"""동영상의 특정 구간(시작~끝)을 잘라 고품질 GIF 로 변환.

구현:
  - 번들 ffmpeg(imageio-ffmpeg)로 변환한다. 별도 설치 불필요.
  - 좋은 색감을 위해 2-pass 대신 filter_complex 한 번에 palettegen→paletteuse 를
    적용한다(fps·scale 적용 후 최적 팔레트 생성 → 그 팔레트로 다시 그리기).
  - 구간은 `-ss 시작 -t 길이` 로 지정(길이 = 끝 - 시작). -ss 를 -i 앞에 두어
    빠르게 탐색한다.

GUI 블로킹을 막기 위해 변환을 QThread 에서 돌리고 완료/실패를 시그널로 알린다.
"""
from __future__ import annotations

import os
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal


def _ffmpeg_exe() -> str | None:
    """번들 ffmpeg 실행 파일 경로(없으면 None)."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def probe_duration(path: str) -> float:
    """동영상 길이(초)를 반환. 실패하면 0.0.

    ffprobe 대신 OpenCV 로 프레임 수 / fps 를 계산한다(번들에 ffprobe 가 없어서).
    """
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        cap.release()
        if fps > 0 and frames > 0:
            return float(frames) / float(fps)
    except Exception:
        pass
    return 0.0


def default_gif_path(video_path: str) -> str:
    """같은 폴더에 '영상이름.gif'. 이미 있으면 '_1', '_2' … 를 붙인다."""
    base, _ = os.path.splitext(video_path)
    cand = base + ".gif"
    n = 1
    while os.path.exists(cand):
        cand = f"{base}_{n}.gif"
        n += 1
    return cand


class GifMaker(QThread):
    """동영상의 [start, end] 구간을 GIF 로 변환하는 작업 스레드."""

    note = pyqtSignal(str)
    finished_ok = pyqtSignal(str)   # 저장 경로
    failed = pyqtSignal(str)

    def __init__(self, video_path: str, out_path: str,
                 start: float, end: float,
                 fps: int = 12, width: int = 0) -> None:
        """
        start/end : 구간(초). end<=0 이면 영상 끝까지.
        fps       : GIF 프레임레이트.
        width     : 가로 픽셀(0 이면 원본 크기 유지, 세로는 비율 유지).
        """
        super().__init__()
        self._video = video_path
        self._out = out_path
        self._start = max(0.0, float(start))
        self._end = float(end)
        self._fps = max(1, int(fps))
        self._width = max(0, int(width))

    def run(self) -> None:
        try:
            if not os.path.exists(self._video):
                raise RuntimeError(f"동영상 파일을 찾을 수 없습니다: {self._video}")

            ff = _ffmpeg_exe()
            if not ff:
                raise RuntimeError(
                    "ffmpeg 를 찾을 수 없습니다(imageio-ffmpeg 미설치).")

            # 구간 길이 계산: end 가 0 이하이거나 start 보다 작으면 '끝까지'
            duration = None
            if self._end > 0 and self._end > self._start:
                duration = self._end - self._start

            # scale 필터: width 0 이면 크기 유지, 아니면 가로 고정·세로 비율 유지
            if self._width > 0:
                # -2 : 코덱 요구에 맞춰 짝수로 자동 보정
                scale = f"scale={self._width}:-2:flags=lanczos,"
            else:
                scale = ""
            vf = (f"fps={self._fps},{scale}"
                  "split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
                  "[s1][p]paletteuse=dither=bayer:bayer_scale=3")

            os.makedirs(os.path.dirname(os.path.abspath(self._out)), exist_ok=True)

            cmd = [ff, "-y"]
            if self._start > 0:
                cmd += ["-ss", f"{self._start:.3f}"]
            cmd += ["-i", self._video]
            if duration is not None:
                cmd += ["-t", f"{duration:.3f}"]
            cmd += ["-vf", vf, "-loop", "0", self._out]

            seg = (f"{self._start:.1f}~"
                   f"{'끝' if duration is None else f'{self._end:.1f}'}초")
            self.note.emit(
                f"GIF 변환 중… 구간 {seg}, {self._fps}fps"
                + (f", 가로 {self._width}px" if self._width else "") + " …")

            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=creationflags)
            if proc.returncode != 0:
                tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError(
                    "ffmpeg 오류: " + (tail[-1] if tail else "알 수 없음"))
            if not os.path.exists(self._out) or os.path.getsize(self._out) == 0:
                raise RuntimeError("GIF 파일이 생성되지 않았습니다.")

            self.finished_ok.emit(self._out)
        except Exception as exc:
            self.failed.emit(str(exc))
