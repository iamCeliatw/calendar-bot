"""使用者互動狀態管理（多步驟精靈、確認等待）。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class PendingEvent:
    step: str
    # step 可能的值：
    #   "confirm"        — 等待使用者確認建立
    #   "conflict"       — 偵測到衝突，等待使用者決定
    #   "wizard_date"    — 精靈：選日期
    #   "wizard_time"    — 精靈：選時間
    #   "wizard_duration"— 精靈：選時長
    #   "wizard_title"   — 精靈：輸入名稱
    #   "wizard_location"— 精靈：輸入地點
    #   "reminder_date"  — 提醒精靈：選日期
    #   "reminder_time"  — 提醒精靈：選時間
    #   "reminder_text"  — 提醒精靈：輸入提醒內容
    #   "reminder_confirm"— 提醒精靈：確認建立
    #   "cc_remind_banks"— 卡費提醒精靈：輸入銀行清單
    #   "cc_remind_time" — 卡費提醒精靈：選提醒時間
    #   "cc_remind_confirm"— 卡費提醒精靈：確認建立
    summary: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    location: str = ""
    is_all_day: bool = False
    all_day_date: Optional[str] = None   # "YYYY-MM-DD"，全天事件及精靈暫存日期共用
    wizard_time: str = ""                # 精靈暫存時間 "HH:MM"
    reminder_date: Optional[str] = None  # "YYYY-MM-DD"
    reminder_time: str = ""              # "HH:MM"
    reminder_text: str = ""
    cc_banks: list = field(default_factory=list)  # [{"name": str, "day": int}, ...]
    expires_at: datetime = field(
        default_factory=lambda: datetime.now() + timedelta(minutes=10)
    )


class _SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, PendingEvent] = {}
        self._lock = threading.Lock()

    def get(self, uid: str) -> Optional[PendingEvent]:
        with self._lock:
            p = self._data.get(uid)
            if p and p.expires_at < datetime.now():
                del self._data[uid]
                return None
            return p

    def set(self, uid: str, pending: PendingEvent) -> None:
        with self._lock:
            self._data[uid] = pending

    def delete(self, uid: str) -> None:
        with self._lock:
            self._data.pop(uid, None)


_store = _SessionStore()


def get_session(uid: str) -> Optional[PendingEvent]:
    return _store.get(uid)


def set_session(uid: str, pending: PendingEvent) -> None:
    _store.set(uid, pending)


def delete_session(uid: str) -> None:
    _store.delete(uid)
