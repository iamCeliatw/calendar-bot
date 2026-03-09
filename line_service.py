import os
from datetime import datetime
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    FlexMessage,
)


def _build_event_row(event: dict) -> dict:
    """將單一行程組成 Flex bubble body 的一個區塊"""
    contents = []

    # 時間標籤
    if event["is_all_day"]:
        time_text = "全天"
        time_color = "#6C63FF"
    else:
        start = event["start_time"].strftime("%H:%M")
        end = event["end_time"].strftime("%H:%M")
        time_text = f"{start} – {end}"
        time_color = "#1DB446"

    contents.append({
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": time_text,
                        "size": "xs",
                        "color": "#ffffff",
                        "weight": "bold",
                        "align": "center",
                    }
                ],
                "backgroundColor": time_color,
                "cornerRadius": "4px",
                "paddingAll": "4px",
                "width": "90px",
                "justifyContent": "center",
            },
            {
                "type": "text",
                "text": event["summary"],
                "size": "sm",
                "weight": "bold",
                "color": "#333333",
                "flex": 1,
                "wrap": True,
                "margin": "md",
            },
        ],
        "alignItems": "center",
    })

    # 地點（若有）
    if event["location"]:
        contents.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": "📍",
                    "size": "xs",
                    "flex": 0,
                },
                {
                    "type": "text",
                    "text": event["location"],
                    "size": "xs",
                    "color": "#888888",
                    "wrap": True,
                    "margin": "sm",
                },
            ],
            "margin": "sm",
        })

    return {
        "type": "box",
        "layout": "vertical",
        "contents": contents,
        "paddingAll": "4px",
    }


def _build_flex_contents(events: list[dict], label: str) -> dict:
    """組成完整的 Flex Bubble JSON"""
    body_contents = []

    for i, event in enumerate(events):
        if i > 0:
            body_contents.append({"type": "separator", "margin": "md"})
        body_contents.append(_build_event_row(event))

    count = len(events)

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "📅 行程通知",
                    "color": "#ffffff",
                    "size": "xs",
                    "weight": "bold",
                },
                {
                    "type": "text",
                    "text": label,
                    "color": "#ffffff",
                    "size": "md",
                    "weight": "bold",
                    "wrap": True,
                },
            ],
            "backgroundColor": "#4A90E2",
            "paddingAll": "16px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "spacing": "md",
            "paddingAll": "16px",
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"共 {count} 個行程，加油！💪",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "align": "center",
                }
            ],
            "paddingAll": "12px",
        },
        "styles": {
            "header": {"separator": False},
            "footer": {"separator": True},
        },
    }


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
    user_ids = [uid.strip() for uid in os.environ["LINE_USER_IDS"].split(",")]

    config = Configuration(access_token=token)
    with ApiClient(config) as client:
        api = MessagingApi(client)
        flex_contents = _build_flex_contents(events, label)
        flex_msg = FlexMessage(alt_text=label, contents=flex_contents)
        for user_id in user_ids:
            api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[flex_msg],
                )
            )
    print(f"[LINE] 已發送 Flex Message：{label}（{len(user_ids)} 人）")
