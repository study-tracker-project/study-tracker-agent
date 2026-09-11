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
import tray

POLL_INTERVAL = 5
SEND_INTERVAL = 60
IDLE_THRESHOLD = 30

# 브라우저 사용 시간은 크롬 익스텐션이 도메인 단위로 기록한다. 에이전트가 같은
# 시간을 "chrome.exe"로 또 보내면 세션 시간이 이중 집계되므로 아예 무시한다.
BROWSER_APPS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "whale.exe",
    "brave.exe", "opera.exe", "vivaldi.exe", "iexplore.exe",
}

current_session_id: Optional[int] = None
current_study_type: str = "ONLINE"
is_running: bool = False

app_batch: list = []
last_app: Optional[str] = None
last_window: Optional[str] = None
last_poll_time: Optional[datetime] = None


def get_active_app() -> tuple[str, str]:
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


def send_activity_logs(logs: list) -> bool:
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
    pending = buffer.get_pending_logs()
    for row in pending:
        log_id, log_type, data = row
        import json
        success = send_activity_logs(json.loads(data)["logs"])
        if success:
            buffer.delete_log(log_id)
        else:
            break  # 실패하면 중단 (순서 보장)


def send_batch():
    global app_batch

    if not app_batch or not config.get_session_id():
        return

    logs_to_send = app_batch.copy()
    app_batch = []

    success = send_activity_logs(logs_to_send)
    if not success:
        buffer.save_log("activity", {
            "logs": logs_to_send
        })
        print(f"[버퍼] {len(logs_to_send)}개 로그 로컬 저장")
    else:
        print(f"[전송] {len(logs_to_send)}개 로그 전송 완료")

    if buffer.get_pending_count() > 0:
        flush_buffer()


def poll():
    global last_app, last_window, last_poll_time

    if not config.get_session_id():
        return

    now = datetime.now()
    idle = is_idle()
    app_name, window_title = get_active_app()

    if app_name in BROWSER_APPS:
        return

    if (last_app == app_name and
            last_poll_time and
            (now - last_poll_time).seconds < POLL_INTERVAL * 2):

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


def start_session(study_type: str, target_sec: Optional[int] = None):
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
    session_id = config.get_session_id()
    token = config.get_token()

    if not session_id or not token:
        print("[오류] 진행 중인 세션이 없습니다.")
        return

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
    """Google OAuth 데스크톱 앱 클라이언트 정보를 구한다.
    빌드 시 oauth_secret.py(gitignore, 로컬 전용)가 있으면 그 값을 쓰고,
    없으면 환경변수를 본다. 데스크톱 앱 클라이언트 시크릿은 배포되는
    바이너리에 어차피 들어가므로(Google도 이를 비밀로 취급하지 않음)
    빌드 시 박아두면 최종 사용자는 환경변수를 따로 설정할 필요가 없다."""
    try:
        from oauth_secret import GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
        return GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
    except ImportError:
        pass

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


def _login_with_id_token(id_token: str) -> Optional[str]:
    try:
        response = requests.post(
            f"{config.SERVER_URL}/api/auth/google",
            json={"idToken": id_token},
            timeout=10
        )
    except requests.RequestException as e:
        print(f"[오류] 서버 연결 실패: {e}")
        return None

    if response.status_code != 200:
        print(f"[오류] 로그인 실패: {response.status_code}")
        return None

    try:
        data = response.json()
        access_token = data["accessToken"]
    except (ValueError, KeyError) as e:
        print(f"[오류] 서버 응답 형식이 올바르지 않습니다: {e}")
        return None

    print("[로그인] 성공")
    return access_token


def _register_device(access_token: str, device_name: str) -> Optional[dict]:
    try:
        response = requests.post(
            f"{config.SERVER_URL}/api/auth/device",
            json={"deviceName": device_name, "deviceType": "PC"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
    except requests.RequestException as e:
        print(f"[오류] 서버 연결 실패: {e}")
        return None

    if response.status_code != 200:
        print(f"[오류] 기기 등록 실패: {response.status_code}")
        return None

    try:
        return response.json()
    except ValueError as e:
        print(f"[오류] 서버 응답 형식이 올바르지 않습니다: {e}")
        return None


def login(device_name: str) -> bool:
    client_id, client_secret = _require_oauth_env()

    flow = InstalledAppFlow.from_client_config(
        _build_client_config(client_id, client_secret),
        scopes=["openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile"]
    )

    try:
        credentials = flow.run_local_server(port=0)
    except Exception as e:
        print(f"[오류] Google 로그인 실패: {e}")
        return False

    if not credentials.id_token:
        print("[오류] Google 응답에 ID 토큰이 없습니다. openid 스코프가 요청되었는지 확인하세요.")
        return False

    access_token = _login_with_id_token(credentials.id_token)
    if not access_token:
        return False

    data = _register_device(access_token, device_name)
    if not data:
        return False

    try:
        device_token = data["deviceToken"]
        device_id = data["deviceId"]
    except KeyError as e:
        print(f"[오류] 서버 응답 형식이 올바르지 않습니다: {e}")
        return False

    config.save_token(device_token)
    config.save_device_id(device_id)
    print(f"[기기] 등록 완료 - ID: {device_id}")
    return True


def _register_schedule():
    """폴링/전송/세션동기화 스케줄 등록 (콘솔 모드 run()과 트레이 모드 공용)"""
    schedule.every(POLL_INTERVAL).seconds.do(poll)
    schedule.every(SEND_INTERVAL).seconds.do(send_batch)
    schedule.every(60).seconds.do(sync_active_session)


def run():
    buffer.init_db()
    _register_schedule()

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
        print("  python agent.py login <device_name>")
        print("  python agent.py start <ONLINE|OFFLINE> [target_sec]")
        print("  python agent.py end")
        print("  python agent.py run")
        print("  python agent.py tray   (시스템 트레이 상주 모드, 일반 사용자용)")
        sys.exit(1)

    command = sys.argv[1]

    if command == "login":
        if len(sys.argv) < 3:
            print("[오류] device_name이 필요합니다. 사용법: python agent.py login <device_name>")
            sys.exit(1)
        success = login(sys.argv[2])
        sys.exit(0 if success else 1)

    elif command == "start":
        study_type = sys.argv[2] if len(sys.argv) > 2 else "ONLINE"
        target_sec = int(sys.argv[3]) if len(sys.argv) > 3 else None
        start_session(study_type, target_sec)

    elif command == "end":
        end_session()

    elif command == "run":
        run()

    elif command == "tray":
        tray.run_tray()

    else:
        print(f"[오류] 알 수 없는 명령어: {command}")