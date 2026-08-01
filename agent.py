# agent.py
import os
import sys
import time
import ctypes
import threading
from datetime import datetime, timezone
from typing import Optional

import win32gui
import win32process
import win32api
import win32con
import psutil
import requests
import schedule
from google_auth_oauthlib.flow import InstalledAppFlow

import config
import buffer
import classifier

# ── 상수 ──────────────────────────────────────────
POLL_INTERVAL = 5        # 앱 감지 주기 (초)
SEND_INTERVAL = 60       # 서버 전송 주기 (초)
IDLE_THRESHOLD = 30      # 유휴 판단 기준 (초)

# ── 상태 변수 ─────────────────────────────────────
current_session_id: Optional[int] = None
current_study_type: str = "ONLINE"
is_running: bool = False

# 현재 앱 포커스 누적 (1분 배치용)
app_batch: list = []
last_app: Optional[str] = None
last_window: Optional[str] = None
last_poll_time: Optional[datetime] = None


# ── OS API ────────────────────────────────────────

def get_active_app() -> tuple[str, str]:
    """현재 포커스된 앱 이름과 창 제목 반환"""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        app_name = process.name()
        window_title = win32gui.GetWindowText(hwnd)
        return app_name, window_title
    except Exception:
        return "unknown.exe", ""


def get_idle_sec() -> int:
    """마지막 입력 후 경과 시간 (초) 반환"""
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        elapsed = win32api.GetTickCount() - lii.dwTime
        return elapsed // 1000
    except Exception:
        return 0


def is_idle() -> bool:
    return get_idle_sec() >= IDLE_THRESHOLD


# ── 서버 통신 ─────────────────────────────────────

def send_activity_logs(logs: list) -> bool:
    """앱 활동 로그 서버 전송"""
    token = config.get_token()
    device_id = config.get_device_id()
    session_id = config.get_session_id()

    if not token or not device_id or not session_id:
        return False

    payload = {
        "sessionId": session_id,
        "deviceId": device_id,
        "logs": logs
    }

    try:
        response = requests.post(
            f"{config.SERVER_URL}/api/activity-logs",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def flush_buffer():
    """로컬 버퍼에 쌓인 미전송 로그 재전송"""
    pending = buffer.get_pending_logs()
    for row in pending:
        log_id, log_type, data = row
        import json
        success = send_activity_logs(json.loads(data)["logs"])
        if success:
            buffer.delete_log(log_id)
        else:
            break  # 실패하면 중단 (순서 보장)


# ── 배치 전송 ─────────────────────────────────────

def send_batch():
    """1분마다 누적된 로그 배치 전송"""
    global app_batch

    if not app_batch or not config.get_session_id():
        return

    logs_to_send = app_batch.copy()
    app_batch = []

    success = send_activity_logs(logs_to_send)
    if not success:
        # 전송 실패 시 로컬 버퍼에 저장
        buffer.save_log("activity", {
            "logs": logs_to_send
        })
        print(f"[버퍼] {len(logs_to_send)}개 로그 로컬 저장")
    else:
        print(f"[전송] {len(logs_to_send)}개 로그 전송 완료")

    # 버퍼 재전송 시도
    if buffer.get_pending_count() > 0:
        flush_buffer()


# ── 폴링 루프 ─────────────────────────────────────

def poll():
    """5초마다 현재 앱 감지 및 배치 누적"""
    global last_app, last_window, last_poll_time

    if not config.get_session_id():
        return

    now = datetime.now()
    idle = is_idle()
    app_name, window_title = get_active_app()

    # 이전 폴링과 같은 앱이면 duration 누적
    if (last_app == app_name and
            last_poll_time and
            (now - last_poll_time).seconds < POLL_INTERVAL * 2):

        # 마지막 항목에 duration 추가
        if app_batch and app_batch[-1]["appName"] == app_name:
            app_batch[-1]["durationSec"] += POLL_INTERVAL
        else:
            app_batch.append({
                "appName": app_name,
                "windowTitle": window_title,
                "startedAt": now.strftime("%Y-%m-%dT%H:%M:%S"),
                "durationSec": POLL_INTERVAL,
                "isIdle": idle
            })
    else:
        # 새 앱으로 전환됨
        app_batch.append({
            "appName": app_name,
            "windowTitle": window_title,
            "startedAt": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "durationSec": POLL_INTERVAL,
            "isIdle": idle
        })

    last_app = app_name
    last_window = window_title
    last_poll_time = now

    print(f"[감지] {app_name} | 유휴: {idle} | 배치: {len(app_batch)}개")


# ── 세션 관리 ─────────────────────────────────────

def start_session(study_type: str, target_sec: Optional[int] = None):
    """세션 시작"""
    global current_study_type

    token = config.get_token()
    if not token:
        print("[오류] 먼저 로그인이 필요합니다.")
        return

    payload = {"studyType": study_type}
    if target_sec:
        payload["targetSec"] = target_sec

    try:
        response = requests.post(
            f"{config.SERVER_URL}/api/sessions",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            config.save_session_id(data["sessionId"])
            current_study_type = study_type
            print(f"[세션] 시작 - ID: {data['sessionId']} | 유형: {study_type}")
        else:
            print(f"[오류] 세션 시작 실패: {response.status_code}")
    except requests.RequestException as e:
        print(f"[오류] 서버 연결 실패: {e}")

def sync_active_session():
    """서버에 현재 활성 세션을 물어보고 로컬 session_id를 동기화"""
    token = config.get_token()
    if not token:
        return

    try:
        response = requests.get(
            f"{config.SERVER_URL}/api/sessions/active",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            current = config.get_session_id()
            if current != data["sessionId"]:
                config.save_session_id(data["sessionId"])
                print(f"[세션 동기화] {current} -> {data['sessionId']}")
        elif response.status_code == 400 or response.status_code == 404:
            # 활성 세션 없음
            if config.get_session_id():
                config.clear_session_id()
                print("[세션 동기화] 활성 세션 없음 -> 로컬 초기화")
    except requests.RequestException:
        pass  # 네트워크 오류는 무시하고 다음 주기에 재시도

def end_session():
    """세션 종료"""
    session_id = config.get_session_id()
    token = config.get_token()

    if not session_id or not token:
        print("[오류] 진행 중인 세션이 없습니다.")
        return

    # 남은 배치 전송
    send_batch()

    try:
        response = requests.patch(
            f"{config.SERVER_URL}/api/sessions/{session_id}/end",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            config.clear_session_id()
            print(f"[세션] 종료 완료")
            print(f"  순공 시간: {data['studySec'] // 60}분")
            print(f"  딴짓 시간: {data['distractSec'] // 60}분")
        else:
            print(f"[오류] 세션 종료 실패: {response.status_code}")
    except requests.RequestException as e:
        print(f"[오류] 서버 연결 실패: {e}")


def _require_oauth_env() -> tuple[str, str]:
    """Google OAuth 데스크톱 앱 클라이언트 정보를 환경변수에서 읽는다. 없으면 안내 후 종료."""
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        print("[오류] GOOGLE_OAUTH_CLIENT_ID 환경변수가 설정되어 있지 않습니다.")
        sys.exit(1)

    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_secret:
        print("[오류] GOOGLE_OAUTH_CLIENT_SECRET 환경변수가 설정되어 있지 않습니다.")
        sys.exit(1)

    return client_id, client_secret


def _build_client_config(client_id: str, client_secret: str) -> dict:
    """InstalledAppFlow.from_client_config()에 넘길 데스크톱 앱 클라이언트 설정."""
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"]
        }
    }


# ── 로그인 ────────────────────────────────────────

def login(email: str, password: str, device_name: str):
    """로그인 + device_token 발급"""
    try:
        # 로그인
        response = requests.post(
            f"{config.SERVER_URL}/api/auth/login",
            json={"email": email, "password": password},
            timeout=10
        )
        if response.status_code != 200:
            print(f"[오류] 로그인 실패: {response.status_code}")
            return

        access_token = response.json()["accessToken"]
        print("[로그인] 성공")

        # device_token 발급
        response = requests.post(
            f"{config.SERVER_URL}/api/auth/device",
            json={"deviceName": device_name, "deviceType": "PC"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            config.save_token(data["deviceToken"])
            config.save_device_id(data["deviceId"])
            print(f"[기기] 등록 완료 - ID: {data['deviceId']}")
        else:
            print(f"[오류] 기기 등록 실패: {response.status_code}")

    except requests.RequestException as e:
        print(f"[오류] 서버 연결 실패: {e}")


# ── 메인 ──────────────────────────────────────────

def run():
    """에이전트 메인 루프"""
    buffer.init_db()

    # 스케줄 등록
    schedule.every(POLL_INTERVAL).seconds.do(poll)
    schedule.every(SEND_INTERVAL).seconds.do(send_batch)
    schedule.every(60).seconds.do(sync_active_session) # 60초 마다 현재 작동중인 sessionId 추적

    sync_active_session()  # ← 시작 시 즉시 1회 동기화

    print("[에이전트] 시작됨")
    print(f"  폴링 주기: {POLL_INTERVAL}초")
    print(f"  전송 주기: {SEND_INTERVAL}초")

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python agent.py login <email> <password> <device_name>")
        print("  python agent.py start <ONLINE|OFFLINE> [target_sec]")
        print("  python agent.py end")
        print("  python agent.py run")
        sys.exit(1)

    command = sys.argv[1]

    if command == "login":
        login(sys.argv[2], sys.argv[3], sys.argv[4])

    elif command == "start":
        study_type = sys.argv[2] if len(sys.argv) > 2 else "ONLINE"
        target_sec = int(sys.argv[3]) if len(sys.argv) > 3 else None
        start_session(study_type, target_sec)

    elif command == "end":
        end_session()

    elif command == "run":
        run()

    else:
        print(f"[오류] 알 수 없는 명령어: {command}")