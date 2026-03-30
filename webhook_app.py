"""
LINE Webhook：接收使用者文字訊息並寫入 Google Calendar。

部署需公開 HTTPS URL（本機可用 ngrok 等轉發）。
環境變數：LINE_CHANNEL_ACCESS_TOKEN、LINE_CHANNEL_SECRET、LINE_USER_IDS、TIMEZONE
"""

import os

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
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

import calendar_service
import event_parser

load_dotenv()

app = Flask(__name__)

CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "").strip()
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
TIMEZONE = os.getenv("TIMEZONE", "Asia/Taipei")

_allowed_ids: frozenset[str] | None = None


def _get_allowed_ids() -> frozenset[str]:
    global _allowed_ids
    if _allowed_ids is None:
        raw = os.environ.get("LINE_USER_IDS", "")
        # 允許逗號或換行分隔，避免從記事本貼上多一行就對不到
        parts = raw.replace("\r", "\n").replace(",", "\n").split("\n")
        _allowed_ids = frozenset(p.strip() for p in parts if p.strip())
    return _allowed_ids


handler = WebhookHandler(CHANNEL_SECRET)


def _reply_text(reply_token: str, text: str) -> None:
    config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    with ApiClient(config) as client:
        api = MessagingApi(client)
        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )


@handler.add(MessageEvent, message=TextMessageContent)
def _on_text(event: MessageEvent):
    if event.source.type != "user" or not event.source.user_id:
        return
    uid = event.source.user_id
    if uid not in _get_allowed_ids():
        # Cloud Run 日誌可查此字串，將此 userId 設進 LINE_USER_IDS 即可
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
    if text in ("說明", "help", "Help"):
        _reply_text(event.reply_token, event_parser.USAGE_HELP)
        return

    parsed = event_parser.parse_event_line(text, TIMEZONE)
    if not parsed:
        _reply_text(
            event.reply_token,
            "無法解析時間與標題。\n\n" + event_parser.USAGE_HELP,
        )
        return

    start, end, summary = parsed
    try:
        created = calendar_service.create_timed_event(
            summary, start, end, TIMEZONE
        )
        link = created.get("htmlLink", "")
        when = f"{start.strftime('%Y-%m-%d %H:%M')} – {end.strftime('%H:%M')}"
        msg = f"已建立：{summary}\n{when}"
        if link:
            msg += f"\n{link}"
        _reply_text(event.reply_token, msg)
    except Exception as e:
        _reply_text(event.reply_token, f"寫入日曆失敗：{e}")


@app.route("/callback", methods=["GET"])
def callback_probe():
    """瀏覽器測試用；LINE Verify 實際會對此 URL 送 POST。"""
    return "LINE Webhook：請在 LINE Developers 使用 POST 驗證此路徑。", 200


@app.route("/callback", methods=["POST"])
def callback():
    if not CHANNEL_SECRET:
        return "LINE_CHANNEL_SECRET 未設定", 503
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        # 多數是 Cloud Run 的 Channel secret 與 LINE 後台不一致
        return "Invalid signature（請檢查 LINE_CHANNEL_SECRET 是否與 Messaging API 的 Channel secret 完全相同）", 400
    return "OK", 200


@app.route("/health", methods=["GET", "POST"])
def health():
    # LINE Verify 若誤填成 /health，會送 POST；僅 GET 會得到 405 導致 Verify 失敗
    return "ok", 200


if __name__ == "__main__":
    if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
        raise SystemExit("請在 .env 設定 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN")
    if not _get_allowed_ids():
        raise SystemExit("請在 .env 設定 LINE_USER_IDS")
    # Cloud Run 注入 PORT；本機可用 WEBHOOK_PORT
    port = int(os.getenv("PORT", os.getenv("WEBHOOK_PORT", "5000")))
    print(f"Webhook 監聽 http://0.0.0.0:{port}/callback")
    app.run(host="0.0.0.0", port=port)
