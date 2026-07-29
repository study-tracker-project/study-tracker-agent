# buffer.py
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "buffer.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_type TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_log(log_type: str, data: dict):
    """서버 전송 실패 시 로컬에 저장"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO pending_logs (log_type, data, created_at) VALUES (?, ?, ?)",
        (log_type, json.dumps(data), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_pending_logs() -> list:
    """미전송 로그 목록 조회"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, log_type, data FROM pending_logs ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return rows

def delete_log(log_id: int):
    """전송 성공한 로그 삭제"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM pending_logs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()

def get_pending_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM pending_logs").fetchone()[0]
    conn.close()
    return count