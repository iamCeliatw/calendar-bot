import json
import os
import threading
from contextlib import contextmanager
from typing import Optional

try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

_REMINDERS_FILE = os.environ.get("REMINDERS_FILE", "data/reminders.json")
_thread_lock = threading.Lock()


def _path() -> str:
    return os.environ.get("REMINDERS_FILE", _REMINDERS_FILE)


def _load(f) -> list[dict]:
    f.seek(0)
    content = f.read()
    if not content.strip():
        return []
    return json.loads(content)


def _save(f, records: list[dict]) -> None:
    f.seek(0)
    f.truncate()
    json.dump(records, f, ensure_ascii=False, indent=2)


def _ensure_dir() -> None:
    d = os.path.dirname(_path())
    if d:
        os.makedirs(d, exist_ok=True)


@contextmanager
def _locked_file(mode: str):
    """Open file with thread lock; add flock on Linux."""
    with _thread_lock:
        _ensure_dir()
        with open(_path(), mode, encoding="utf-8") as f:
            if _HAS_FCNTL:
                lock_type = _fcntl.LOCK_EX if "w" in mode or "a" in mode else _fcntl.LOCK_SH
                _fcntl.flock(f, lock_type)
            try:
                yield f
            finally:
                if _HAS_FCNTL:
                    _fcntl.flock(f, _fcntl.LOCK_UN)


def append_reminder(record: dict) -> None:
    with _locked_file("a+") as f:
        records = _load(f)
        records.append(record)
        _save(f, records)


def remove_reminder(task_name: str) -> None:
    with _locked_file("a+") as f:
        records = _load(f)
        records = [r for r in records if r.get("task_name") != task_name]
        _save(f, records)


def update_reminder(old_task_name: str, new_record: dict) -> None:
    with _locked_file("a+") as f:
        records = _load(f)
        records = [r for r in records if r.get("task_name") != old_task_name]
        records.append(new_record)
        _save(f, records)


def get_reminder(task_name: str) -> Optional[dict]:
    try:
        with _locked_file("r") as f:
            records = _load(f)
    except FileNotFoundError:
        return None
    return next((r for r in records if r.get("task_name") == task_name), None)


def list_reminders(user_id: str) -> list[dict]:
    try:
        with _locked_file("r") as f:
            records = _load(f)
    except FileNotFoundError:
        return []
    return [r for r in records if r.get("user_id") == user_id]
