"""
LINE Webhook：接收使用者文字訊息並寫入 Google Calendar。

部署需公開 HTTPS URL（本機可用 ngrok 等轉發）。
環境變數：LINE_CHANNEL_ACCESS_TOKEN、LINE_CHANNEL_SECRET、LINE_USER_IDS、TIMEZONE
"""

import calendar as _calendar
import functools
import json
import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_from_directory
from google.cloud import tasks_v2
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google.protobuf.timestamp_pb2 import Timestamp
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    QuickReply,
    QuickReplyItem,
    PostbackAction,
    MessageAction,
    DatetimePickerAction,
    URIAction,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent

import calendar_service
import event_parser
import line_service
import reminder_store
from main import notify as daily_notify
from session_store import PendingEvent, get_session, set_session, delete_session

load_dotenv()

app = Flask(__name__)

CHANNEL_SECRET       = os.environ.get("LINE_CHANNEL_SECRET", "").strip()
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
TIMEZONE             = os.getenv("TIMEZONE", "Asia/Taipei")
ENABLE_REMINDER      = os.getenv("ENABLE_REMINDER", "true").lower() == "true"
GCP_PROJECT_ID       = os.getenv("GCP_PROJECT_ID", "").strip()
GCP_LOCATION         = os.getenv("GCP_LOCATION", "asia-east1").strip()
REMINDER_TASK_QUEUE  = os.getenv("REMINDER_TASK_QUEUE", "calendar-reminder-queue").strip()
TASK_HANDLER_URL     = os.getenv("TASK_HANDLER_URL", "").strip()
REMINDER_TASK_TOKEN  = os.getenv("REMINDER_TASK_TOKEN", "").strip()
SCHEDULER_SA_EMAIL   = os.getenv("SCHEDULER_SA_EMAIL", "").strip()
LIFF_CALENDAR_ID     = os.getenv("LIFF_CALENDAR_ID", "").strip()
LIFF_FORM_ID         = os.getenv("LIFF_FORM_ID", "").strip()
LIFF_REMINDER_ID     = os.getenv("LIFF_REMINDER_ID", "").strip()

for _liff_var, _liff_name in [
    (LIFF_CALENDAR_ID, "LIFF_CALENDAR_ID"),
    (LIFF_FORM_ID,     "LIFF_FORM_ID"),
    (LIFF_REMINDER_ID, "LIFF_REMINDER_ID"),
]:
    if not _liff_var:
        print(f"[WARNING] {_liff_name} 未設定，LIFF 相關功能將降級")

_allowed_ids: frozenset[str] | None = None
_user_names: dict[str, str] = {}


def _get_allowed_ids() -> frozenset[str]:
    global _allowed_ids
    if _allowed_ids is None:
        raw   = os.environ.get("LINE_USER_IDS", "")
        parts = raw.replace("\r", "\n").replace(",", "\n").split("\n")
        _allowed_ids = frozenset(p.strip() for p in parts if p.strip())
    return _allowed_ids


def _get_user_names() -> dict[str, str]:
    global _user_names
    if not _user_names:
        raw = os.environ.get("LINE_USER_NAMES", "")
        for pair in raw.replace("\n", ",").split(","):
            if ":" in pair:
                uid, name = pair.strip().split(":", 1)
                _user_names[uid.strip()] = name.strip()
    return _user_names


def _prefixed(summary: str, uid: str) -> str:
    """加上「【名字】」前綴；已經有同一個前綴就不再加（編輯時表單會帶回原標題）。"""
    name = _get_user_names().get(uid, "")
    if not name:
        return summary
    tag = f"【{name}】"
    return summary if summary.startswith(tag) else f"{tag}{summary}"


# ── LIFF API 驗證 ─────────────────────────────────────────────────────────────

def _verify_liff_token(auth_header: str) -> str:
    """驗證 LIFF Access Token，回傳 userId 或 raise abort(401/403)。"""
    if not auth_header or not auth_header.startswith("Bearer "):
        abort(401, description="Unauthorized")
    token = auth_header[7:]
    try:
        resp = requests.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except requests.RequestException:
        abort(401, description="Unauthorized")
    if resp.status_code != 200:
        abort(401, description="Unauthorized")
    user_id = resp.json().get("userId", "")
    if user_id not in _get_allowed_ids():
        abort(403, description="Forbidden")
    return user_id


def require_liff_auth(f):
    """Flask decorator：驗證 LIFF Access Token 並將 user_id 注入 kwargs。"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        uid = _verify_liff_token(request.headers.get("Authorization", ""))
        kwargs["liff_user_id"] = uid
        return f(*args, **kwargs)
    return decorated


handler = WebhookHandler(CHANNEL_SECRET)


# ── 回覆工具 ──────────────────────────────────────────────────────────────────

def _reply(reply_token: str, messages: list) -> None:
    config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    with ApiClient(config) as client:
        MessagingApi(client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=messages)
        )


def _reply_text(reply_token: str, text: str) -> None:
    _reply(reply_token, [TextMessage(text=text)])


def _reply_flex(reply_token: str, flex: FlexMessage) -> None:
    _reply(reply_token, [flex])


def _reply_text_with_qr(reply_token: str, text: str, quick_reply: QuickReply) -> None:
    _reply(reply_token, [TextMessage(text=text, quick_reply=quick_reply)])


def _push(user_id: str, messages: list) -> None:
    config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    with ApiClient(config) as client:
        MessagingApi(client).push_message(
            PushMessageRequest(to=user_id, messages=messages)
        )


def _push_flex(user_id: str, flex: FlexMessage) -> None:
    _push(user_id, [flex])


# ── 精靈用 Quick Reply 建構 ────────────────────────────────────────────────────

def _date_quick_reply() -> QuickReply:
    tz  = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    # 指定日期（系統日曆）排第一
    items = [
        QuickReplyItem(
            action=DatetimePickerAction(
                label="指定日期 📅",
                data="wizard:pick_date",
                mode="date",
                initial=now.strftime("%Y-%m-%d"),
                min="2020-01-01",
                max="2035-12-31",
            )
        )
    ]
    labels = [("今天", 0), ("明天", 1), ("後天", 2)]
    for label, d in labels:
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=f"{label}（{(now + timedelta(days=d)).strftime('%m/%d')}）",
                    data=f"wizard:date:{(now + timedelta(days=d)).strftime('%Y-%m-%d')}",
                )
            )
        )
    return QuickReply(items=items)


def _reminder_date_quick_reply() -> QuickReply:
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    items = [
        QuickReplyItem(
            action=DatetimePickerAction(
                label="指定日期 📅",
                data="reminder:pick_date",
                mode="date",
                initial=now.strftime("%Y-%m-%d"),
                min="2020-01-01",
                max="2035-12-31",
            )
        )
    ]
    labels = [("今天", 0), ("明天", 1), ("後天", 2)]
    for label, d in labels:
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=f"{label}（{(now + timedelta(days=d)).strftime('%m/%d')}）",
                    data=f"reminder:date:{(now + timedelta(days=d)).strftime('%Y-%m-%d')}",
                )
            )
        )
    return QuickReply(items=items)


def _time_quick_reply() -> QuickReply:
    slots = ["全天", "08:00", "09:00", "10:00", "11:00", "12:00",
             "13:00", "14:00", "15:00", "16:00", "18:00", "20:00"]
    items = [
        QuickReplyItem(
            action=PostbackAction(
                label=t,
                data="wizard:time:allday" if t == "全天" else f"wizard:time:{t}",
            )
        )
        for t in slots
    ]
    return QuickReply(items=items)


def _monthly_time_quick_reply() -> QuickReply:
    slots = ["08:00", "09:00", "10:00", "11:00", "12:00",
             "13:00", "15:00", "18:00", "20:00"]
    items = [
        QuickReplyItem(
            action=PostbackAction(label=t, data=f"monthly_remind:time:{t}")
        )
        for t in slots
    ]
    return QuickReply(items=items)


def _reminder_time_quick_reply() -> QuickReply:
    slots = ["08:00", "09:00", "10:00", "11:00", "12:00",
             "13:00", "14:00", "15:00", "16:00", "18:00", "20:00"]
    items = [
        QuickReplyItem(
            action=PostbackAction(label=t, data=f"reminder:time:{t}")
        )
        for t in slots
    ]
    return QuickReply(items=items)


def _duration_quick_reply() -> QuickReply:
    durations = [("30分鐘", 30), ("1小時", 60), ("1.5小時", 90), ("2小時", 120), ("3小時", 180)]
    items = [
        QuickReplyItem(
            action=PostbackAction(label=label, data=f"wizard:duration:{mins}")
        )
        for label, mins in durations
    ]
    return QuickReply(items=items)


def _skip_location_quick_reply() -> QuickReply:
    return QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="跳過", data="wizard:skip_location"))
    ])


# ── 查看指令解析 ──────────────────────────────────────────────────────────────

_RE_VIEW_KW   = re.compile(r"^查看\s*(今天|今日|明天|翌日|後天)$")
_RE_VIEW_ISO  = re.compile(r"^查看\s*(\d{4}[/-]\d{2}[/-]\d{2})$")
_RE_VIEW_WEEK = re.compile(r"^查看\s*(本週|本周|下週|下周)$")
_KW_DELTA     = {"今天": 0, "今日": 0, "明天": 1, "翌日": 1, "後天": 2}


def _try_parse_week_view(text: str) -> tuple[datetime, datetime, str] | None:
    """解析「查看本週／下週」，回傳 (週一 00:00, 下週一 00:00, 標籤) 或 None。"""
    m = _RE_VIEW_WEEK.match(text)
    if not m:
        return None
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if m.group(1) in ("本週", "本周"):
        start = this_monday
        label = "本週"
    else:
        start = this_monday + timedelta(days=7)
        label = "下週"
    end = start + timedelta(days=7)
    return start, end, label


def _try_parse_view(text: str) -> datetime | None:
    tz  = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    m = _RE_VIEW_KW.match(text)
    if m:
        delta = _KW_DELTA.get(m.group(1), 0)
        return now + timedelta(days=delta)

    m = _RE_VIEW_ISO.match(text)
    if m:
        try:
            date_str = m.group(1).replace("/", "-")
            return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
        except ValueError:
            return None

    return None


def _build_remind_at(pending: PendingEvent, tz: ZoneInfo) -> datetime | None:
    if not pending.reminder_date or not pending.reminder_time:
        return None
    y, mo, d = map(int, pending.reminder_date.split("-"))
    h, mi = map(int, pending.reminder_time.split(":"))
    return datetime(y, mo, d, h, mi, tzinfo=tz)


def _extract_postback_date(event: PostbackEvent) -> str:
    params = event.postback.params
    date_str = ""
    try:
        if params is not None:
            date_str = getattr(params, "date", None) or ""
            if not date_str and isinstance(params, dict):
                date_str = params.get("date", "") or ""
    except Exception:
        pass
    return date_str


def _parse_monthly_entries(text: str) -> list[dict] | None:
    """解析每月提醒輸入，格式：每行「項目名稱 日期」。"""
    lines = [l.strip() for l in re.split(r"[\n,，]", text) if l.strip()]
    if not lines:
        return None
    entries = []
    for line in lines:
        m = re.match(r"^(.+?)\s+(\d{1,2})號?$", line)
        if not m:
            return None
        day = int(m.group(2))
        if not 1 <= day <= 31:
            return None
        entries.append({"name": m.group(1).strip(), "day": day})
    return entries or None


def _next_monthly_occurrence(day_of_month: int, remind_time: str, tz: ZoneInfo) -> datetime:
    """計算下一個每月提醒時間（若本月尚未到則用本月，否則用下月）。"""
    now = datetime.now(tz)
    h, mi = map(int, remind_time.split(":"))
    last_day = _calendar.monthrange(now.year, now.month)[1]
    actual_day = min(day_of_month, last_day)
    candidate = datetime(now.year, now.month, actual_day, h, mi, tzinfo=tz)
    if candidate > now:
        return candidate
    next_month = now.month + 1
    next_year = now.year
    if next_month > 12:
        next_month, next_year = 1, now.year + 1
    last_day = _calendar.monthrange(next_year, next_month)[1]
    actual_day = min(day_of_month, last_day)
    return datetime(next_year, next_month, actual_day, h, mi, tzinfo=tz)


def _next_month_from(from_dt: datetime, day_of_month: int, remind_time: str, tz: ZoneInfo) -> datetime:
    """從給定時間往後推一個月，取指定日期。"""
    next_month = from_dt.month + 1
    next_year = from_dt.year
    if next_month > 12:
        next_month, next_year = 1, from_dt.year + 1
    h, mi = map(int, remind_time.split(":"))
    last_day = _calendar.monthrange(next_year, next_month)[1]
    actual_day = min(day_of_month, last_day)
    return datetime(next_year, next_month, actual_day, h, mi, tzinfo=tz)


def _create_reminder_task(
    user_id: str,
    remind_at: datetime,
    reminder_text: str,
    *,
    recurring: bool = False,
    day_of_month: int | None = None,
    remind_time: str | None = None,
) -> str:
    if not ENABLE_REMINDER:
        raise RuntimeError("提醒功能未啟用（ENABLE_REMINDER=false）")
    if not GCP_PROJECT_ID:
        raise RuntimeError("缺少 GCP_PROJECT_ID")
    if not GCP_LOCATION:
        raise RuntimeError("缺少 GCP_LOCATION")
    if not REMINDER_TASK_QUEUE:
        raise RuntimeError("缺少 REMINDER_TASK_QUEUE")
    if not TASK_HANDLER_URL:
        raise RuntimeError("缺少 TASK_HANDLER_URL")
    if not REMINDER_TASK_TOKEN:
        raise RuntimeError("缺少 REMINDER_TASK_TOKEN")

    payload = {
        "user_id": user_id,
        "reminder_text": reminder_text,
        "remind_at": remind_at.isoformat(),
    }
    if recurring and day_of_month and remind_time:
        payload["recurring"] = True
        payload["day_of_month"] = day_of_month
        payload["remind_time"] = remind_time
    schedule_time = Timestamp()
    schedule_time.FromDatetime(remind_at.astimezone(timezone.utc))

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": TASK_HANDLER_URL,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {REMINDER_TASK_TOKEN}",
            },
            "body": json.dumps(payload).encode("utf-8"),
        },
        "schedule_time": schedule_time,
    }

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(GCP_PROJECT_ID, GCP_LOCATION, REMINDER_TASK_QUEUE)
    created = client.create_task(request={"parent": parent, "task": task})
    return created.name


def _delete_reminder_task(task_name: str) -> None:
    if not (GCP_PROJECT_ID and REMINDER_TASK_QUEUE):
        return
    try:
        tasks_v2.CloudTasksClient().delete_task(request={"name": task_name})
    except Exception as e:
        print(f"[WARN] 刪除 Cloud Task 失敗（可能會多推播一次）：{task_name} {e}")


def _create_reminder(
    user_id: str,
    remind_at: datetime,
    reminder_text: str,
    *,
    recurring: bool = False,
    day_of_month: int | None = None,
    remind_time: str | None = None,
) -> dict:
    """建立 Cloud Task 並寫入提醒清單；清單寫入失敗就刪掉剛建的 task，避免看不到的幽靈提醒。"""
    task_name = _create_reminder_task(
        user_id, remind_at, reminder_text,
        recurring=recurring, day_of_month=day_of_month, remind_time=remind_time,
    )
    record = {
        "task_name":     task_name,
        "user_id":       user_id,
        "remind_at":     remind_at.isoformat(),
        "reminder_text": reminder_text,
        "recurring":     recurring,
    }
    if recurring:
        record["day_of_month"] = day_of_month
        record["remind_time"] = remind_time
    try:
        reminder_store.append_reminder(record)
    except Exception:
        _delete_reminder_task(task_name)
        raise
    return record


# ── 建立行程（抽出共用邏輯） ──────────────────────────────────────────────────

def _do_create_event(pending: PendingEvent, reply_token: str) -> None:
    """實際呼叫 Google Calendar API 建立行程，並回覆成功卡片。"""
    try:
        if pending.is_all_day:
            created = calendar_service.create_all_day_event(
                pending.summary or "",
                pending.all_day_date or "",
                TIMEZONE,
                pending.location,
            )
        else:
            created = calendar_service.create_timed_event(
                pending.summary or "",
                pending.start,
                pending.end,
                TIMEZONE,
                pending.location,
            )
        link     = created.get("htmlLink", "")
        event_id = created.get("id", "")
        _reply_flex(reply_token, line_service.build_success_flex(pending, link, event_id))
    except Exception as e:
        _reply_text(reply_token, f"寫入日曆失敗：{e}")


# ── 精靈文字步驟處理 ──────────────────────────────────────────────────────────

def _handle_wizard_text(uid: str, text: str, reply_token: str, pending: PendingEvent) -> None:
    """處理精靈模式下使用者輸入的自由文字。"""
    step = pending.step
    tz   = ZoneInfo(TIMEZONE)

    if step == "wizard_date":
        m = re.match(r"^(\d{4})[/-](\d{2})[/-](\d{2})$", text.strip())
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"  # 內部統一用 -
            display_date = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
            pending.all_day_date = date_str
            pending.step = "wizard_time"
            set_session(uid, pending)
            _reply_text_with_qr(
                reply_token,
                f"請選擇時間（{display_date}）：",
                _time_quick_reply(),
            )
        else:
            _reply_text(reply_token, "請輸入日期格式 YYYY/MM/DD（例：2026/04/15）或點選上方按鈕。")

    elif step == "wizard_time":
        m = re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            pending.wizard_time = f"{h:02d}:{mi:02d}"
            pending.step = "wizard_duration"
            set_session(uid, pending)
            _reply_text_with_qr(reply_token, "請選擇時長：", _duration_quick_reply())
        else:
            _reply_text(reply_token, "請輸入時間格式 HH:MM（例：15:00）或點選上方按鈕。")

    elif step == "wizard_title":
        pending.summary = _prefixed(text.strip(), uid)
        pending.step = "wizard_location"
        set_session(uid, pending)
        _reply_text_with_qr(
            reply_token,
            "請輸入地點（選填）：",
            _skip_location_quick_reply(),
        )

    elif step == "wizard_location":
        pending.location = text.strip()
        pending.step = "confirm"
        set_session(uid, pending)
        _reply_flex(reply_token, line_service.build_confirmation_flex(pending))

    elif step == "reminder_date":
        m = re.match(r"^(\d{4})[/-](\d{2})[/-](\d{2})$", text.strip())
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            display_date = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
            pending.reminder_date = date_str
            pending.step = "reminder_time"
            set_session(uid, pending)
            _reply_text_with_qr(
                reply_token,
                f"請選擇提醒時間（{display_date}）：",
                _reminder_time_quick_reply(),
            )
        else:
            _reply_text(reply_token, "請輸入日期格式 YYYY/MM/DD（例：2026/04/15）或點選上方按鈕。")

    elif step == "reminder_time":
        m = re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if h < 0 or h > 23 or mi < 0 or mi > 59:
                _reply_text(reply_token, "時間無效，請輸入 HH:MM（例：15:00）。")
                return
            pending.reminder_time = f"{h:02d}:{mi:02d}"
            pending.step = "reminder_text"
            set_session(uid, pending)
            _reply_text(reply_token, "請輸入提醒內容：")
        else:
            _reply_text(reply_token, "請輸入時間格式 HH:MM（例：15:00）或點選上方按鈕。")

    elif step == "reminder_text":
        reminder_text = text.strip()
        if not reminder_text:
            _reply_text(reply_token, "提醒內容不可為空，請重新輸入。")
            return
        pending.reminder_text = reminder_text
        remind_at = _build_remind_at(pending, tz)
        if not remind_at:
            _reply_text(reply_token, "⚠️ 時間解析失敗，請重新輸入「新增提醒」。")
            delete_session(uid)
            return
        if remind_at <= datetime.now(tz):
            _reply_text(reply_token, "⚠️ 不能設定過去時間，請重新輸入「新增提醒」。")
            delete_session(uid)
            return
        pending.step = "reminder_confirm"
        set_session(uid, pending)
        _reply_flex(
            reply_token,
            line_service.build_reminder_confirmation_flex(remind_at, reminder_text),
        )

    elif step in ("monthly_remind_items", "cc_remind_banks"):
        items = _parse_monthly_entries(text)
        if not items:
            _reply_text(
                reply_token,
                "格式不正確，請重新輸入。\n\n"
                "格式：提醒項目名稱 日期（每行一筆）\n\n"
                "範例：\n房租 5\n信用卡帳單 15\n保險費 20",
            )
            return
        pending.monthly_items = items
        pending.step = "monthly_remind_time"
        set_session(uid, pending)
        preview = "\n".join(f"• {item['name']}（每月{item['day']}日）" for item in items)
        _reply_text_with_qr(
            reply_token,
            f"已記錄 {len(items)} 個每月提醒項目：\n{preview}\n\n請選擇每月提醒時間：",
            _monthly_time_quick_reply(),
        )

    elif step in ("monthly_remind_time", "cc_remind_time"):
        m = re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mi <= 59:
                time_val = f"{h:02d}:{mi:02d}"
                pending.reminder_time = time_val
                pending.step = "monthly_remind_confirm"
                set_session(uid, pending)
                _reply_flex(reply_token, line_service.build_monthly_reminder_confirmation_flex(pending.monthly_items, time_val))
            else:
                _reply_text(reply_token, "時間無效，請輸入 HH:MM（例：09:00）或點選上方按鈕。")
        else:
            _reply_text(reply_token, "請輸入時間格式 HH:MM（例：09:00）或點選上方按鈕。")

    else:
        _reply_text(reply_token, "無法解析。\n\n" + event_parser.USAGE_HELP)


# ── MessageEvent 處理 ──────────────────────────────────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def _on_text(event: MessageEvent):
    if event.source.type != "user" or not event.source.user_id:
        return
    uid = event.source.user_id
    if uid not in _get_allowed_ids():
        print(
            f"[LINE] 未授權：本次 userId={uid!r} "
            f"| 白名單筆數={len(_get_allowed_ids())}",
            flush=True,
        )
        _reply_text(
            event.reply_token,
            "未授權的使用者。\n"
            "請到 Cloud Run 日誌搜尋「未授權」取得正確 userId，"
            "並與 LINE_USER_IDS 完全一致（須為此官方帳號對話的 U 開頭 ID）。",
        )
        return

    text = (event.message.text or "").strip()

    # ── 1. 固定指令（不受 session 影響） ─────────────────────────────────────
    if text in ("說明", "help", "Help"):
        _reply_text(event.reply_token, event_parser.USAGE_HELP)
        return

    if text in ("新增行程", "+", "＋"):
        delete_session(uid)
        set_session(uid, PendingEvent(step="wizard_date"))
        _reply_text_with_qr(event.reply_token, "請選擇日期：", _date_quick_reply())
        return

    if ENABLE_REMINDER and text in ("新增提醒", "提醒我"):
        delete_session(uid)
        set_session(uid, PendingEvent(step="reminder_date"))
        _reply_text_with_qr(event.reply_token, "請選擇提醒日期：", _reminder_date_quick_reply())
        return

    if ENABLE_REMINDER and text in (
        "卡費提醒", "繳卡費", "信用卡提醒", "月繳提醒",
        "每月提醒", "月提醒", "每月扣款提醒", "固定提醒",
    ):
        delete_session(uid)
        set_session(uid, PendingEvent(step="monthly_remind_items"))
        _reply_text(
            event.reply_token,
            "🔁 設定每月提醒\n\n"
            "請輸入每個提醒項目與每月日期（每行一筆）\n"
            "格式：提醒項目名稱 日期\n\n"
            "範例：\n房租 5\n信用卡帳單 15\n保險費 20",
        )
        return

    view_date = _try_parse_view(text)
    if view_date:
        delete_session(uid)
        events = calendar_service.get_events(view_date, TIMEZONE)
        if events:
            _reply_flex(event.reply_token, line_service.build_event_list_flex(events, view_date))
        else:
            _reply_text(event.reply_token, f"📅 {view_date.strftime('%Y/%m/%d')} 沒有行程。")
        return

    week_range = _try_parse_week_view(text)
    if week_range:
        delete_session(uid)
        start, end, label = week_range
        events_by_day = calendar_service.get_events_for_days(start, end, TIMEZONE)
        _reply_flex(event.reply_token, line_service.build_week_flex(events_by_day, start, label))
        return

    # ── 2. 嘗試解析為行程格式（有效格式會重置 session） ──────────────────────
    parsed = event_parser.parse_event_line(text, TIMEZONE)
    if parsed:
        delete_session(uid)
        pending = PendingEvent(
            step="confirm",
            summary=_prefixed(parsed.summary, uid),
            start=parsed.start,
            end=parsed.end,
            location=parsed.location,
            is_all_day=parsed.is_all_day,
            all_day_date=parsed.all_day_date,
        )

        # 衝突偵測（全天事件略過）
        conflicts = []
        if not parsed.is_all_day and parsed.start and parsed.end:
            try:
                conflicts = calendar_service.get_events_in_range(
                    parsed.start, parsed.end, TIMEZONE
                )
            except Exception:
                pass  # 查不到衝突不阻擋建立流程

        if conflicts:
            pending.step = "conflict"
            set_session(uid, pending)
            _reply_flex(event.reply_token, line_service.build_conflict_flex(conflicts, pending))
        else:
            set_session(uid, pending)
            _reply_flex(event.reply_token, line_service.build_confirmation_flex(pending))
        return

    # ── 3. 精靈模式文字步驟（wizard_title、wizard_location 等） ──────────────
    session = get_session(uid)
    if session:
        _handle_wizard_text(uid, text, event.reply_token, session)
        return

    # ── 4. 無法解析 ───────────────────────────────────────────────────────────
    _reply_text(event.reply_token, "無法解析時間與標題。\n\n" + event_parser.USAGE_HELP)


# ── PostbackEvent 處理 ─────────────────────────────────────────────────────────

@handler.add(PostbackEvent)
def _on_postback(event: PostbackEvent):
    if event.source.type != "user" or not event.source.user_id:
        return
    uid = event.source.user_id
    if uid not in _get_allowed_ids():
        return

    data        = event.postback.data
    reply_token = event.reply_token
    tz          = ZoneInfo(TIMEZONE)

    # ── 確認建立 ──────────────────────────────────────────────────────────────
    if data in ("confirm", "force_create"):
        pending = get_session(uid)
        if not pending:
            _reply_text(reply_token, "⚠️ 操作逾時，請重新輸入行程。")
            return
        delete_session(uid)
        _do_create_event(pending, reply_token)

    # ── 取消 ──────────────────────────────────────────────────────────────────
    elif data in ("cancel", "reminder:cancel", "monthly_remind:cancel", "cc_remind:cancel"):
        delete_session(uid)
        _reply_text(reply_token, "已取消。")

    # ── 精靈：選日期（快捷按鈕） ──────────────────────────────────────────────
    elif data.startswith("wizard:date:"):
        date_str = data[12:]  # "YYYY-MM-DD"
        display_date = date_str.replace("-", "/")
        pending  = get_session(uid) or PendingEvent(step="wizard_time")
        pending.all_day_date = date_str
        pending.step = "wizard_time"
        set_session(uid, pending)
        _reply_text_with_qr(reply_token, f"請選擇時間（{display_date}）：", _time_quick_reply())

    # ── 精靈：DatetimePicker 選日期 ───────────────────────────────────────────
    elif data == "wizard:pick_date":
        date_str = _extract_postback_date(event)
        if not date_str:
            _reply_text(reply_token, "⚠️ 無法取得日期，請重新點選。")
            return
        display_date = date_str.replace("-", "/")
        pending = get_session(uid) or PendingEvent(step="wizard_time")
        pending.all_day_date = date_str
        pending.step = "wizard_time"
        set_session(uid, pending)
        _reply_text_with_qr(reply_token, f"請選擇時間（{display_date}）：", _time_quick_reply())

    # ── 精靈：選時間 ──────────────────────────────────────────────────────────
    elif data.startswith("wizard:time:"):
        time_val = data[12:]  # "HH:MM" 或 "allday"
        pending  = get_session(uid)
        if not pending:
            _reply_text(reply_token, "⚠️ 操作逾時，請重新輸入「新增行程」。")
            return
        if time_val == "allday":
            pending.is_all_day = True
            pending.step = "wizard_title"
            set_session(uid, pending)
            _reply_text(reply_token, "請輸入行程名稱：")
        else:
            pending.wizard_time = time_val
            pending.step = "wizard_duration"
            set_session(uid, pending)
            _reply_text_with_qr(reply_token, "請選擇時長：", _duration_quick_reply())

    # ── 精靈：選時長 ──────────────────────────────────────────────────────────
    elif data.startswith("wizard:duration:"):
        mins    = int(data[16:])
        pending = get_session(uid)
        if not pending:
            _reply_text(reply_token, "⚠️ 操作逾時，請重新輸入「新增行程」。")
            return
        date_str  = pending.all_day_date or ""
        time_str  = pending.wizard_time or "09:00"
        y, mo, d  = map(int, date_str.split("-"))
        h, mi     = map(int, time_str.split(":"))
        start     = datetime(y, mo, d, h, mi, tzinfo=tz)
        end       = start + timedelta(minutes=mins)
        pending.start        = start
        pending.end          = end
        pending.all_day_date = None
        pending.wizard_time  = ""
        pending.step         = "wizard_title"
        set_session(uid, pending)
        _reply_text(reply_token, "請輸入行程名稱：")

    # ── 精靈：跳過地點 ────────────────────────────────────────────────────────
    elif data == "wizard:skip_location":
        pending = get_session(uid)
        if not pending:
            _reply_text(reply_token, "⚠️ 操作逾時，請重新輸入「新增行程」。")
            return
        pending.location = ""
        pending.step     = "confirm"
        set_session(uid, pending)
        _reply_flex(reply_token, line_service.build_confirmation_flex(pending))

    # ── 提醒精靈：選日期（快捷按鈕） ───────────────────────────────────────────
    elif data.startswith("reminder:date:"):
        date_str = data[14:]  # "YYYY-MM-DD"
        display_date = date_str.replace("-", "/")
        pending = get_session(uid) or PendingEvent(step="reminder_time")
        pending.reminder_date = date_str
        pending.step = "reminder_time"
        set_session(uid, pending)
        _reply_text_with_qr(
            reply_token,
            f"請選擇提醒時間（{display_date}）：",
            _reminder_time_quick_reply(),
        )

    # ── 提醒精靈：DatetimePicker 選日期 ───────────────────────────────────────
    elif data == "reminder:pick_date":
        date_str = _extract_postback_date(event)
        if not date_str:
            _reply_text(reply_token, "⚠️ 無法取得日期，請重新點選。")
            return
        display_date = date_str.replace("-", "/")
        pending = get_session(uid) or PendingEvent(step="reminder_time")
        pending.reminder_date = date_str
        pending.step = "reminder_time"
        set_session(uid, pending)
        _reply_text_with_qr(
            reply_token,
            f"請選擇提醒時間（{display_date}）：",
            _reminder_time_quick_reply(),
        )

    # ── 提醒精靈：選時間 ───────────────────────────────────────────────────────
    elif data.startswith("reminder:time:"):
        time_val = data[14:]  # "HH:MM"
        pending = get_session(uid)
        if not pending:
            _reply_text(reply_token, "⚠️ 操作逾時，請重新輸入「新增提醒」。")
            return
        pending.reminder_time = time_val
        pending.step = "reminder_text"
        set_session(uid, pending)
        _reply_text(reply_token, "請輸入提醒內容：")

    # ── 每月提醒精靈：選時間 ───────────────────────────────────────────────────
    elif data.startswith("monthly_remind:time:") or data.startswith("cc_remind:time:"):
        time_val = data[20:] if data.startswith("monthly_remind:time:") else data[15:]
        pending = get_session(uid)
        if not pending:
            _reply_text(reply_token, "⚠️ 操作逾時，請重新輸入「每月提醒」。")
            return
        pending.reminder_time = time_val
        pending.step = "monthly_remind_confirm"
        set_session(uid, pending)
        _reply_flex(reply_token, line_service.build_monthly_reminder_confirmation_flex(pending.monthly_items, time_val))

    # ── 每月提醒精靈：確認建立 ─────────────────────────────────────────────────
    elif data in ("monthly_remind:confirm", "cc_remind:confirm"):
        pending = get_session(uid)
        if not pending or pending.step != "monthly_remind_confirm":
            _reply_text(reply_token, "⚠️ 操作逾時，請重新輸入「每月提醒」。")
            delete_session(uid)
            return
        items = pending.monthly_items
        remind_time = pending.reminder_time
        if not items or not remind_time:
            _reply_text(reply_token, "⚠️ 資料不完整，請重新輸入「每月提醒」。")
            delete_session(uid)
            return
        created, failed = [], []
        for item in items:
            try:
                remind_at = _next_monthly_occurrence(item["day"], remind_time, tz)
                _create_reminder(
                    uid, remind_at, f"🔁 {item['name']} 每月提醒",
                    recurring=True, day_of_month=item["day"], remind_time=remind_time,
                )
                created.append(item)
            except Exception as e:
                failed.append((item["name"], str(e)))
        delete_session(uid)
        if failed:
            fail_lines = "\n".join(f"• {name}: {err}" for name, err in failed)
            _reply_text(reply_token, f"⚠️ 部分建立失敗：\n{fail_lines}")
        else:
            lines = "\n".join(f"• {item['name']}（每月{item['day']}日）" for item in created)
            _reply_text(
                reply_token,
                f"✅ 每月提醒已建立！\n\n{lines}\n\n提醒時間：{remind_time}\n每月自動發送 🔁",
            )

    # ── 卡費提醒精靈：取消 ─────────────────────────────────────────────────────
    elif data == "cc_remind:cancel":
        delete_session(uid)
        _reply_text(reply_token, "已取消。")

    # ── 行程刪除：第一次點擊 → 確認卡片 ──────────────────────────────────────
    elif data.startswith("delete_event:"):
        event_id = data[13:]
        confirm_bubble = line_service.build_delete_confirm_flex(event_id)
        _reply_flex(reply_token, confirm_bubble)

    # ── 行程刪除：確認刪除 ────────────────────────────────────────────────────
    elif data.startswith("delete_confirm:"):
        event_id = data[15:]
        try:
            calendar_service.delete_event(event_id)
            _reply_text(reply_token, "🗑 行程已刪除。")
        except Exception as e:
            _reply_text(reply_token, f"刪除失敗：{e}")

    # ── 提醒精靈：確認建立 ─────────────────────────────────────────────────────
    elif data == "reminder:confirm":
        pending = get_session(uid)
        if not pending:
            _reply_text(reply_token, "⚠️ 操作逾時，請重新輸入「新增提醒」。")
            return
        if pending.step != "reminder_confirm":
            _reply_text(reply_token, "⚠️ 流程狀態不正確，請重新輸入「新增提醒」。")
            delete_session(uid)
            return

        remind_at = _build_remind_at(pending, tz)
        reminder_text = pending.reminder_text.strip()
        if not remind_at or not reminder_text:
            _reply_text(reply_token, "⚠️ 提醒資料不完整，請重新輸入「新增提醒」。")
            delete_session(uid)
            return
        if remind_at <= datetime.now(tz):
            _reply_text(reply_token, "⚠️ 不能設定過去時間，請重新輸入「新增提醒」。")
            delete_session(uid)
            return

        try:
            task_name = _create_reminder(uid, remind_at, reminder_text)["task_name"]
        except Exception as e:
            _reply_text(reply_token, f"建立提醒失敗：{e}")
            return

        delete_session(uid)
        _reply_text(
            reply_token,
            "✅ 提醒已建立\n"
            f"時間：{remind_at.strftime('%Y/%m/%d %H:%M')}\n"
            f"內容：{reminder_text}\n"
            f"Task：{task_name.split('/')[-1]}",
        )


# ── Flask 路由 ────────────────────────────────────────────────────────────────

_LIFF_PAGES = {"calendar", "event-form", "reminder-manager"}


@app.route("/liff/<page>", methods=["GET"])
def liff_page(page: str):
    if page not in _LIFF_PAGES:
        return "Not Found", 404
    liff_dir = os.path.join(os.path.dirname(__file__), "liff")
    try:
        with open(os.path.join(liff_dir, f"{page}.html"), "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return "Not Found", 404
    content = (content
        .replace("{{LIFF_CALENDAR_ID}}", LIFF_CALENDAR_ID)
        .replace("{{LIFF_FORM_ID}}", LIFF_FORM_ID)
        .replace("{{LIFF_REMINDER_ID}}", LIFF_REMINDER_ID))
    return content, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/callback", methods=["GET"])
def callback_probe():
    """瀏覽器測試用；LINE Verify 實際會對此 URL 送 POST。"""
    return "LINE Webhook：請在 LINE Developers 使用 POST 驗證此路徑。", 200


@app.route("/callback", methods=["POST"])
def callback():
    if not CHANNEL_SECRET:
        return "LINE_CHANNEL_SECRET 未設定", 503
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return (
            "Invalid signature（請檢查 LINE_CHANNEL_SECRET 是否與 "
            "Messaging API 的 Channel secret 完全相同）",
            400,
        )
    return "OK", 200


@app.route("/health", methods=["GET", "POST"])
def health():
    return "ok", 200


# ── LIFF JSON API ─────────────────────────────────────────────────────────────

def _parse_event_body(data: dict, tz: ZoneInfo):
    """從 LIFF 表單 body 解析行程欄位，回傳 (summary, start_dt, end_dt, is_all_day, date_str, end_date_str, location)。"""
    summary    = str(data.get("summary", "")).strip()
    date_str   = str(data.get("date", "")).strip()
    end_date_str = str(data.get("end_date", "")).strip()
    is_all_day = bool(data.get("is_all_day", False))
    location   = str(data.get("location", "")).strip()
    start_dt = end_dt = None
    if not is_all_day:
        st = str(data.get("start_time", "09:00"))
        et = str(data.get("end_time",   "10:00"))
        y, mo, d = map(int, date_str.split("-"))
        sh, sm   = map(int, st.split(":"))
        eh, em   = map(int, et.split(":"))
        start_dt = datetime(y, mo, d, sh, sm, tzinfo=tz)
        end_dt   = datetime(y, mo, d, eh, em, tzinfo=tz)
    return summary, start_dt, end_dt, is_all_day, date_str, end_date_str, location


@app.route("/api/events", methods=["GET"])
@require_liff_auth
def api_events_list(liff_user_id: str):
    tz  = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    try:
        year  = int(request.args.get("year",  now.year))
        month = int(request.args.get("month", now.month))
    except ValueError:
        year, month = now.year, now.month
    start = datetime(year, month, 1, tzinfo=tz)
    import calendar as _cal
    last_day = _cal.monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=tz) + timedelta(seconds=1)
    events_by_day = calendar_service.get_events_for_days(start, end, TIMEZONE)
    result = []
    seen = set()  # 跨天全天事件會出現在多天，只回一次
    for day_evs in events_by_day.values():
        for ev in day_evs:
            if ev["event_id"] in seen:
                continue
            seen.add(ev["event_id"])
            result.append({
                "event_id":   ev["event_id"],
                "summary":    ev["summary"],
                "start":      ev["start_time"].isoformat() if ev["start_time"] else None,
                "end":        ev["end_time"].isoformat()   if ev["end_time"]   else None,
                "is_all_day": ev["is_all_day"],
                "date":       ev["start_time"].strftime("%Y-%m-%d") if ev["start_time"] else ev["date"],
                "end_date":   ev.get("end_date"),
                "location":   ev["location"],
                "is_editable": ev["is_editable"],
            })
    result.sort(key=lambda x: x["start"] or x["date"] or "")
    return jsonify(result), 200


@app.route("/api/events/<event_id>", methods=["GET"])
@require_liff_auth
def api_event_get(event_id: str, liff_user_id: str):
    try:
        ev = calendar_service.get_event(event_id)
    except Exception:
        return jsonify({"error": "Event not found"}), 404
    return jsonify({
        "event_id":   ev["event_id"],
        "summary":    ev["summary"],
        "start":      ev["start_time"].isoformat() if ev["start_time"] else None,
        "end":        ev["end_time"].isoformat()   if ev["end_time"]   else None,
        "is_all_day": ev["is_all_day"],
        "date":       ev["start_time"].strftime("%Y-%m-%d") if ev["start_time"] else ev["date"],
        "end_date":   ev.get("end_date"),
        "location":   ev["location"],
        "is_editable": ev["is_editable"],
    }), 200


@app.route("/api/events", methods=["POST"])
@require_liff_auth
def api_events_create(liff_user_id: str):
    data = request.get_json(silent=True) or {}
    tz   = ZoneInfo(TIMEZONE)
    summary, start_dt, end_dt, is_all_day, date_str, end_date_str, location = _parse_event_body(data, tz)
    if not summary or not date_str:
        return jsonify({"error": "missing required fields"}), 400
    if end_date_str and end_date_str < date_str:
        return jsonify({"error": "結束日期不可早於開始日期"}), 400
    summary = _prefixed(summary, liff_user_id)
    try:
        if is_all_day:
            created = calendar_service.create_all_day_event(summary, date_str, TIMEZONE, location, end_date_str)
        else:
            created = calendar_service.create_timed_event(summary, start_dt, end_dt, TIMEZONE, location)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    try:
        _push_flex(liff_user_id, line_service.build_event_notification_flex(created, is_update=False))
    except Exception as e:
        print(f"[WARN] push flex failed: {e}")
    return jsonify({"event_id": created.get("id", ""), "htmlLink": created.get("htmlLink", "")}), 201


@app.route("/api/events/<event_id>", methods=["PUT"])
@require_liff_auth
def api_event_update(event_id: str, liff_user_id: str):
    data = request.get_json(silent=True) or {}
    tz   = ZoneInfo(TIMEZONE)
    summary, start_dt, end_dt, is_all_day, date_str, end_date_str, location = _parse_event_body(data, tz)
    if end_date_str and end_date_str < date_str:
        return jsonify({"error": "結束日期不可早於開始日期"}), 400
    try:
        updated = calendar_service.update_event(
            event_id, summary, start_dt, end_dt, TIMEZONE, location,
            is_all_day=is_all_day, all_day_date=date_str, all_day_end_date=end_date_str,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        msg = str(e)
        if "404" in msg or "notFound" in msg:
            return jsonify({"error": "Event not found"}), 404
        return jsonify({"error": msg}), 500
    try:
        _push_flex(liff_user_id, line_service.build_event_notification_flex(updated, is_update=True))
    except Exception as e:
        print(f"[WARN] push flex failed: {e}")
    return jsonify({"event_id": updated.get("id", ""), "summary": updated.get("summary", "")}), 200


@app.route("/api/events/<event_id>", methods=["DELETE"])
@require_liff_auth
def api_event_delete(event_id: str, liff_user_id: str):
    try:
        calendar_service.delete_event(event_id)
    except Exception as e:
        msg = str(e)
        if "404" in msg or "notFound" in msg:
            return jsonify({"error": "Event not found"}), 404
        return jsonify({"error": msg}), 500
    return "", 204


# ── LIFF Reminder API ──────────────────────────────────────────────────────────

@app.route("/api/reminders", methods=["GET"])
@require_liff_auth
def api_reminders_list(liff_user_id: str):
    tz  = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    all_records = reminder_store.list_reminders(liff_user_id)
    future = [r for r in all_records if datetime.fromisoformat(r["remind_at"]) > now]
    future.sort(key=lambda r: r["remind_at"])
    return jsonify(future), 200


@app.route("/api/reminders", methods=["POST"])
@require_liff_auth
def api_reminders_create(liff_user_id: str):
    data          = request.get_json(silent=True) or {}
    remind_at_raw = str(data.get("remind_at", "")).strip()
    reminder_text = str(data.get("reminder_text", "")).strip()
    if not remind_at_raw or not reminder_text:
        return jsonify({"error": "missing required fields"}), 400
    try:
        remind_at = datetime.fromisoformat(remind_at_raw)
    except ValueError:
        return jsonify({"error": "invalid remind_at format"}), 400
    tz  = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    if remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=tz)
    if remind_at <= now:
        return jsonify({"error": "remind_at must be in the future"}), 400
    try:
        record = _create_reminder(liff_user_id, remind_at, reminder_text)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(record), 201


@app.route("/api/reminders/<path:task_name_encoded>", methods=["PUT"])
@require_liff_auth
def api_reminders_update(task_name_encoded: str, liff_user_id: str):
    task_name     = urllib.parse.unquote(task_name_encoded)
    data          = request.get_json(silent=True) or {}
    remind_at_raw = str(data.get("remind_at", "")).strip()
    reminder_text = str(data.get("reminder_text", "")).strip()
    if not remind_at_raw or not reminder_text:
        return jsonify({"error": "missing required fields"}), 400
    try:
        remind_at = datetime.fromisoformat(remind_at_raw)
    except ValueError:
        return jsonify({"error": "invalid remind_at format"}), 400
    tz  = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    if remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=tz)
    if remind_at <= now:
        return jsonify({"error": "remind_at must be in the future"}), 400

    existing = reminder_store.get_reminder(task_name)
    if not existing:
        return jsonify({"error": "Not found"}), 404
    if existing.get("user_id") != liff_user_id:
        return jsonify({"error": "Forbidden"}), 403

    # 先建新 task、寫好清單，最後才刪舊 task：中途失敗時舊提醒還在
    try:
        new_task_name = _create_reminder_task(liff_user_id, remind_at, reminder_text)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    new_record = {
        "task_name":     new_task_name,
        "user_id":       liff_user_id,
        "remind_at":     remind_at.isoformat(),
        "reminder_text": reminder_text,
        "recurring":     existing.get("recurring", False),
        "day_of_month":  existing.get("day_of_month"),
        "remind_time":   existing.get("remind_time"),
    }
    try:
        reminder_store.update_reminder(task_name, new_record)
    except Exception as e:
        _delete_reminder_task(new_task_name)
        return jsonify({"error": str(e)}), 500
    _delete_reminder_task(task_name)
    return jsonify(new_record), 200


@app.route("/api/reminders/<path:task_name_encoded>", methods=["DELETE"])
@require_liff_auth
def api_reminders_delete(task_name_encoded: str, liff_user_id: str):
    task_name = urllib.parse.unquote(task_name_encoded)
    existing  = reminder_store.get_reminder(task_name)
    if existing and existing.get("user_id") != liff_user_id:
        return jsonify({"error": "Forbidden"}), 403

    _delete_reminder_task(task_name)
    reminder_store.remove_reminder(task_name)
    return jsonify({"status": "cancelled"}), 200


@app.route("/tasks/daily-notify", methods=["POST"])
def tasks_daily_notify():
    # 服務是公開的（LINE webhook 要打得到），所以自己驗 Cloud Scheduler 帶的 OIDC token：
    # 簽章是 Google 的、audience 是這個網址、email 是指定的 Scheduler SA
    if not SCHEDULER_SA_EMAIL:
        return "SCHEDULER_SA_EMAIL 未設定", 503
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return "Unauthorized", 401
    try:
        claims = id_token.verify_oauth2_token(
            auth.removeprefix("Bearer "),
            google_requests.Request(),
            audience=f"https://{request.host}/tasks/daily-notify",
        )
    except ValueError:
        return "Unauthorized", 401
    if claims.get("email") != SCHEDULER_SA_EMAIL or not claims.get("email_verified"):
        return "Forbidden", 403

    daily_notify()
    return "OK", 200


@app.route("/tasks/reminder", methods=["POST"])
def tasks_reminder():
    auth = request.headers.get("Authorization", "")
    if not REMINDER_TASK_TOKEN:
        return "REMINDER_TASK_TOKEN 未設定", 503
    if auth != f"Bearer {REMINDER_TASK_TOKEN}":
        return "Unauthorized", 401

    payload = request.get_json(silent=True) or {}
    user_id = str(payload.get("user_id", "")).strip()
    reminder_text = str(payload.get("reminder_text", "")).strip()
    remind_at_raw = str(payload.get("remind_at", "")).strip()
    if not user_id or not reminder_text:
        return "Bad Request: missing user_id or reminder_text", 400

    try:
        remind_at = datetime.fromisoformat(remind_at_raw)
    except ValueError:
        remind_at = datetime.now(ZoneInfo(TIMEZONE))

    line_service.send_single_reminder(user_id, reminder_text, remind_at)

    recurring = bool(payload.get("recurring", False))
    day_of_month = payload.get("day_of_month")
    remind_time = str(payload.get("remind_time", "")).strip()
    if recurring and day_of_month and remind_time:
        try:
            tz = ZoneInfo(TIMEZONE)
            next_dt = _next_month_from(remind_at, int(day_of_month), remind_time, tz)
            # 不用 _create_reminder：清單寫入失敗時寧可留著 task，也不要讓每月提醒中斷
            new_task_name = _create_reminder_task(
                user_id, next_dt, reminder_text,
                recurring=True, day_of_month=int(day_of_month), remind_time=remind_time,
            )
            # payload 裡沒有 task_name；Cloud Tasks 會在 header 帶上這個 task 的短 ID
            old_task_name = payload.get("task_name") or request.headers.get("X-CloudTasks-TaskName", "")
            if old_task_name:
                reminder_store.remove_reminder(old_task_name)
            reminder_store.append_reminder({
                "task_name":     new_task_name,
                "user_id":       user_id,
                "remind_at":     next_dt.isoformat(),
                "reminder_text": reminder_text,
                "recurring":     True,
                "day_of_month":  int(day_of_month),
                "remind_time":   remind_time,
            })
            print(f"[Tasks] 自動重排下月提醒：{next_dt.isoformat()}")
        except Exception as e:
            print(f"[WARN] 自動重排失敗：{e}")

    return "OK", 200


if __name__ == "__main__":
    if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
        raise SystemExit("請在 .env 設定 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN")
    if not _get_allowed_ids():
        raise SystemExit("請在 .env 設定 LINE_USER_IDS")
    port = int(os.getenv("PORT", os.getenv("WEBHOOK_PORT", "5000")))
    print(f"Webhook 監聽 http://0.0.0.0:{port}/callback")
    app.run(host="0.0.0.0", port=port)
