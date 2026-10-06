"""使用者互動狀態管理（多步驟精靈、確認等待）。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from google.cloud import firestore


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
    #   "monthly_remind_items" — 每月提醒精靈：輸入項目清單
    #   "monthly_remind_time"  — 每月提醒精靈：選提醒時間
    #   "monthly_remind_confirm" — 每月提醒精靈：確認建立
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
    monthly_items: list = field(default_factory=list)  # [{"name": str, "day": int}, ...]
    expires_at: datetime = field(
        default_factory=lambda: datetime.now() + timedelta(minutes=10)
    )


# 精靈狀態存 Firestore：Cloud Run 有多個執行個體、重新部署或縮到 0 時，記憶體裡的狀態都會不見。
# datetime 存成 ISO 字串，讀回來時區（+08:00 或 naive）才會跟存進去的一樣；
# 另存一個 Timestamp 欄位 ttl 給 Firestore TTL policy 自動清掉過期文件。
_COLLECTION = os.environ.get("SESSIONS_COLLECTION", "sessions")
_DT_FIELDS = ("start", "end", "expires_at")
_client: Optional[firestore.Client] = None


def _col():
    # 延遲建立：沒有 GCP 憑證的本機環境也能正常 import 這個模組
    global _client
    if _client is None:
        _client = firestore.Client(project=os.environ.get("GCP_PROJECT_ID") or None)
    return _client.collection(_COLLECTION)


def _to_doc(pending: PendingEvent) -> dict:
    doc = asdict(pending)
    for k in _DT_FIELDS:
        if doc[k] is not None:
            doc[k] = doc[k].isoformat()
    doc["ttl"] = pending.expires_at.astimezone()
    return doc


def _from_doc(doc: dict) -> PendingEvent:
    doc.pop("ttl", None)
    for k in _DT_FIELDS:
        if doc.get(k) is not None:
            doc[k] = datetime.fromisoformat(doc[k])
    return PendingEvent(**doc)


def get_session(uid: str) -> Optional[PendingEvent]:
    snap = _col().document(uid).get()
    if not snap.exists:
        return None
    p = _from_doc(snap.to_dict())
    # ponytail: TTL policy 最晚可能 24 小時後才刪，過期判斷還是要自己做
    if p.expires_at < datetime.now():
        delete_session(uid)
        return None
    return p


def set_session(uid: str, pending: PendingEvent) -> None:
    _col().document(uid).set(_to_doc(pending))


def delete_session(uid: str) -> None:
    _col().document(uid).delete()


if __name__ == "__main__":
    # 不連 Firestore 的自我檢查：存進去再讀出來要一模一樣
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Taipei")
    p = PendingEvent(
        step="confirm",
        start=datetime(2026, 10, 6, 9, 30, tzinfo=tz),
        end=datetime(2026, 10, 6, 10, 30, tzinfo=tz),
        monthly_items=[{"name": "房租", "day": 5}],
    )
    q = _from_doc(_to_doc(p))
    assert q == p, (q, p)
    assert q.start.utcoffset() == p.start.utcoffset()
    assert _from_doc(_to_doc(PendingEvent(step="wizard_date"))).start is None
    print("ok")
