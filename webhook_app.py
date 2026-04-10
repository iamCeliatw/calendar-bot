"""
LINE Webhook：接收使用者文字訊息並寫入 Google Calendar。

部署需公開 HTTPS URL（本機可用 ngrok 等轉發）。
環境變數：LINE_CHANNEL_ACCESS_TOKEN、LINE_CHANNEL_SECRET、LINE_USER_IDS、TIMEZONE
"""

import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    FlexMessage,
    QuickReply,
    QuickReplyItem,
    PostbackAction,
    MessageAction,
    DatetimePickerAction,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent

import calendar_service
import event_parser
import line_service
from session_store import PendingEvent, get_session, set_session, delete_session

load_dotenv()

app = Flask(__name__)

CHANNEL_SECRET       = os.environ.get("LINE_CHANNEL_SECRET", "").strip()
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
TIMEZONE             = os.getenv("TIMEZONE", "Asia/Taipei")

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
    name = _get_user_names().get(uid, "")
    return f"【{name}】{summary}" if name else summary


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
        link = created.get("htmlLink", "")
        _reply_flex(reply_token, line_service.build_success_flex(pending, link))
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
    elif data == "cancel":
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
        params = event.postback.params
        date_str = ""
        try:
            if params is not None:
                date_str = getattr(params, "date", None) or ""
                if not date_str and isinstance(params, dict):
                    date_str = params.get("date", "") or ""
        except Exception:
            pass
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


# ── Flask 路由 ────────────────────────────────────────────────────────────────

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


if __name__ == "__main__":
    if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
        raise SystemExit("請在 .env 設定 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN")
    if not _get_allowed_ids():
        raise SystemExit("請在 .env 設定 LINE_USER_IDS")
    port = int(os.getenv("PORT", os.getenv("WEBHOOK_PORT", "5000")))
    print(f"Webhook 監聽 http://0.0.0.0:{port}/callback")
    app.run(host="0.0.0.0", port=port)
