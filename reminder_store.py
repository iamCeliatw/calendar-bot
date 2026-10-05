"""提醒清單存在 Firestore（Cloud Run 容器的檔案系統是暫時的，重新部署就會消失）。

文件 ID 用 Cloud Task 名稱的最後一段（完整名稱含 "/"，不能當文件 ID），
剛好也等於 Cloud Tasks 呼叫時帶的 X-CloudTasks-TaskName header。
"""

import os
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

_COLLECTION = os.environ.get("REMINDERS_COLLECTION", "reminders")
_client: Optional[firestore.Client] = None


def _db() -> firestore.Client:
    # 延遲建立：沒有 GCP 憑證的本機環境也能正常 import 這個模組
    global _client
    if _client is None:
        _client = firestore.Client(project=os.environ.get("GCP_PROJECT_ID") or None)
    return _client


def _col():
    return _db().collection(_COLLECTION)


def _doc_id(task_name: str) -> str:
    return task_name.rsplit("/", 1)[-1]


def append_reminder(record: dict) -> None:
    _col().document(_doc_id(record["task_name"])).set(record)


def remove_reminder(task_name: str) -> None:
    _col().document(_doc_id(task_name)).delete()


def update_reminder(old_task_name: str, new_record: dict) -> None:
    batch = _db().batch()
    batch.delete(_col().document(_doc_id(old_task_name)))
    batch.set(_col().document(_doc_id(new_record["task_name"])), new_record)
    batch.commit()


def get_reminder(task_name: str) -> Optional[dict]:
    snap = _col().document(_doc_id(task_name)).get()
    return snap.to_dict() if snap.exists else None


def list_reminders(user_id: str) -> list[dict]:
    query = _col().where(filter=FieldFilter("user_id", "==", user_id))
    return [snap.to_dict() for snap in query.stream()]
