# config.py
import keyring

SERVICE_NAME = "study-tracker-agent"
SERVER_URL = "https://api.studytracker.cloud"

def save_token(token: str):
    keyring.set_password(SERVICE_NAME, "device_token", token)

def get_token() -> str | None:
    return keyring.get_password(SERVICE_NAME, "device_token")

def save_device_id(device_id: int):
    keyring.set_password(SERVICE_NAME, "device_id", str(device_id))

def get_device_id() -> int | None:
    val = keyring.get_password(SERVICE_NAME, "device_id")
    return int(val) if val else None

def save_session_id(session_id: int):
    keyring.set_password(SERVICE_NAME, "session_id", str(session_id))

def get_session_id() -> int | None:
    val = keyring.get_password(SERVICE_NAME, "session_id")
    return int(val) if val else None

def clear_session_id():
    keyring.delete_password(SERVICE_NAME, "session_id")

def save_autostart_preference(value: str):
    keyring.set_password(SERVICE_NAME, "autostart_preference", value)

def get_autostart_preference() -> str | None:
    return keyring.get_password(SERVICE_NAME, "autostart_preference")