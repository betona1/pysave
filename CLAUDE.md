# CLAUDE.md

이 파일은 Claude Code가 이 저장소에서 작업할 때 참고하는 가이드입니다.

## 프로젝트 개요

**ShotKey** — 전역 핫키 기반 자동 화면 캡처 도구.

지정한 핫키를 누르면, 미리 저장해둔 화면 좌표에서 **우측 화살표키**를 입력해 다음 페이지로 넘긴 뒤 **자동으로 스크린샷을 저장**한다. 전자책·만화 뷰어·PDF 등 "페이지 넘기며 연속 캡처"가 필요한 작업을 자동화하는 것이 목적이다.

핵심 동작 흐름:
1. 사용자가 캡처 영역(또는 클릭할 좌표)을 마우스로 지정 → 설정에 저장
2. 트리거 핫키를 등록 (예: `F8`, 또는 우측 화살표키 자체)
3. 핫키 입력 시 → 저장 좌표 클릭/포커스 → `right` 키 전송 → 지정 영역 스크린샷 → 파일 저장
4. (선택) 반복 모드: N회 자동 반복하며 page_001.png ~ page_NNN.png 순차 저장

## 기술 스택

- **언어**: Python 3.10+
- **GUI**: PyQt6
- **전역 핫키**: pynput (백그라운드 키 감지)
- **키 입력 / 좌표 측정**: pyautogui
- **스크린샷**: mss (멀티모니터·고속 캡처)
- **설정 저장**: JSON (`config.json`)

```
pip install PyQt6 pynput pyautogui mss
```

## 디렉터리 구조

```
shotkey/
├── main.py              # 진입점, QApplication 실행
├── ui/
│   ├── main_window.py   # 메인 윈도우 (핫키 설정, 좌표 지정 버튼, 시작/정지)
│   └── region_picker.py # 화면 위에 반투명 오버레이로 영역 드래그 선택
├── core/
│   ├── hotkey.py        # pynput 전역 핫키 리스너 (별도 스레드)
│   ├── capturer.py      # mss 기반 영역 스크린샷 + 저장
│   ├── automator.py     # pyautogui로 좌표 클릭 + right 키 입력
│   └── config.py        # config.json 로드/저장
├── config.json          # 사용자 설정 (좌표, 핫키, 저장 경로 등)
└── captures/            # 캡처 결과 저장 폴더
```

## 핵심 구현 포인트

### 1. 좌표 측정 (region_picker.py)
- "영역 지정" 버튼 클릭 시 화면 전체를 덮는 반투명 `QWidget`(`Qt.WindowType.FramelessWindowHint | WindowStaysOnTopHint`) 표시
- 마우스 드래그로 사각형 영역 선택 → `(left, top, width, height)` 반환
- 단일 클릭 좌표만 필요할 경우 `pyautogui.position()`으로 현재 마우스 좌표 캡처

### 2. 전역 핫키 (hotkey.py)
- `pynput.keyboard.GlobalHotKeys` 또는 `Listener`를 **QThread가 아닌 별도 스레드**에서 실행
- 핫키 콜백 → PyQt 메인 스레드로 시그널(`pyqtSignal`) 전달 (스레드 안전성 필수)
- 절대 콜백 안에서 직접 GUI를 건드리지 말 것 → 시그널/슬롯으로 넘긴다

### 3. 자동화 동작 (automator.py)
```python
import pyautogui, time
def do_action(click_xy, delay=0.3):
    if click_xy:
        pyautogui.click(*click_xy)   # 대상 창에 포커스
        time.sleep(delay)
    pyautogui.press('right')         # 다음 페이지
    time.sleep(delay)                # 페이지 전환 렌더링 대기 (조정 가능)
```
- `delay`는 대상 프로그램 페이지 전환 속도에 따라 config에서 조정

### 4. 스크린샷 (capturer.py)
```python
import mss
def capture(region, path):  # region = {"top":, "left":, "width":, "height":}
    with mss.mss() as sct:
        img = sct.grab(region)
        mss.tools.to_png(img.rgb, img.size, output=path)
```
- 파일명은 `page_{n:03d}.png` 형식으로 0패딩 순번

## config.json 형식

```json
{
  "trigger_hotkey": "<f8>",
  "click_position": [960, 540],
  "capture_region": {"top": 100, "left": 200, "width": 800, "height": 1000},
  "save_dir": "./captures",
  "action_delay": 0.3,
  "repeat_count": 1,
  "page_turn_key": "right"
}
```

## 개발 명령어

```bash
python main.py                    # 실행
pyinstaller --noconsole --onefile main.py   # 단일 exe 빌드 (Windows)
```

## 주의사항 / 함정

- **스레드 안전성**: pynput 리스너 콜백에서 PyQt 위젯을 직접 조작하면 크래시. 반드시 시그널로 메인 스레드에 전달.
- **pyautogui FAILSAFE**: 마우스를 화면 좌상단으로 옮기면 동작 중단됨. 의도된 안전장치이므로 끄지 말 것 (`pyautogui.FAILSAFE`).
- **멀티모니터 좌표**: pyautogui와 mss의 좌표 기준이 다를 수 있음. mss는 `sct.monitors`로 모니터별 offset 확인 필요.
- **고DPI 스케일링(Windows)**: 좌표가 어긋나면 `main.py` 상단에서 `QApplication.setAttribute` 또는 DPI awareness 설정 확인.
- **트리거 키 = 우측키일 때 무한루프 주의**: 핫키가 우측키인데 자동화도 우측키를 누르면 자기 자신을 트리거할 수 있음. 자동화로 보낸 키 입력은 무시하도록 플래그 처리.

## 향후 확장 (선택)

- 시스템 트레이 상주 (QSystemTrayIcon)
- 캡처본 자동 PDF 병합 (img2pdf)
- 영역 OCR 연동
- 좌표 프리셋 여러 개 저장/전환