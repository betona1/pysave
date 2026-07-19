"""ShotKey 메인 윈도우.

기능:
  - 모니터 식별/선택, 선택 모니터 전체 캡처 또는 드래그 영역 지정
  - 대상: 열린 창(프로그램) 선택해 포커스 후 키 입력  /  또는 좌표 클릭
  - 페이지 넘김 키(기본 right), 반복 횟수, 딜레이 설정
  - 전역 핫키 등록/시작/정지, 즉시 1회 테스트
  - 캡처 결과 PNG → PDF 병합
"""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QApplication, QCheckBox, QInputDialog, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from core import config as cfg_mod
from core import monitors, pdf, windows
from core import automator, capturer
from core.hotkey import HotkeyManager
from core.recorder import (
    VideoRecorder, next_video_name as recorder_next_name, validate_region,
)
from core.gif_maker import GifMaker, probe_duration, default_gif_path
from core.worker import CaptureWorker
from ui.hotkey_capture import HotkeyCaptureDialog
from ui.monitor_identifier import MonitorIdentifier
from ui.point_picker import PointPicker
from ui.region_picker import RegionPicker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ShotKey — 자동 화면 캡처")
        self.config = cfg_mod.load_config()

        self.hotkey = HotkeyManager()
        self.hotkey.triggered.connect(self.on_hotkey_triggered)
        self.hotkey.error.connect(lambda m: self.log(m))

        self._identifier = MonitorIdentifier()
        self._picker: RegionPicker | None = None
        self._worker: CaptureWorker | None = None
        self._recorder: VideoRecorder | None = None
        self._gifmaker: GifMaker | None = None
        self._gif_duration: float = 0.0
        self._running = False

        self._build_ui()
        self._load_into_ui()

        admin = windows.is_admin()
        self.log(f"ShotKey 시작 — 관리자 권한: {'예' if admin else '아니오'}")
        if not admin:
            self.log(
                "ℹ 대상 앱이 관리자 권한이면 키가 안 들어갑니다. "
                "안 넘어가면 '관리자 권한으로 재실행'을 눌러보세요."
            )

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        # --- 모니터 ---
        mon_box = QGroupBox("1. 모니터")
        mon_l = QHBoxLayout(mon_box)
        self.cmb_monitor = QComboBox()
        btn_identify = QPushButton("모니터 식별")
        btn_identify.clicked.connect(self.on_identify)
        btn_refresh_mon = QPushButton("새로고침")
        btn_refresh_mon.clicked.connect(self.refresh_monitors)
        btn_full = QPushButton("선택 모니터 전체 캡처 영역으로")
        btn_full.clicked.connect(self.on_use_full_monitor)
        mon_l.addWidget(QLabel("대상 모니터:"))
        mon_l.addWidget(self.cmb_monitor, 1)
        mon_l.addWidget(btn_identify)
        mon_l.addWidget(btn_refresh_mon)
        mon_l.addWidget(btn_full)
        root.addWidget(mon_box)

        # --- 캡처 영역 ---
        reg_box = QGroupBox("2. 캡처 영역")
        reg_l = QHBoxLayout(reg_box)
        self.lbl_region = QLabel("-")
        btn_pick_region = QPushButton("영역 드래그 지정")
        btn_pick_region.clicked.connect(self.on_pick_region)
        reg_l.addWidget(QLabel("영역:"))
        reg_l.addWidget(self.lbl_region, 1)
        reg_l.addWidget(btn_pick_region)
        root.addWidget(reg_box)

        # --- 대상(키를 누를 곳) ---
        tgt_box = QGroupBox("3. 키를 보낼 대상")
        tgt_l = QVBoxLayout(tgt_box)
        row_mode = QHBoxLayout()
        self.rb_window = QRadioButton("열린 창 선택")
        self.rb_click = QRadioButton("좌표 클릭")
        self.rb_window.setChecked(True)
        self.rb_window.toggled.connect(self._update_target_enabled)
        row_mode.addWidget(self.rb_window)
        row_mode.addWidget(self.rb_click)
        row_mode.addStretch(1)
        tgt_l.addLayout(row_mode)

        row_win = QHBoxLayout()
        self.cmb_window = QComboBox()
        self.cmb_window.setMinimumWidth(280)
        btn_refresh_win = QPushButton("창 목록 새로고침")
        btn_refresh_win.clicked.connect(self.refresh_windows)
        self.btn_win_region = QPushButton("이 창 위치/크기로 캡처 영역 지정")
        self.btn_win_region.clicked.connect(self.on_use_window_region)
        row_win.addWidget(QLabel("대상 창:"))
        row_win.addWidget(self.cmb_window, 1)
        row_win.addWidget(btn_refresh_win)
        row_win.addWidget(self.btn_win_region)
        tgt_l.addLayout(row_win)

        row_click = QHBoxLayout()
        self.lbl_click = QLabel("-")
        btn_pick_click = QPushButton("화면 클릭해 좌표 지정")
        btn_pick_click.clicked.connect(self.on_pick_click)
        row_click.addWidget(QLabel("클릭 좌표:"))
        row_click.addWidget(self.lbl_click, 1)
        row_click.addWidget(btn_pick_click)
        tgt_l.addLayout(row_click)
        root.addWidget(tgt_box)

        # --- 동작 설정 ---
        act_box = QGroupBox("4. 동작 설정")
        act_v = QVBoxLayout(act_box)

        # 캡처 모드: 자동(키 전송+반복) / 수동(핫키 누를 때마다 1장, 키 전송 안 함)
        mode_l = QHBoxLayout()
        self.rb_mode_auto = QRadioButton("자동 (키 전송 + 반복 캡처)")
        self.rb_mode_manual = QRadioButton("수동 (핫키 누를 때마다 1장만 저장)")
        self.rb_mode_auto.setChecked(True)
        self.rb_mode_auto.toggled.connect(self._on_mode_changed)
        mode_l.addWidget(QLabel("캡처 모드:"))
        mode_l.addWidget(self.rb_mode_auto)
        mode_l.addWidget(self.rb_mode_manual)
        mode_l.addStretch(1)
        act_v.addLayout(mode_l)

        act_l = QHBoxLayout()
        self.txt_key = QLineEdit("right")
        self.txt_key.setMaximumWidth(90)
        self.spn_repeat = QSpinBox()
        self.spn_repeat.setRange(1, 1000000)
        self.spn_delay = QDoubleSpinBox()
        self.spn_delay.setRange(0.0, 600.0)   # 최대 10분까지 (30초 등 입력 가능)
        self.spn_delay.setSingleStep(0.5)
        self.spn_delay.setDecimals(2)
        act_l.addWidget(QLabel("페이지 넘김 키:"))
        act_l.addWidget(self.txt_key)
        act_l.addSpacing(12)
        act_l.addWidget(QLabel("반복 횟수:"))
        act_l.addWidget(self.spn_repeat)
        act_l.addSpacing(12)
        act_l.addWidget(QLabel("딜레이(초):"))
        act_l.addWidget(self.spn_delay)
        act_l.addStretch(1)
        act_v.addLayout(act_l)

        # 끝 페이지 → 반복 횟수 자동 계산 (예: 2쪽씩 보기면 끝페이지/2 + 1)
        act_l2 = QHBoxLayout()
        self.spn_end_page = QSpinBox()
        self.spn_end_page.setRange(0, 1000000)
        self.spn_end_page.setSpecialValueText("(미사용)")  # 0이면 사용 안 함
        self.spn_per_view = QSpinBox()
        self.spn_per_view.setRange(1, 4)
        self.spn_per_view.setValue(2)
        self.chk_auto_pdf = QCheckBox("완료 후 자동 PDF 생성")
        self.chk_auto_pdf.setChecked(True)
        act_l2.addWidget(QLabel("끝 페이지:"))
        act_l2.addWidget(self.spn_end_page)
        act_l2.addWidget(QLabel("한 화면당 쪽수:"))
        act_l2.addWidget(self.spn_per_view)
        self.lbl_calc = QLabel("→ 반복 0회")
        act_l2.addWidget(self.lbl_calc)
        act_l2.addSpacing(12)
        act_l2.addWidget(self.chk_auto_pdf)
        act_l2.addStretch(1)
        act_v.addLayout(act_l2)

        # 끝 페이지/쪽수 바뀌면 반복 횟수 자동 갱신
        self.spn_end_page.valueChanged.connect(self._recalc_repeat)
        self.spn_per_view.valueChanged.connect(self._recalc_repeat)
        root.addWidget(act_box)

        # --- 핫키 & 저장 ---
        hk_box = QGroupBox("5. 핫키 / 저장 경로")
        hk_l = QHBoxLayout(hk_box)
        self.txt_hotkey = QLineEdit("<f8>")
        self.txt_hotkey.setMaximumWidth(140)
        btn_cap_hotkey = QPushButton("핫키 입력")
        btn_cap_hotkey.clicked.connect(self.on_capture_hotkey)
        self.txt_savedir = QLineEdit("./captures")
        btn_browse = QPushButton("폴더…")
        btn_browse.clicked.connect(self.on_browse_savedir)
        hk_l.addWidget(QLabel("트리거 핫키:"))
        hk_l.addWidget(self.txt_hotkey)
        hk_l.addWidget(btn_cap_hotkey)
        hk_l.addSpacing(12)
        hk_l.addWidget(QLabel("저장 폴더:"))
        hk_l.addWidget(self.txt_savedir, 1)
        hk_l.addWidget(btn_browse)
        root.addWidget(hk_box)

        # --- 동영상 녹화 ---
        vid_box = QGroupBox("6. 동영상 녹화 (설정한 캡처 영역)")
        vid_v = QVBoxLayout(vid_box)

        # 동영상 저장 폴더(사진과 별도로 지정 가능, 비우면 사진 폴더 사용)
        vdir_l = QHBoxLayout()
        self.txt_videodir = QLineEdit()
        self.txt_videodir.setPlaceholderText("(비우면 사진 저장 폴더에 저장)")
        self.txt_videodir.editingFinished.connect(self._refresh_video_name)
        btn_video_browse = QPushButton("폴더…")
        btn_video_browse.clicked.connect(self.on_browse_videodir)
        vdir_l.addWidget(QLabel("동영상 저장 폴더:"))
        vdir_l.addWidget(self.txt_videodir, 1)
        vdir_l.addWidget(btn_video_browse)
        vid_v.addLayout(vdir_l)

        # 파일명(기본: 폴더명_숫자, 이미 있으면 숫자+1) — 수정 가능
        vname_l = QHBoxLayout()
        self.txt_videoname = QLineEdit()
        self.txt_videoname.setPlaceholderText("폴더명_1.mp4")
        btn_name_auto = QPushButton("자동 이름")
        btn_name_auto.clicked.connect(self._refresh_video_name)
        vname_l.addWidget(QLabel("파일명:"))
        vname_l.addWidget(self.txt_videoname, 1)
        vname_l.addWidget(btn_name_auto)
        vid_v.addLayout(vname_l)

        # FPS + 소리 + 자동 종료 + 녹화 버튼
        vrec_l = QHBoxLayout()
        self.spn_fps = QSpinBox()
        self.spn_fps.setRange(1, 60)
        self.spn_fps.setValue(15)
        self.spn_fps.setSuffix(" fps")
        self.chk_audio = QCheckBox("시스템 소리 함께 녹음")
        self.chk_audio.setChecked(True)
        # 자동 종료 시간: 시 / 분 / 초 (모두 0이면 무제한)
        self.spn_h = QSpinBox(); self.spn_h.setRange(0, 99); self.spn_h.setSuffix(" 시")
        self.spn_m = QSpinBox(); self.spn_m.setRange(0, 59); self.spn_m.setSuffix(" 분")
        self.spn_s = QSpinBox(); self.spn_s.setRange(0, 59); self.spn_s.setSuffix(" 초")
        self.btn_record = QPushButton("⏺ 영역 동영상 녹화 시작")
        self.btn_record.clicked.connect(self.on_toggle_record)
        self.lbl_record = QLabel("대기 중")
        vrec_l.addWidget(QLabel("프레임:"))
        vrec_l.addWidget(self.spn_fps)
        vrec_l.addSpacing(8)
        vrec_l.addWidget(self.chk_audio)
        vrec_l.addSpacing(8)
        vrec_l.addWidget(QLabel("자동 종료:"))
        vrec_l.addWidget(self.spn_h)
        vrec_l.addWidget(self.spn_m)
        vrec_l.addWidget(self.spn_s)
        vrec_l.addWidget(QLabel("(모두 0=무제한)"))
        vrec_l.addSpacing(8)
        vrec_l.addWidget(self.btn_record)
        vrec_l.addWidget(self.lbl_record, 1)
        vid_v.addLayout(vrec_l)
        root.addWidget(vid_box)

        # --- 동영상 → GIF 변환 ---
        gif_box = QGroupBox("7. 동영상 → GIF 변환 (특정 구간)")
        gif_v = QVBoxLayout(gif_box)

        # 원본 동영상 선택
        gsrc_l = QHBoxLayout()
        self.txt_gif_src = QLineEdit()
        self.txt_gif_src.setPlaceholderText("변환할 동영상(.mp4) 파일 선택")
        btn_gif_browse = QPushButton("동영상 선택…")
        btn_gif_browse.clicked.connect(self.on_browse_gif_src)
        gsrc_l.addWidget(QLabel("원본 동영상:"))
        gsrc_l.addWidget(self.txt_gif_src, 1)
        gsrc_l.addWidget(btn_gif_browse)
        gif_v.addLayout(gsrc_l)

        # 구간(시작~끝, 초) + 총 길이
        gseg_l = QHBoxLayout()
        self.spn_gif_start = QDoubleSpinBox()
        self.spn_gif_start.setRange(0.0, 999999.0)
        self.spn_gif_start.setDecimals(1)
        self.spn_gif_start.setSingleStep(0.5)
        self.spn_gif_start.setSuffix(" 초")
        self.spn_gif_end = QDoubleSpinBox()
        self.spn_gif_end.setRange(0.0, 999999.0)
        self.spn_gif_end.setDecimals(1)
        self.spn_gif_end.setSingleStep(0.5)
        self.spn_gif_end.setSuffix(" 초")
        self.spn_gif_end.setSpecialValueText("(끝까지)")  # 0 이면 끝까지
        self.lbl_gif_dur = QLabel("총 길이 -")
        gseg_l.addWidget(QLabel("구간 시작:"))
        gseg_l.addWidget(self.spn_gif_start)
        gseg_l.addWidget(QLabel("끝:"))
        gseg_l.addWidget(self.spn_gif_end)
        gseg_l.addSpacing(8)
        gseg_l.addWidget(self.lbl_gif_dur)
        gseg_l.addStretch(1)
        gif_v.addLayout(gseg_l)

        # GIF 옵션(fps, 가로 폭) + 변환 버튼
        gopt_l = QHBoxLayout()
        self.spn_gif_fps = QSpinBox()
        self.spn_gif_fps.setRange(1, 50)
        self.spn_gif_fps.setValue(12)
        self.spn_gif_fps.setSuffix(" fps")
        self.spn_gif_width = QSpinBox()
        self.spn_gif_width.setRange(0, 4096)
        self.spn_gif_width.setValue(480)
        self.spn_gif_width.setSpecialValueText("(원본)")  # 0 이면 원본 크기
        self.spn_gif_width.setSuffix(" px")
        self.btn_gif_make = QPushButton("🎞 GIF 만들기")
        self.btn_gif_make.clicked.connect(self.on_make_gif)
        self.lbl_gif_status = QLabel("대기 중")
        gopt_l.addWidget(QLabel("프레임:"))
        gopt_l.addWidget(self.spn_gif_fps)
        gopt_l.addSpacing(8)
        gopt_l.addWidget(QLabel("가로 폭:"))
        gopt_l.addWidget(self.spn_gif_width)
        gopt_l.addSpacing(8)
        gopt_l.addWidget(self.btn_gif_make)
        gopt_l.addWidget(self.lbl_gif_status, 1)
        gif_v.addLayout(gopt_l)
        root.addWidget(gif_box)

        # --- 실행 버튼 ---
        run_l = QHBoxLayout()
        self.btn_start = QPushButton("● 핫키 대기 시작")
        self.btn_start.clicked.connect(self.on_toggle_start)
        btn_run = QPushButton("▶ 폴더 지정 후 자동 캡처 시작")
        btn_run.clicked.connect(self.on_start_with_folder)
        self.btn_stop = QPushButton("■ 캡처 정지")
        self.btn_stop.clicked.connect(self.on_stop_capture)
        self.btn_stop.setEnabled(False)
        btn_save = QPushButton("설정 저장")
        btn_save.clicked.connect(self.on_save_config)
        btn_pdf = QPushButton("PNG → PDF 생성")
        btn_pdf.clicked.connect(self.on_make_pdf)
        self.btn_admin = QPushButton("관리자 권한으로 재실행")
        self.btn_admin.clicked.connect(self.on_relaunch_admin)
        run_l.addWidget(self.btn_start)
        run_l.addWidget(btn_run)
        run_l.addWidget(self.btn_stop)
        run_l.addWidget(btn_save)
        run_l.addWidget(btn_pdf)
        run_l.addWidget(self.btn_admin)
        root.addLayout(run_l)

        # --- 로그 ---
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        root.addWidget(self.log_view, 1)

        self.setCentralWidget(central)
        self.resize(820, 640)
        self._update_target_enabled()

    # ----------------------------------------------------- config <-> UI
    def _load_into_ui(self) -> None:
        c = self.config
        self.refresh_monitors()
        idx = c.get("monitor_index", 1)
        self._select_monitor_index(idx)

        region = c.get("capture_region") or {}
        self._set_region_label(region)

        mode = c.get("target_mode", "window")
        self.rb_window.setChecked(mode == "window")
        self.rb_click.setChecked(mode == "click")
        self.refresh_windows()
        title = c.get("target_window_title")
        if title:
            # 정확히 일치하는 창이 있을 때만 선택(없으면 유령 항목 만들지 않음)
            i = self.cmb_window.findText(title)
            if i >= 0:
                self.cmb_window.setCurrentIndex(i)
            else:
                self.log(
                    f"저장된 대상 창 '{title}' 을(를) 현재 목록에서 못 찾음 — "
                    "'창 목록 새로고침' 후 실제 창(책 제목)을 선택하세요"
                )
        click = c.get("click_position")
        self.lbl_click.setText(str(click) if click else "-")

        self.txt_key.setText(c.get("page_turn_key", "right"))
        self.spn_per_view.setValue(int(c.get("pages_per_view", 2)))
        self.spn_end_page.setValue(int(c.get("end_page", 0)))
        self.spn_repeat.setValue(int(c.get("repeat_count", 1)))
        self.spn_delay.setValue(float(c.get("action_delay", 3.0)))
        self.chk_auto_pdf.setChecked(bool(c.get("auto_pdf", True)))
        self.txt_hotkey.setText(c.get("trigger_hotkey", "<f8>"))
        self.txt_savedir.setText(c.get("save_dir", "./captures"))
        self.spn_fps.setValue(int(c.get("video_fps", 15)))
        self.txt_videodir.setText(c.get("video_dir", "") or "")
        self.chk_audio.setChecked(bool(c.get("record_audio", True)))
        total = int(c.get("video_max_seconds", 0))
        self.spn_h.setValue(total // 3600)
        self.spn_m.setValue((total % 3600) // 60)
        self.spn_s.setValue(total % 60)
        self._refresh_video_name()
        mode = c.get("capture_mode", "auto")
        self.rb_mode_manual.setChecked(mode == "manual")
        self.rb_mode_auto.setChecked(mode != "manual")
        self._update_target_enabled()
        self._update_calc_label()
        self._on_mode_changed()

    def _collect_from_ui(self) -> dict:
        c = dict(self.config)
        c["monitor_index"] = self._current_monitor_index()
        c["capture_region"] = self._current_region or c.get("capture_region")
        c["target_mode"] = "window" if self.rb_window.isChecked() else "click"
        c["target_window_title"] = self.cmb_window.currentText() or None
        c["target_window_hwnd"] = self._current_hwnd()
        c["click_position"] = self._current_click
        c["page_turn_key"] = self.txt_key.text().strip() or "right"
        c["repeat_count"] = self.spn_repeat.value()
        c["action_delay"] = self.spn_delay.value()
        c["end_page"] = self.spn_end_page.value()
        c["pages_per_view"] = self.spn_per_view.value()
        c["auto_pdf"] = self.chk_auto_pdf.isChecked()
        c["capture_mode"] = "manual" if self.rb_mode_manual.isChecked() else "auto"
        c["trigger_hotkey"] = self.txt_hotkey.text().strip() or "<f8>"
        c["save_dir"] = self.txt_savedir.text().strip() or "./captures"
        c["video_fps"] = self.spn_fps.value()
        c["video_dir"] = self.txt_videodir.text().strip()
        c["record_audio"] = self.chk_audio.isChecked()
        c["video_max_seconds"] = (
            self.spn_h.value() * 3600 + self.spn_m.value() * 60 + self.spn_s.value())
        return c

    def _recalc_repeat(self) -> None:
        """끝 페이지 > 0 이면 반복 횟수 = 끝페이지 // 쪽수 + 1 로 자동 설정."""
        end = self.spn_end_page.value()
        per = max(1, self.spn_per_view.value())
        if end > 0:
            rep = end // per + 1
            self.spn_repeat.setValue(rep)
        self._update_calc_label()

    def _update_calc_label(self) -> None:
        end = self.spn_end_page.value()
        per = max(1, self.spn_per_view.value())
        if end > 0:
            self.lbl_calc.setText(f"→ 반복 {end // per + 1}회")
        else:
            self.lbl_calc.setText("→ 반복 수동")

    @staticmethod
    def _persistable(cfg: dict) -> dict:
        """config.json 에 저장할 dict (세션마다 바뀌는 HWND 는 제외)."""
        c = dict(cfg)
        c.pop("target_window_hwnd", None)
        return c

    # ------------------------------------------------------ state helpers
    _current_region: dict | None = None
    _current_click = None

    def _set_region_label(self, region: dict) -> None:
        if region:
            self._current_region = region
            self.lbl_region.setText(
                f"left={region.get('left')}, top={region.get('top')}, "
                f"{region.get('width')}x{region.get('height')}"
            )

    # ------------------------------------------------------------ monitors
    def refresh_monitors(self) -> None:
        self.cmb_monitor.clear()
        for mon in monitors.list_monitors():
            self.cmb_monitor.addItem(mon["label"], mon["index"])

    def _current_monitor_index(self) -> int:
        data = self.cmb_monitor.currentData()
        return int(data) if data is not None else 1

    def _select_monitor_index(self, index: int) -> None:
        i = self.cmb_monitor.findData(index)
        if i >= 0:
            self.cmb_monitor.setCurrentIndex(i)

    def on_identify(self) -> None:
        self.refresh_monitors()
        self._identifier.show(2000)
        self.log("모니터 식별 — 각 화면에 번호 표시(2초)")

    def on_use_full_monitor(self) -> None:
        idx = self._current_monitor_index()
        region = monitors.monitor_region(idx)
        if region is None:
            QMessageBox.warning(self, "오류", "모니터 정보를 가져올 수 없습니다.")
            return
        self._set_region_label(region)
        self.log(f"모니터 {idx} 전체를 캡처 영역으로 설정: {region}")

    # -------------------------------------------------------------- region
    def _selected_monitor_bounds(self) -> dict | None:
        """선택한 모니터의 영역(전체=가상데스크톱이면 None)."""
        idx = self._current_monitor_index()
        if idx == 0:
            return None  # 전체 가상 데스크톱
        return monitors.monitor_region(idx)

    def on_pick_region(self) -> None:
        bounds = self._selected_monitor_bounds()
        self._picker = RegionPicker()
        self._picker.region_selected.connect(self._on_region_selected)
        self._picker.cancelled.connect(lambda: self.log("영역 지정 취소"))
        self.showMinimized()
        self._picker.start(bounds)

    def _on_region_selected(self, region: dict) -> None:
        self._set_region_label(region)
        self.showNormal()
        self.activateWindow()
        self.log(f"영역 지정: {region}")

    def on_use_window_region(self) -> None:
        title = self.cmb_window.currentText().strip()
        hwnd = self._current_hwnd()
        if not title and hwnd is None:
            QMessageBox.warning(self, "오류", "먼저 대상 창을 선택하세요.")
            return
        region = None
        if hwnd is not None:
            region = windows.region_of_hwnd(hwnd)
        if region is None and title:
            region = windows.window_region(title)  # 폴백
        if region is None:
            QMessageBox.warning(
                self, "오류",
                f"'{title}' 창 위치를 가져올 수 없습니다.\n"
                "창이 최소화되어 있지 않은지 확인하고 '창 목록 새로고침' 후 다시 시도하세요."
            )
            return
        self._set_region_label(region)
        self.log(f"'{title}' 창 영역을 캡처 영역으로 설정: {region}")

    # -------------------------------------------------------------- target
    def _update_target_enabled(self) -> None:
        win = self.rb_window.isChecked()
        self.cmb_window.setEnabled(win)
        self.btn_win_region.setEnabled(win)
        self.lbl_click.setEnabled(not win)

    def _on_mode_changed(self) -> None:
        """수동 모드면 키 전송 관련 입력을 비활성화(캡처만 함)."""
        manual = self.rb_mode_manual.isChecked()
        # 수동 모드: 키 전송 대상/페이지키/반복은 의미 없음
        self.txt_key.setDisabled(manual)
        self.spn_repeat.setDisabled(manual)
        self.spn_end_page.setDisabled(manual)
        self.spn_per_view.setDisabled(manual)
        if manual:
            self.log(
                "수동 모드: 직접 페이지를 넘기고, 핫키(기본 우측화살표)를 누르면 "
                "그 화면을 1장 저장합니다. (앱에 키를 보내지 않음)"
            )

    def refresh_windows(self) -> None:
        if not windows.available():
            self.log("창 제어 기능 사용 불가(pygetwindow 미설치).")
            return
        cur = self.cmb_window.currentText()
        self.cmb_window.clear()
        wins = windows.list_windows()
        for w in wins:
            self.cmb_window.addItem(w["title"], w["hwnd"])  # 텍스트=제목, data=HWND
        self.log(f"창 목록 {len(wins)}개 갱신")
        if cur:
            i = self.cmb_window.findText(cur)
            if i >= 0:
                self.cmb_window.setCurrentIndex(i)

    def _current_hwnd(self):
        data = self.cmb_window.currentData()
        return int(data) if data else None

    def on_pick_click(self) -> None:
        bounds = self._selected_monitor_bounds()
        self._point_picker = PointPicker()
        self._point_picker.point_selected.connect(self._on_point_selected)
        self._point_picker.cancelled.connect(lambda: self.log("좌표 클릭 지정 취소"))
        self.showMinimized()
        self._point_picker.start(bounds)

    def _on_point_selected(self, x: int, y: int) -> None:
        self._current_click = [int(x), int(y)]
        self.lbl_click.setText(str(self._current_click))
        self.showNormal()
        self.activateWindow()
        self.log(f"클릭 좌표 지정: {self._current_click}")

    # -------------------------------------------------------------- hotkey
    def on_capture_hotkey(self) -> None:
        dlg = HotkeyCaptureDialog(self)
        if dlg.exec() and dlg.result_hotkey:
            self.txt_hotkey.setText(dlg.result_hotkey)
            self.log(f"핫키 설정: {dlg.result_hotkey}")

    def on_toggle_start(self) -> None:
        if self._running:
            self.hotkey.stop()
            self._running = False
            self.btn_start.setText("● 핫키 시작")
            self.log("핫키 정지")
            return
        self.config = self._collect_from_ui()
        cfg_mod.save_config(self._persistable(self.config))
        hk = self.config["trigger_hotkey"]
        if self.hotkey.start(hk):
            self._running = True
            self.btn_start.setText("■ 핫키 정지")
            self.log(f"핫키 시작: {hk} — 누르면 캡처 시퀀스 실행")

    def on_hotkey_triggered(self) -> None:
        if self.rb_mode_manual.isChecked():
            self.log("핫키 감지 → 현재 화면 1장 저장(수동)")
            self._run_sequence(skip_action=True)
        else:
            self.log("핫키 감지 → 자동 캡처 시퀀스 시작")
            self._run_sequence()

    # ------------------------------------------------------------- running
    def on_test_run(self) -> None:
        self.config = self._collect_from_ui()
        self._run_sequence()

    def on_start_with_folder(self) -> None:
        """저장 폴더를 먼저 고르고(없으면 새로 만들고) 바로 자동 캡처 시작."""
        start = self.txt_savedir.text().strip() or "./captures"
        if not os.path.isabs(start):
            start = cfg_mod.resolve_save_dir({"save_dir": start})
        d = QFileDialog.getExistingDirectory(
            self, "저장 폴더 선택 또는 새로 만들기", start,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not d:
            self.log("폴더 선택 취소 — 시작하지 않음")
            return
        self.txt_savedir.setText(d)
        self.config = self._collect_from_ui()
        cfg_mod.save_config(self._persistable(self.config))  # 즉시 저장(재실행 유지)
        self.log(f"저장 폴더: {d}")
        self._run_sequence()

    def on_stop_capture(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self.log("정지 요청 — 현재 장 완료 후 중단합니다.")

    def _run_sequence(self, skip_action: bool = False) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.log("이미 캡처가 진행 중입니다.")
            return
        cfg = self._collect_from_ui()
        if not cfg.get("capture_region"):
            QMessageBox.warning(self, "오류", "캡처 영역을 먼저 지정하세요.")
            return
        save_dir = cfg_mod.resolve_save_dir(cfg)
        self._run_save_dir = save_dir

        if skip_action:
            # 수동 모드: 키 전송/포커스 없음, 1장만, 매번 PDF 만들지 않음
            cfg = dict(cfg)
            cfg["repeat_count"] = 1
            self._run_auto_pdf = False
            self.hotkey.set_suppressed(True)  # 캡처 중 중복 트리거 방지(디바운스)
            self._worker = CaptureWorker(cfg, save_dir, skip_action=True)
        else:
            self._run_auto_pdf = bool(cfg.get("auto_pdf", True))
            # 캡처 시작 전, 메인 스레드에서 대상 창을 확실히 맨 앞으로 올린다
            if cfg.get("target_mode") == "window":
                hwnd = cfg.get("target_window_hwnd")
                if not hwnd:
                    QMessageBox.warning(
                        self, "대상 창 없음",
                        "키를 보낼 창이 선택되지 않았습니다.\n"
                        "'창 목록 새로고침' 후 책 제목 창(예: '나의 사주명리')을 선택하세요.",
                    )
                    return
                ok = windows.activate_hwnd(int(hwnd))
                fg = windows.get_foreground_title()
                self.log(f"대상 창 포커스 시도: 활성화={ok}, 현재 포커스='{fg}'")
            # 자동화가 보낼 키로 자기 핫키가 다시 눌리는 무한루프 방지
            self.hotkey.set_suppressed(True)
            self.log(
                f"자동 캡처 시작 — {cfg.get('repeat_count', 1)}회, "
                f"딜레이 {cfg.get('action_delay', 0.3)}초, 키 '{cfg.get('page_turn_key')}'"
            )
            self._worker = CaptureWorker(cfg, save_dir)

        self.btn_stop.setEnabled(True)
        self._worker.progress.connect(self._on_progress)
        self._worker.note.connect(self.log)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, cur: int, total: int, path: str) -> None:
        self.log(f"  [{cur}/{total}] 저장: {os.path.basename(path)}")

    def _on_finished(self, saved: int) -> None:
        self.hotkey.set_suppressed(False)
        self.btn_stop.setEnabled(False)
        self.log(f"완료 — {saved}장 저장")
        # 완료 후 자동 PDF 생성
        if getattr(self, "_run_auto_pdf", False) and saved > 0:
            save_dir = getattr(self, "_run_save_dir", None) or "."
            name = os.path.basename(os.path.normpath(save_dir)) or "shotkey"
            out = os.path.join(save_dir, f"{name}.pdf")
            ok, msg = pdf.build_pdf(save_dir, out)
            self.log(("자동 PDF 생성: " if ok else "자동 PDF 실패: ") + msg)

    def _on_failed(self, msg: str) -> None:
        self.hotkey.set_suppressed(False)
        self.btn_stop.setEnabled(False)
        self.log(f"실패: {msg}")
        QMessageBox.critical(self, "오류", msg)

    # ----------------------------------------------------------------- misc
    def on_browse_savedir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if d:
            self.txt_savedir.setText(d)

    def on_browse_videodir(self) -> None:
        start = self.txt_videodir.text().strip() or self.txt_savedir.text().strip()
        d = QFileDialog.getExistingDirectory(self, "동영상 저장 폴더 선택", start)
        if d:
            self.txt_videodir.setText(d)

    def on_save_config(self) -> None:
        self.config = self._collect_from_ui()
        cfg_mod.save_config(self._persistable(self.config))
        self.log("설정 저장됨 (config.json)")

    def on_relaunch_admin(self) -> None:
        """ShotKey 를 관리자 권한으로 다시 실행한다(현재 인스턴스 종료)."""
        import sys
        import ctypes
        if windows.is_admin():
            QMessageBox.information(self, "관리자", "이미 관리자 권한으로 실행 중입니다.")
            return
        # 현재 설정 저장 후 elevate
        cfg_mod.save_config(self._persistable(self._collect_from_ui()))
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
        try:
            # ShellExecute 'runas' → UAC 승격
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{script}"',
                os.path.dirname(script), 1
            )
            if int(ret) > 32:
                self.hotkey.stop()
                QApplication.quit()
            else:
                QMessageBox.warning(self, "오류", "관리자 권한 실행이 취소되었습니다.")
        except Exception as exc:
            QMessageBox.critical(self, "오류", f"재실행 실패: {exc}")

    def on_make_pdf(self) -> None:
        cfg = self._collect_from_ui()
        save_dir = cfg_mod.resolve_save_dir(cfg)
        name = os.path.basename(os.path.normpath(save_dir)) or "shotkey"
        out = os.path.join(save_dir, f"{name}.pdf")
        ok, msg = pdf.build_pdf(save_dir, out)
        self.log(("PDF 생성: " if ok else "PDF 실패: ") + msg)
        if ok:
            QMessageBox.information(self, "PDF 생성", msg)
        else:
            QMessageBox.warning(self, "PDF", msg)

    # -------------------------------------------------------- video record
    def _video_base_name(self) -> str:
        """동영상 파일명 기본값에 쓸 폴더명."""
        cfg = self._collect_from_ui()
        video_dir = cfg_mod.resolve_video_dir(cfg)
        return os.path.basename(os.path.normpath(video_dir)) or "shotkey"

    def _refresh_video_name(self) -> None:
        """파일명 입력칸을 '폴더명_숫자.mp4' 다음 번호로 채운다(비어 있을 때만 자동 채움도 겸)."""
        cfg = self._collect_from_ui()
        video_dir = cfg_mod.resolve_video_dir(cfg)
        base = os.path.basename(os.path.normpath(video_dir)) or "shotkey"
        self.txt_videoname.setText(recorder_next_name(video_dir, base))

    def on_toggle_record(self) -> None:
        # 녹화 중이면 정지
        if self._recorder is not None and self._recorder.isRunning():
            self.lbl_record.setText("정지 중… (파일 마무리)")
            self._recorder.stop()
            return

        cfg = self._collect_from_ui()

        # 1) 영상 캡처 영역 검증 — 없거나 이상하면 메시지 띄우고 중단
        region = cfg.get("capture_region")
        bounds = monitors.virtual_bounds()
        ok, msg = validate_region(region, bounds)
        if not ok:
            QMessageBox.warning(self, "영상 캡처 위치 확인", msg)
            self.log("영상 녹화 취소 — 캡처 위치 문제: " + msg.splitlines()[0])
            return

        # 2) 동영상 저장 폴더 검증(생성 시도) — 실패하면 메시지
        try:
            video_dir = cfg_mod.resolve_video_dir(cfg)
        except Exception as exc:
            where = (cfg.get("video_dir") or "").strip() or cfg.get("save_dir", "")
            QMessageBox.warning(
                self, "동영상 저장 폴더 확인",
                f"동영상 저장 폴더를 사용할 수 없습니다:\n{where}\n\n{exc}\n\n"
                "폴더 경로를 다시 지정하세요.")
            self.log(f"영상 녹화 취소 — 저장 폴더 문제: {where} ({exc})")
            return

        # 3) 검증 통과 → 지정한 영역/폴더를 config.json 에 저장(기억)
        cfg_mod.save_config(self._persistable(cfg))
        self.log(
            f"영상 캡처 위치 확인 OK — 영역 left={region.get('left')}, "
            f"top={region.get('top')}, {region.get('width')}x{region.get('height')} / "
            f"폴더 {video_dir}")

        # 파일명: 입력값 사용, 비어 있으면 자동 생성. 확장자 보정.
        fname = self.txt_videoname.text().strip()
        if not fname:
            base = os.path.basename(os.path.normpath(video_dir)) or "shotkey"
            fname = recorder_next_name(video_dir, base)
        if not fname.lower().endswith(".mp4"):
            fname += ".mp4"
        out = os.path.join(video_dir, fname)
        if os.path.exists(out):
            ans = QMessageBox.question(
                self, "덮어쓰기 확인",
                f"'{fname}' 파일이 이미 있습니다. 덮어쓸까요?\n"
                "('아니오'를 누르면 다음 번호로 저장합니다.)")
            if ans != QMessageBox.StandardButton.Yes:
                base = os.path.basename(os.path.normpath(video_dir)) or "shotkey"
                fname = recorder_next_name(video_dir, base)
                out = os.path.join(video_dir, fname)
                self.txt_videoname.setText(fname)

        fps = cfg.get("video_fps", 15)
        audio = bool(cfg.get("record_audio", True))
        max_sec = float(cfg.get("video_max_seconds", 0))

        self._recorder = VideoRecorder(
            region, out, fps, record_audio=audio, max_seconds=max_sec)
        self._recorder.progress.connect(self._on_record_progress)
        self._recorder.note.connect(self.log)
        self._recorder.finished_ok.connect(self._on_record_finished)
        self._recorder.failed.connect(self._on_record_failed)
        self._recorder.start()

        self.btn_record.setText("⏹ 녹화 정지")
        if max_sec > 0:
            m, s = divmod(int(max_sec), 60)
            h, m = divmod(m, 60)
            limit = f", 자동종료 {h:02d}:{m:02d}:{s:02d}"
        else:
            limit = ""
        self.lbl_record.setText("녹화 중…")
        self.log(
            f"동영상 녹화 시작 — {os.path.basename(out)}, "
            f"영역 {region.get('width')}x{region.get('height')}, {fps}fps, "
            f"소리 {'ON' if audio else 'OFF'}{limit}")

    def _on_record_progress(self, elapsed: float, frames: int) -> None:
        self.lbl_record.setText(f"녹화 중… {elapsed:0.1f}초 / {frames}프레임")

    def _on_record_finished(self, path: str, frames: int) -> None:
        self.btn_record.setText("⏺ 영역 동영상 녹화 시작")
        self.lbl_record.setText(f"저장됨: {os.path.basename(path)} ({frames}프레임)")
        self.log(f"동영상 저장 완료 — {path} ({frames}프레임)")
        # 방금 녹화한 영상을 GIF 변환 원본으로 자동 지정(길이도 프로빙)
        self._load_gif_source(path)
        # 다음 녹화를 위해 파일명을 다음 번호로 자동 갱신
        self._refresh_video_name()
        QMessageBox.information(self, "동영상 녹화", f"저장 완료:\n{path}\n{frames}프레임")

    def _on_record_failed(self, msg: str) -> None:
        self.btn_record.setText("⏺ 영역 동영상 녹화 시작")
        self.lbl_record.setText("실패")
        self.log(f"동영상 녹화 실패: {msg}")
        QMessageBox.critical(self, "동영상 녹화 오류", msg)

    # ----------------------------------------------------------- GIF 변환
    def on_browse_gif_src(self) -> None:
        start = self.txt_gif_src.text().strip()
        if start and os.path.isfile(start):
            start = os.path.dirname(start)
        else:
            start = self.txt_videodir.text().strip() or self.txt_savedir.text().strip()
        path, _ = QFileDialog.getOpenFileName(
            self, "GIF 로 변환할 동영상 선택", start,
            "동영상 (*.mp4 *.avi *.mov *.mkv *.webm);;모든 파일 (*.*)")
        if path:
            self._load_gif_source(path)

    def _load_gif_source(self, path: str) -> None:
        """GIF 원본으로 동영상을 세팅하고 길이를 프로빙해 구간 기본값을 잡는다."""
        self.txt_gif_src.setText(path)
        dur = probe_duration(path)
        self._gif_duration = dur
        if dur > 0:
            self.lbl_gif_dur.setText(f"총 길이 {dur:0.1f}초")
            # 구간 상한을 실제 길이에 맞추고, 끝은 '끝까지'(0)로 초기화
            self.spn_gif_start.setMaximum(dur)
            self.spn_gif_end.setMaximum(dur)
            self.spn_gif_start.setValue(0.0)
            self.spn_gif_end.setValue(0.0)
            self.log(f"GIF 원본 선택: {os.path.basename(path)} (길이 {dur:0.1f}초)")
        else:
            self.lbl_gif_dur.setText("총 길이 ? (구간을 직접 입력)")
            self.log(f"GIF 원본 선택: {os.path.basename(path)} (길이 확인 실패)")

    def on_make_gif(self) -> None:
        # 진행 중이면 무시(중복 실행 방지)
        if self._gifmaker is not None and self._gifmaker.isRunning():
            self.log("이미 GIF 변환이 진행 중입니다.")
            return

        src = self.txt_gif_src.text().strip()
        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, "동영상 없음",
                                "GIF 로 변환할 동영상을 먼저 선택하세요.")
            return

        start = self.spn_gif_start.value()
        end = self.spn_gif_end.value()  # 0 = 끝까지
        if end > 0 and end <= start:
            QMessageBox.warning(
                self, "구간 확인",
                f"끝({end:g}초)이 시작({start:g}초)보다 뒤여야 합니다.\n"
                "끝을 0(=끝까지)으로 두거나 값을 다시 지정하세요.")
            return

        out = default_gif_path(src)
        fps = self.spn_gif_fps.value()
        width = self.spn_gif_width.value()

        self._gifmaker = GifMaker(src, out, start, end, fps=fps, width=width)
        self._gifmaker.note.connect(self.log)
        self._gifmaker.finished_ok.connect(self._on_gif_finished)
        self._gifmaker.failed.connect(self._on_gif_failed)
        self._gifmaker.start()

        self.btn_gif_make.setEnabled(False)
        self.lbl_gif_status.setText("변환 중…")

    def _on_gif_finished(self, path: str) -> None:
        self.btn_gif_make.setEnabled(True)
        self.lbl_gif_status.setText(f"저장됨: {os.path.basename(path)}")
        self.log(f"GIF 저장 완료 — {path}")
        QMessageBox.information(self, "GIF 변환", f"저장 완료:\n{path}")

    def _on_gif_failed(self, msg: str) -> None:
        self.btn_gif_make.setEnabled(True)
        self.lbl_gif_status.setText("실패")
        self.log(f"GIF 변환 실패: {msg}")
        QMessageBox.critical(self, "GIF 변환 오류", msg)

    def log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_view.appendPlainText(line)
        try:
            print(line, flush=True)  # 콘솔/로그파일에도 남겨 진단 가능하게
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        # 현재 설정을 그대로 저장 → 재실행해도 유지
        try:
            cfg_mod.save_config(self._persistable(self._collect_from_ui()))
        except Exception:
            pass
        self.hotkey.stop()
        self._identifier.close()
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        if self._recorder and self._recorder.isRunning():
            self._recorder.stop()
            self._recorder.wait(3000)
        if self._gifmaker and self._gifmaker.isRunning():
            self._gifmaker.wait(3000)
        super().closeEvent(event)
