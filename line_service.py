import os
from datetime import datetime
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    FlexMessage,
    FlexBubble,
    FlexBox,
    FlexText,
    FlexSeparator,
)


def _build_event_row(event: dict) -> FlexBox:
    """將單一行程組成 Flex row"""
    if event["is_all_day"]:
        time_text = "全天"
        badge_color = "#6C63FF"
    else:
        start = event["start_time"].strftime("%H:%M")
        end = event["end_time"].strftime("%H:%M")
        time_text = f"{start}–{end}"
        badge_color = "#1DB446"

    # 時間 badge
    time_badge = FlexBox(
        type="box",
        layout="vertical",
        contents=[
            FlexText(
                type="text",
                text=time_text,
                size="xs",
                color="#ffffff",
                weight="bold",
                align="center",
            )
        ],
        background_color=badge_color,
        corner_radius="4px",
        padding_all="4px",
        width="90px",
        justify_content="center",
    )

    # 行程標題
    title = FlexText(
        type="text",
        text=event["summary"],
        size="sm",
        weight="bold",
        color="#333333",
        flex=1,
        wrap=True,
        margin="md",
    )

    row_contents = [
        FlexBox(
            type="box",
            layout="horizontal",
            contents=[time_badge, title],
            align_items="center",
        )
    ]

    # 地點（若有）
    if event["location"]:
        row_contents.append(
            FlexBox(
                type="box",
                layout="horizontal",
                contents=[
                    FlexText(type="text", text="📍", size="xs", flex=0),
                    FlexText(
                        type="text",
                        text=event["location"],
                        size="xs",
                        color="#888888",
                        wrap=True,
                        margin="sm",
                    ),
                ],
                margin="sm",
            )
        )

    return FlexBox(
        type="box",
        layout="vertical",
        contents=row_contents,
        padding_all="4px",
    )


def _build_flex_bubble(events: list[dict], label: str) -> FlexBubble:
    """組成完整 FlexBubble"""
    body_contents = []
    for i, event in enumerate(events):
        if i > 0:
            body_contents.append(FlexSeparator(type="separator", margin="md"))
        body_contents.append(_build_event_row(event))

    return FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            contents=[
                FlexText(
                    type="text",
                    text="📅 行程通知",
                    color="#ffffff",
                    size="xs",
                    weight="bold",
                ),
                FlexText(
                    type="text",
                    text=label,
                    color="#ffffff",
                    size="md",
                    weight="bold",
                    wrap=True,
                ),
            ],
            background_color="#4A90E2",
            padding_all="16px",
        ),
        body=FlexBox(
            type="box",
            layout="vertical",
            contents=body_contents,
            spacing="md",
            padding_all="16px",
        ),
        footer=FlexBox(
            type="box",
            layout="vertical",
            contents=[
                FlexText(
                    type="text",
                    text=f"共 {len(events)} 個行程，加油！💪",
                    size="xs",
                    color="#aaaaaa",
                    align="center",
                )
            ],
            padding_all="12px",
        ),
    )


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
        bubble = _build_flex_bubble(events, label)
        flex_msg = FlexMessage(alt_text=label, contents=bubble)
        for user_id in user_ids:
            api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[flex_msg],
                )
            )
    print(f"[LINE] 已發送 Flex Message：{label}（{len(user_ids)} 人）")
