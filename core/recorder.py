"""설정한 캡처 영역을 동영상(.mp4)으로 녹화 — 시스템 소리 포함.

구성:
  - 영상: mss 로 지정 영역 프레임을 목표 FPS 로 반복 캡처 → OpenCV(VideoWriter)로 임시 mp4.
  - 소리: soundcard 의 WASAPI 루프백으로 '스피커로 나가는 시스템 소리'를 병렬 캡처 → 임시 wav.
  - 합치기: 녹화가 끝나면 ffmpeg(imageio-ffmpeg 번들)로 영상+소리를 mux 하여 최종 mp4 생성.

GUI 블로킹을 막기 위해 전체 루프를 QThread 에서 돌리고, 오디오는 그 안의
별도 스레드에서 캡처한다. 진행 상황/완료/실패를 시그널로 메인 스레드에 알린다.

동기화:
  - 실제 경과 시간(벽시계)으로 영상 fps 를 재계산(real_fps = 프레임수 / 경과초)하여
    영상 길이를 실제 녹화 시간과 일치시킨다 → 소리와 어긋나지 않는다.

주의:
  - mss / soundcard 객체는 각자 사용하는 스레드 안에서 생성해야 안전하다.
  - 루프백 오디오 장치가 없거나 캡처 실패 시엔 '영상만' 저장하고 안내를 남긴다.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import wave
from typing import Any

import cv2
import mss
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal


def validate_region(region: Any,
                    bounds: dict[str, int] | None = None) -> tuple[bool, str]:
    """영상 캡처 영역이 유효한지 검사. (정상여부, 문제메시지) 반환.

    - 영역 미지정 / 값 손상 / 크기 0 이하 → 오류
    - bounds(가상 데스크톱 경계)가 주어지면, 영역이 화면과 전혀 겹치지 않으면 오류
      (모니터 구성이 바뀌어 좌표가 화면 밖으로 나간 경우 등)
    """
    if not region:
        return False, ("영상 캡처 영역이 지정되어 있지 않습니다.\n"
                       "'2. 캡처 영역'에서 영역을 먼저 지정하세요.")
    try:
        left = int(region["left"]); top = int(region["top"])
        w = int(region["width"]); h = int(region["height"])
    except (KeyError, TypeError, ValueError):
        return False, f"영상 캡처 영역 값이 올바르지 않습니다: {region!r}"
    if w <= 0 or h <= 0:
        return False, (f"영상 캡처 영역 크기가 올바르지 않습니다 "
                       f"(가로 {w} x 세로 {h}).\n영역을 다시 지정하세요.")
    if bounds:
        bl, bt = int(bounds["left"]), int(bounds["top"])
        bw, bh = int(bounds["width"]), int(bounds["height"])
        ix, iy = max(left, bl), max(top, bt)
        ix2, iy2 = min(left + w, bl + bw), min(top + h, bt + bh)
        if ix2 <= ix or iy2 <= iy:
            return False, (
                "영상 캡처 영역이 화면(모니터) 밖에 있습니다.\n"
                f"현재 영역: left={left}, top={top}, {w}x{h}\n"
                f"화면 전체: left={bl}, top={bt}, {bw}x{bh}\n"
                "모니터 구성이 바뀌었을 수 있으니 영역을 다시 지정하세요.")
    return True, ""


def next_video_name(directory: str, base: str, ext: str = ".mp4") -> str:
    """directory 안에서 '{base}_1.mp4', '{base}_2.mp4' … 중 비어있는 다음 이름 반환.

    폴더명(base) 뒤에 숫자를 붙이고, 같은 이름이 이미 있으면 숫자를 1씩 올린다.
    """
    n = 1
    while True:
        name = f"{base}_{n}{ext}"
        if not os.path.exists(os.path.join(directory, name)):
            return name
        n += 1


def _ffmpeg_exe() -> str | None:
    """번들 ffmpeg 실행 파일 경로(없으면 None)."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class VideoRecorder(QThread):
    """capture_region 영역을 목표 FPS 로 녹화하고 시스템 소리를 함께 담아 .mp4 저장."""

    progress = pyqtSignal(float, int)   # (경과초, 저장한 프레임 수)
    note = pyqtSignal(str)              # 진행 중 안내
    finished_ok = pyqtSignal(str, int)  # (파일경로, 총 프레임 수)
    failed = pyqtSignal(str)

    def __init__(self, region: dict[str, int], out_path: str,
                 fps: int = 15, record_audio: bool = True,
                 audio_samplerate: int = 48000,
                 max_seconds: float = 0) -> None:
        super().__init__()
        self._region = region
        self._out_path = out_path
        self._fps = max(1, int(fps))
        self._record_audio = record_audio
        self._audio_sr = int(audio_samplerate)
        self._max_seconds = float(max_seconds)  # 0 = 무제한
        self._stop = False
        # 오디오 스레드 공유 상태
        self._audio_chunks: list[np.ndarray] = []
        self._audio_error: str | None = None
        self._audio_channels = 2

    def stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------- 오디오
    def _record_audio_loop(self) -> None:
        """WASAPI 루프백으로 시스템 소리를 self._audio_chunks 에 모은다."""
        try:
            import soundcard as sc
            speaker = sc.default_speaker()
            mic = sc.get_microphone(speaker.name, include_loopback=True)
            with mic.recorder(samplerate=self._audio_sr, channels=2,
                              blocksize=1024) as rec:
                self.note.emit(f"소리 녹음: '{speaker.name}' 루프백 @ {self._audio_sr}Hz")
                while not self._stop:
                    data = rec.record(numframes=4096)  # (frames, 2) float32
                    self._audio_chunks.append(data.copy())
        except Exception as exc:  # 루프백 장치 없음/권한 등 → 영상만 진행
            self._audio_error = str(exc)

    def _write_wav(self, wav_path: str) -> bool:
        """모은 오디오를 16bit PCM wav 로 저장. 데이터 없으면 False."""
        if not self._audio_chunks:
            return False
        data = np.concatenate(self._audio_chunks, axis=0)  # float32 -1..1
        if data.size == 0:
            return False
        clipped = np.clip(data, -1.0, 1.0)
        pcm16 = (clipped * 32767.0).astype("<i2")
        ch = pcm16.shape[1] if pcm16.ndim > 1 else 1
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(ch)
            wf.setsampwidth(2)
            wf.setframerate(self._audio_sr)
            wf.writeframes(pcm16.tobytes())
        return True

    # ---------------------------------------------------------------- run
    def run(self) -> None:
        out_path = self._out_path
        fps = self._fps
        interval = 1.0 / fps
        base, _ = os.path.splitext(out_path)
        temp_video = base + ".tmp_video.mp4"
        temp_audio = base + ".tmp_audio.wav"

        writer: cv2.VideoWriter | None = None
        audio_thread: threading.Thread | None = None
        frames = 0
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

            # 1) 오디오 캡처 스레드 시작(요청 시)
            if self._record_audio:
                audio_thread = threading.Thread(
                    target=self._record_audio_loop, daemon=True)
                audio_thread.start()

            # 2) 영상 캡처 루프
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            start = time.time()
            next_t = start
            last_note = 0.0
            with mss.mss() as sct:
                while not self._stop:
                    frame_bgra = np.asarray(sct.grab(self._region))
                    frame_bgr = frame_bgra[:, :, :3]
                    if writer is None:
                        h, w = frame_bgr.shape[:2]
                        writer = cv2.VideoWriter(temp_video, fourcc, fps, (w, h))
                        if not writer.isOpened():
                            raise RuntimeError(
                                "동영상 파일을 열 수 없습니다(코덱 문제일 수 있음).")
                        self.note.emit(f"영상 녹화 시작: {w}x{h} @ {fps}fps")
                    writer.write(frame_bgr)
                    frames += 1

                    elapsed = time.time() - start
                    if elapsed - last_note >= 0.5:
                        self.progress.emit(elapsed, frames)
                        last_note = elapsed

                    # 최대 녹화 시간 도달 시 자동 종료
                    if self._max_seconds > 0 and elapsed >= self._max_seconds:
                        self.note.emit(
                            f"설정한 종료 시간({self._max_seconds:g}초) 도달 — 자동 정지")
                        break

                    next_t += interval
                    sleep = next_t - time.time()
                    if sleep > 0:
                        time.sleep(sleep)
                    else:
                        next_t = time.time()

            total_elapsed = time.time() - start
            if writer is not None:
                writer.release()

            # 3) 오디오 스레드 정지 대기 + wav 저장
            has_audio = False
            if audio_thread is not None:
                # 소리가 흐르는 중이면 즉시 끝나고, 완전 무음이면 최대 2초만 대기
                audio_thread.join(timeout=2.0)
                if self._audio_error:
                    self.note.emit(
                        f"⚠ 소리 녹음 실패 → 영상만 저장합니다: {self._audio_error}")
                else:
                    has_audio = self._write_wav(temp_audio)
                    if not has_audio:
                        self.note.emit("⚠ 녹음된 소리가 없어 영상만 저장합니다.")

            if frames == 0:
                raise RuntimeError("녹화된 프레임이 없습니다.")

            real_fps = frames / total_elapsed if total_elapsed > 0 else fps

            # 4) ffmpeg 로 영상 fps 보정 + (있으면) 소리 합치기
            self.note.emit("파일 마무리 중(영상/소리 합치기)…")
            ok = self._mux(temp_video, temp_audio if has_audio else None,
                           out_path, real_fps)
            if not ok:
                # ffmpeg 실패/부재 → 임시 영상만이라도 최종본으로
                if os.path.exists(out_path):
                    os.remove(out_path)
                os.replace(temp_video, out_path)
                self.note.emit("⚠ ffmpeg 합치기 실패 — 소리 없이 영상만 저장했습니다.")

            # 5) 임시 파일 정리
            for p in (temp_video, temp_audio):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

            self.finished_ok.emit(out_path, frames)
        except Exception as exc:
            if writer is not None:
                try:
                    writer.release()
                except Exception:
                    pass
            self.failed.emit(str(exc))

    # ---------------------------------------------------------------- mux
    def _mux(self, video_path: str, audio_path: str | None,
             out_path: str, real_fps: float) -> bool:
        """ffmpeg 로 영상(fps 보정) + 소리를 최종 mp4 로 합친다. 성공하면 True."""
        ff = _ffmpeg_exe()
        if not ff:
            return False
        fps_arg = f"{max(real_fps, 0.1):.6f}"
        cmd = [ff, "-y",
               "-r", fps_arg, "-i", video_path]
        if audio_path:
            cmd += ["-i", audio_path]
        # 스트림을 명시적으로 매핑 → 영상 트랙이 빠지는 일을 방지
        cmd += ["-map", "0:v:0"]
        if audio_path:
            cmd += ["-map", "1:a:0"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast"]
        if audio_path:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
        cmd += [out_path]

        # 콘솔 창이 뜨지 않도록(Windows)
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=creationflags)
            if proc.returncode != 0:
                tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
                self.note.emit("ffmpeg 오류: " + (tail[-1] if tail else "알 수 없음"))
                return False
            return True
        except Exception as exc:
            self.note.emit(f"ffmpeg 실행 실패: {exc}")
            return False
