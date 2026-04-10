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
    FlexButton,
    PostbackAction,
    URIAction,
    MessageAction,
)

from session_store import PendingEvent


# ── 共用小元件 ────────────────────────────────────────────────────────────────

def _info_row(icon: str, text: str, bold: bool = False) -> FlexBox:
    """圖示 + 文字的水平資訊列。"""
    return FlexBox(
        type="box",
        layout="horizontal",
        spacing="sm",
        contents=[
            FlexText(type="text", text=icon, size="sm", flex=0, align="start"),
            FlexText(
                type="text",
                text=text,
                size="sm",
                weight="bold" if bold else "regular",
                color="#333333",
                wrap=True,
                flex=1,
            ),
        ],
    )


def _pending_info_rows(pending: PendingEvent) -> list:
    """從 PendingEvent 建立行程資訊列（名稱、日期、時間、地點）。"""
    if pending.is_all_day:
        date_label = (pending.all_day_date or "").replace("-", "/")
        time_label = "全天"
    else:
        date_label = pending.start.strftime("%Y/%m/%d") if pending.start else ""
        start_str  = pending.start.strftime("%H:%M") if pending.start else ""
        end_str    = pending.end.strftime("%H:%M")   if pending.end   else ""
        time_label = f"{start_str} – {end_str}"

    rows = [
        _info_row("📌", pending.summary or "（未命名）", bold=True),
        _info_row("📅", date_label),
        _info_row("⏰", time_label),
    ]
    if pending.location:
        rows.append(_info_row("📍", pending.location))
    return rows


# ── 互動卡片 ──────────────────────────────────────────────────────────────────

def build_confirmation_flex(pending: PendingEvent) -> FlexMessage:
    """建立確認卡片（含「✅ 確認」「❌ 取消」按鈕）。"""
    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            background_color="#F5A623",
            padding_all="16px",
            contents=[
                FlexText(
                    type="text",
                    text="🗓 確認新增行程？",
                    color="#ffffff",
                    size="md",
                    weight="bold",
                )
            ],
        ),
        body=FlexBox(
            type="box",
            layout="vertical",
            spacing="md",
            padding_all="16px",
            contents=_pending_info_rows(pending),
        ),
        footer=FlexBox(
            type="box",
            layout="horizontal",
            spacing="sm",
            padding_all="12px",
            contents=[
                FlexButton(
                    type="button",
                    style="primary",
                    color="#27AE60",
                    action=PostbackAction(label="✅ 確認", data="confirm"),
                    flex=1,
                ),
                FlexButton(
                    type="button",
                    style="secondary",
                    action=PostbackAction(label="❌ 取消", data="cancel"),
                    flex=1,
                ),
            ],
        ),
    )
    return FlexMessage(alt_text="確認新增行程？", contents=bubble)


def build_success_flex(pending: PendingEvent, link: str) -> FlexMessage:
    """建立成功卡片（含「查看行事曆」「繼續新增」按鈕）。"""
    footer_contents = []
    if link:
        footer_contents.append(
            FlexButton(
                type="button",
                style="primary",
                color="#4A90E2",
                action=URIAction(label="查看行事曆", uri=link),
                flex=1,
            )
        )
    footer_contents.append(
        FlexButton(
            type="button",
            style="secondary",
            action=MessageAction(label="繼續新增", text="新增行程"),
            flex=1,
        )
    )

    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            background_color="#27AE60",
            padding_all="16px",
            contents=[
                FlexText(
                    type="text",
                    text="✅ 行程已建立",
                    color="#ffffff",
                    size="md",
                    weight="bold",
                )
            ],
        ),
        body=FlexBox(
            type="box",
            layout="vertical",
            spacing="md",
            padding_all="16px",
            contents=_pending_info_rows(pending),
        ),
        footer=FlexBox(
            type="box",
            layout="horizontal",
            spacing="sm",
            padding_all="12px",
            contents=footer_contents,
        ),
    )
    summary = pending.summary or "行程"
    return FlexMessage(alt_text=f"✅ 已建立：{summary}", contents=bubble)


def build_conflict_flex(conflicts: list[dict], pending: PendingEvent) -> FlexMessage:
    """建立衝突警告卡片（含「還是新增」「取消」按鈕）。"""
    conflict_items = []
    for c in conflicts:
        if c["is_all_day"]:
            label = f"• {c['summary']}（全天）"
        else:
            s = c["start_time"].strftime("%H:%M")
            e = c["end_time"].strftime("%H:%M")
            label = f"• {c['summary']}  {s}–{e}"
        conflict_items.append(
            FlexText(type="text", text=label, size="sm", color="#E74C3C", wrap=True)
        )

    if pending.is_all_day:
        new_when = f"{(pending.all_day_date or '').replace('-', '/')} 全天"
    else:
        s = pending.start.strftime("%H:%M") if pending.start else ""
        e = pending.end.strftime("%H:%M")   if pending.end   else ""
        new_when = f"{s} – {e}"

    body_contents = [
        FlexText(
            type="text",
            text="以下行程時間重疊：",
            size="sm",
            color="#666666",
        ),
        *conflict_items,
        FlexSeparator(type="separator", margin="md"),
        _info_row("📌", pending.summary or "（未命名）", bold=True),
        _info_row("⏰", new_when),
    ]

    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            background_color="#E74C3C",
            padding_all="16px",
            contents=[
                FlexText(
                    type="text",
                    text="⚠️ 時間衝突",
                    color="#ffffff",
                    size="md",
                    weight="bold",
                )
            ],
        ),
        body=FlexBox(
            type="box",
            layout="vertical",
            spacing="sm",
            padding_all="16px",
            contents=body_contents,
        ),
        footer=FlexBox(
            type="box",
            layout="horizontal",
            spacing="sm",
            padding_all="12px",
            contents=[
                FlexButton(
                    type="button",
                    style="primary",
                    color="#E67E22",
                    action=PostbackAction(label="還是新增", data="force_create"),
                    flex=1,
                ),
                FlexButton(
                    type="button",
                    style="secondary",
                    action=PostbackAction(label="取消", data="cancel"),
                    flex=1,
                ),
            ],
        ),
    )
    return FlexMessage(alt_text="⚠️ 偵測到時間衝突，請確認", contents=bubble)


def build_event_list_flex(events: list[dict], date: datetime) -> FlexMessage:
    """建立行程列表卡片。"""
    body_contents = []

    for i, event in enumerate(events):
        if i > 0:
            body_contents.append(FlexSeparator(type="separator", margin="md"))

        if event["is_all_day"]:
            time_text   = "全天"
            badge_color = "#6C63FF"
        else:
            s = event["start_time"].strftime("%H:%M")
            e = event["end_time"].strftime("%H:%M")
            time_text   = f"{s}–{e}"
            badge_color = "#1DB446"

        time_badge = FlexBox(
            type="box",
            layout="vertical",
            background_color=badge_color,
            corner_radius="4px",
            padding_all="4px",
            width="90px",
            justify_content="center",
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
        )

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

        main_row_contents = [time_badge, title]

        event_rows = [
            FlexBox(
                type="box",
                layout="horizontal",
                contents=main_row_contents,
                align_items="center",
            )
        ]

        if event.get("location"):
            event_rows.append(
                FlexBox(
                    type="box",
                    layout="horizontal",
                    margin="sm",
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
                )
            )

        body_contents.append(
            FlexBox(type="box", layout="vertical", contents=event_rows, padding_all="4px")
        )

    date_str = date.strftime("%Y/%m/%d")
    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            background_color="#4A90E2",
            padding_all="16px",
            contents=[
                FlexText(
                    type="text",
                    text="📅 行程查詢",
                    color="#ffffff",
                    size="xs",
                    weight="bold",
                ),
                FlexText(
                    type="text",
                    text=date_str,
                    color="#ffffff",
                    size="md",
                    weight="bold",
                ),
            ],
        ),
        body=FlexBox(
            type="box",
            layout="vertical",
            spacing="md",
            padding_all="16px",
            contents=body_contents,
        ),
        footer=FlexBox(
            type="box",
            layout="vertical",
            padding_all="12px",
            contents=[
                FlexText(
                    type="text",
                    text=f"共 {len(events)} 個行程",
                    size="xs",
                    color="#aaaaaa",
                    align="center",
                )
            ],
        ),
    )
    return FlexMessage(
        alt_text=f"行程查詢：{date_str}（共 {len(events)} 個）",
        contents=bubble,
    )


# ── 排程推播（原有功能） ──────────────────────────────────────────────────────

def _build_event_row(event: dict) -> FlexBox:
    """將單一行程組成 Flex row（用於排程通知）。"""
    if event["is_all_day"]:
        time_text   = "全天"
        badge_color = "#6C63FF"
    else:
        start = event["start_time"].strftime("%H:%M")
        end   = event["end_time"].strftime("%H:%M")
        time_text   = f"{start}–{end}"
        badge_color = "#1DB446"

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
    """組成完整 FlexBubble（用於排程通知）。"""
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
    """發送今日行程通知。"""
    label = f"今日行程提醒（{date.strftime('%m/%d')}）"
    _send(label, events)


def send_tomorrow_notification(events: list[dict], date: datetime):
    """發送明日行程預告。"""
    label = f"明日行程預告（{date.strftime('%m/%d')}）"
    _send(label, events)


def _send(label: str, events: list[dict]):
    token    = os.environ["LINE_CHANNEL_ACCESS_TOKEN"].strip()
    user_ids = [uid.strip() for uid in os.environ["LINE_USER_IDS"].split(",")]

    config = Configuration(access_token=token)
    with ApiClient(config) as client:
        api    = MessagingApi(client)
        bubble = _build_flex_bubble(events, label)
        flex_msg = FlexMessage(alt_text=label, contents=bubble)
        for user_id in user_ids:
            api.push_message(
                PushMessageRequest(to=user_id, messages=[flex_msg])
            )
    print(f"[LINE] 已發送 Flex Message：{label}（{len(user_ids)} 人）")
