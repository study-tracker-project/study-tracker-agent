"""시스템 트레이 상주 모드.

콘솔 창 없이 백그라운드에서 계속 실행되며, 트레이 아이콘 메뉴에서
"컴퓨터 시작 시 자동 실행"을 켜고 끌 수 있다. 최초 실행 시(사용자가
자동 시작을 명시적으로 끈 적이 없으면) 기본값으로 자동 시작을 켠다 —
이 앱은 켜져 있지 않으면 그 시간의 추적 자체가 유실되는 성격이라
기본 ON이 맞고, 대신 트레이 아이콘으로 항상 실행 상태를 보여주고
언제든 한 번에 끌 수 있게 해서 신뢰를 확보하는 방식.
"""
import atexit
import ctypes
import os
import sys
import threading
import time
import winreg

import schedule
from PIL import Image
import pystray

import buffer
import config

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "StudyTrackerAgent"


def _resource_path(filename: str) -> str:
    """PyInstaller로 빌드됐으면 번들 안 경로, 아니면 스크립트 옆 경로."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)


def _autostart_command() -> str:
    """자동 시작 등록에 쓸 실행 커맨드. 빌드된 exe면 그 경로 그대로,
    개발 중(python agent.py)이면 python 경로 + 스크립트 경로로 구성."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" tray'
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "agent.py"))
    return f'"{sys.executable}" "{script}" tray'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _RUN_NAME)
            return True
    except FileNotFoundError:
        return False


def enable_autostart():
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, _autostart_command())
    config.save_autostart_preference("enabled")


def disable_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, _RUN_NAME)
    except FileNotFoundError:
        pass
    config.save_autostart_preference("disabled")


def _hide_console():
    """트레이 모드는 콘솔 UI가 없으므로, 떠 있으면 숨긴다."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def run_tray():
    import agent  # 순환 import 방지: agent가 tray를 import하므로 여기서는 함수 안에서 지연 import

    _hide_console()

    if config.get_autostart_preference() is None:
        enable_autostart()

    buffer.init_db()
    agent._register_schedule()
    agent.sync_active_session()
    atexit.register(agent.send_batch)

    stop_event = threading.Event()

    def _scheduler_loop():
        while not stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)

    threading.Thread(target=_scheduler_loop, daemon=True).start()

    def _on_toggle_autostart(icon, item):
        if is_autostart_enabled():
            disable_autostart()
        else:
            enable_autostart()

    def _on_quit(icon, item):
        stop_event.set()
        agent.send_batch()
        icon.stop()

    image = Image.open(_resource_path("icon.png"))
    menu = pystray.Menu(
        pystray.MenuItem("Study Tracker 에이전트 실행 중", None, enabled=False),
        pystray.MenuItem(
            "컴퓨터 시작 시 자동 실행",
            _on_toggle_autostart,
            checked=lambda item: is_autostart_enabled(),
        ),
        pystray.MenuItem("종료", _on_quit),
    )
    icon = pystray.Icon("study-tracker-agent", image, "Study Tracker", menu)
    icon.run()
