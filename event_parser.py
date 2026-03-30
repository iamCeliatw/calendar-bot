"""解析使用者傳入的文字，轉成日曆事件的起訖時間與標題。"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 2026-03-30 15:00-16:00 開會
_RE_ISO_RANGE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*[-–~至]\s*(\d{1,2}):(\d{2})\s+(.+)$"
)
# 2026-03-30 15:00 開會
_RE_ISO_SINGLE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s+(.+)$"
)
# 今天 15:00-16:00 開會
_RE_KW_RANGE = re.compile(
    r"^(今天|今日|明天|翌日|後天)\s+(\d{1,2}):(\d{2})\s*[-–~至]\s*(\d{1,2}):(\d{2})\s+(.+)$"
)
# 今天 15:00 開會
_RE_KW_SINGLE = re.compile(
    r"^(今天|今日|明天|翌日|後天)\s+(\d{1,2}):(\d{2})\s+(.+)$"
)


def _base_date_for_keyword(keyword: str, now_local: datetime) -> datetime:
    d = now_local.date()
    if keyword in ("今天", "今日"):
        delta = 0
    elif keyword in ("明天", "翌日"):
        delta = 1
    elif keyword in ("後天",):
        delta = 2
    else:
        delta = 0
    target = d + timedelta(days=delta)
    return datetime(target.year, target.month, target.day, tzinfo=now_local.tzinfo)


def parse_event_line(text: str, timezone_str: str) -> tuple[datetime, datetime, str] | None:
    """
    成功時回傳 (start, end, summary)；無法解析則回傳 None。
    預設行程長度為 1 小時（僅有開始時間時）。
    """
    raw = text.strip()
    if not raw:
        return None
    tz = ZoneInfo(timezone_str)
    now = datetime.now(tz)

    m = _RE_ISO_RANGE.match(raw)
    if m:
        y, mo, d = map(int, m.group(1).split("-"))
        sh, sm = int(m.group(2)), int(m.group(3))
        eh, em = int(m.group(4)), int(m.group(5))
        summary = m.group(6).strip()
        start = datetime(y, mo, d, sh, sm, tzinfo=tz)
        end = datetime(y, mo, d, eh, em, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)
        return start, end, summary

    m = _RE_ISO_SINGLE.match(raw)
    if m:
        y, mo, d = map(int, m.group(1).split("-"))
        sh, sm = int(m.group(2)), int(m.group(3))
        summary = m.group(4).strip()
        start = datetime(y, mo, d, sh, sm, tzinfo=tz)
        end = start + timedelta(hours=1)
        return start, end, summary

    m = _RE_KW_RANGE.match(raw)
    if m:
        base = _base_date_for_keyword(m.group(1), now)
        sh, sm = int(m.group(2)), int(m.group(3))
        eh, em = int(m.group(4)), int(m.group(5))
        summary = m.group(6).strip()
        start = base.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = base.replace(hour=eh, minute=em, second=0, microsecond=0)
        if end <= start:
            end += timedelta(days=1)
        return start, end, summary

    m = _RE_KW_SINGLE.match(raw)
    if m:
        base = _base_date_for_keyword(m.group(1), now)
        sh, sm = int(m.group(2)), int(m.group(3))
        summary = m.group(4).strip()
        start = base.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = start + timedelta(hours=1)
        return start, end, summary

    return None


USAGE_HELP = """請用下面格式建立行程（預設長度 1 小時）：

2026-03-30 15:00 開會
今天 15:00 開會
明天 15:00 開會
後天 15:00 開會

含結束時間：
2026-03-30 15:00-16:00 開會
今天 15:00-16:00 開會

輸入「說明」可再顯示此訊息。"""
