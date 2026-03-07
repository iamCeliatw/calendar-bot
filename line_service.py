import os
from datetime import datetime
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)


def _build_message(events: list[dict], label: str) -> str:
    """將行程列表組成 LINE 訊息文字"""
    if not events:
        return f"📅 {label}\n\n目前沒有行程，好好休息！"

    lines = [f"📅 {label}\n"]

    for e in events:
        if e["is_all_day"]:
            lines.append(f"🔵 【全天】{e['summary']}")
        else:
            start = e["start_time"].strftime("%H:%M")
            end = e["end_time"].strftime("%H:%M")
            lines.append(f"🕐 {start}–{end}  {e['summary']}")

        if e["location"]:
            lines.append(f"   📍 {e['location']}")

    count = len(events)
    lines.append(f"\n共 {count} 個行程，加油！💪")
    return "\n".join(lines)


def send_today_notification(events: list[dict], date: datetime):
    """發送今日行程通知"""
    label = f"今日行程提醒（{date.strftime('%m/%d')}）"
    _send(label, events)


def send_tomorrow_notification(events: list[dict], date: datetime):
    """發送明日行程預告"""
    label = f"明日行程預告（{date.strftime('%m/%d')}）"
    _send(label, events)


def _send(label: str, events: list[dict]):
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"].strip()
    user_id = os.environ["LINE_USER_ID"]

    config = Configuration(access_token=token)
    with ApiClient(config) as client:
        api = MessagingApi(client)
        message = _build_message(events, label)
        api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(type="text", text=message)],
            )
        )
    print(f"[LINE] 已發送：{label}")
