"""解析使用者傳入的文字，轉成日曆事件的起訖時間與標題。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass
class ParsedEvent:
    summary: str
    start: Optional[datetime]       # 全天事件為 None
    end: Optional[datetime]         # 全天事件為 None
    location: str = ""
    is_all_day: bool = False
    all_day_date: Optional[str] = None  # "YYYY-MM-DD"，全天事件使用


def _extract_location(text: str) -> tuple[str, str]:
    """將 '標題 @地點' 拆成 (標題, 地點)；沒有 @ 則地點為空字串。"""
    if " @" in text:
        parts = text.rsplit(" @", 1)
        return parts[0].strip(), parts[1].strip()
    return text.strip(), ""


# ── regex 定義 ──────────────────────────────────────────────────────────────
_KW   = r"(今天|今日|明天|翌日|後天)"
_DATE = r"(\d{4}[/-]\d{2}[/-]\d{2})"
_TIME = r"(\d{1,2}):(\d{2})"
_SEP  = r"\s*[-–~至]\s*"
_REST = r"(.+)"

_RE_ISO_RANGE   = re.compile(rf"^{_DATE}\s+{_TIME}{_SEP}{_TIME}\s+{_REST}$")
_RE_ISO_SINGLE  = re.compile(rf"^{_DATE}\s+{_TIME}\s+{_REST}$")
_RE_KW_RANGE    = re.compile(rf"^{_KW}\s+{_TIME}{_SEP}{_TIME}\s+{_REST}$")
_RE_KW_SINGLE   = re.compile(rf"^{_KW}\s+{_TIME}\s+{_REST}$")
_RE_ISO_ALLDAY  = re.compile(rf"^{_DATE}\s+全天\s+{_REST}$")
_RE_KW_ALLDAY   = re.compile(rf"^{_KW}\s+全天\s+{_REST}$")
# 關鍵字 + 非數字開頭的文字 → 隱含全天（沒有時間）
_RE_KW_IMPLICIT = re.compile(rf"^{_KW}\s+([^\d].*)$")


def _norm_date(s: str) -> str:
    """將 YYYY/MM/DD 正規化為 YYYY-MM-DD，方便後續 split 與 strptime。"""
    return s.replace("/", "-")


def _base_date(keyword: str, now_local: datetime) -> datetime:
    d = now_local.date()
    delta = {"今天": 0, "今日": 0, "明天": 1, "翌日": 1, "後天": 2}.get(keyword, 0)
    target = d + timedelta(days=delta)
    return datetime(target.year, target.month, target.day, tzinfo=now_local.tzinfo)


def parse_event_line(text: str, timezone_str: str) -> Optional[ParsedEvent]:
    """
    解析使用者輸入，回傳 ParsedEvent；無法解析則回傳 None。

    支援格式：
      2026-03-30 15:00-16:00 開會 [@地點]
      2026-03-30 15:00 開會 [@地點]       （預設 1 小時）
      今天 15:00-16:00 開會 [@地點]
      今天 15:00 開會 [@地點]             （預設 1 小時）
      2026-03-30 全天 讀書日 [@地點]
      今天 全天 讀書日 [@地點]
      今天 讀書日 [@地點]                 （隱含全天）
    """
    raw = text.strip()
    if not raw:
        return None
    tz = ZoneInfo(timezone_str)
    now = datetime.now(tz)

    # ── ISO 日期 + 時間範圍 ────────────────────────────────────────────────
    m = _RE_ISO_RANGE.match(raw)
    if m:
        y, mo, d = map(int, _norm_date(m.group(1)).split("-"))
        sh, sm = int(m.group(2)), int(m.group(3))
        eh, em = int(m.group(4)), int(m.group(5))
        summary, location = _extract_location(m.group(6).strip())
        start = datetime(y, mo, d, sh, sm, tzinfo=tz)
        end   = datetime(y, mo, d, eh, em, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)
        return ParsedEvent(summary=summary, start=start, end=end, location=location)

    # ── ISO 日期 + 單一時間 ────────────────────────────────────────────────
    m = _RE_ISO_SINGLE.match(raw)
    if m:
        y, mo, d = map(int, _norm_date(m.group(1)).split("-"))
        sh, sm = int(m.group(2)), int(m.group(3))
        summary, location = _extract_location(m.group(4).strip())
        start = datetime(y, mo, d, sh, sm, tzinfo=tz)
        end   = start + timedelta(hours=1)
        return ParsedEvent(summary=summary, start=start, end=end, location=location)

    # ── 關鍵字 + 時間範圍 ─────────────────────────────────────────────────
    m = _RE_KW_RANGE.match(raw)
    if m:
        base = _base_date(m.group(1), now)
        sh, sm = int(m.group(2)), int(m.group(3))
        eh, em = int(m.group(4)), int(m.group(5))
        summary, location = _extract_location(m.group(6).strip())
        start = base.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end   = base.replace(hour=eh, minute=em, second=0, microsecond=0)
        if end <= start:
            end += timedelta(days=1)
        return ParsedEvent(summary=summary, start=start, end=end, location=location)

    # ── 關鍵字 + 單一時間 ─────────────────────────────────────────────────
    m = _RE_KW_SINGLE.match(raw)
    if m:
        base = _base_date(m.group(1), now)
        sh, sm = int(m.group(2)), int(m.group(3))
        summary, location = _extract_location(m.group(4).strip())
        start = base.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end   = start + timedelta(hours=1)
        return ParsedEvent(summary=summary, start=start, end=end, location=location)

    # ── ISO 日期 + 全天（明確） ───────────────────────────────────────────
    m = _RE_ISO_ALLDAY.match(raw)
    if m:
        date_str = _norm_date(m.group(1))
        summary, location = _extract_location(m.group(2).strip())
        return ParsedEvent(summary=summary, start=None, end=None, location=location,
                           is_all_day=True, all_day_date=date_str)

    # ── 關鍵字 + 全天（明確） ────────────────────────────────────────────
    m = _RE_KW_ALLDAY.match(raw)
    if m:
        base = _base_date(m.group(1), now)
        date_str = base.strftime("%Y-%m-%d")
        summary, location = _extract_location(m.group(2).strip())
        return ParsedEvent(summary=summary, start=None, end=None, location=location,
                           is_all_day=True, all_day_date=date_str)

    # ── 關鍵字 + 文字（隱含全天） ────────────────────────────────────────
    m = _RE_KW_IMPLICIT.match(raw)
    if m:
        base = _base_date(m.group(1), now)
        date_str = base.strftime("%Y-%m-%d")
        summary, location = _extract_location(m.group(2).strip())
        return ParsedEvent(summary=summary, start=None, end=None, location=location,
                           is_all_day=True, all_day_date=date_str)

    return None


USAGE_HELP = """📋 行程輸入格式

⏰ 有時間（預設 1 小時）：
  今天 15:00 開會
  明天 15:00-16:00 開會
  2026/03/30 15:00 開會

📍 加地點（結尾加 @地點）：
  今天 15:00 開會 @信義辦公室

🗓 全天事件：
  今天 全天 讀書日
  今天 讀書日

🧙 精靈模式（逐步引導）：
  輸入「新增行程」→ 點選日期、時間、時長

🔍 查看行程：
  查看今天 ／ 查看明天 ／ 查看後天
  查看本週 ／ 查看下週
  查看 2026/03/30

⏰ 提醒精靈：
  輸入「新增提醒」→ 點選日期、時間，再輸入提醒內容

輸入「說明」可再顯示此訊息。"""
