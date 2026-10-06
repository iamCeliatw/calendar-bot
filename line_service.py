import os
from datetime import datetime
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    FlexBubble,
    FlexBox,
    FlexText,
    FlexSeparator,
    FlexButton,
    FlexFiller,
    PostbackAction,
    URIAction,
    MessageAction,
    FlexCarousel,
)

_LIFF_FORM_ID     = os.getenv("LIFF_FORM_ID", "").strip()
_LIFF_CALENDAR_ID = os.getenv("LIFF_CALENDAR_ID", "").strip()

from session_store import PendingEvent

_WEEKDAY_ZH = ("週一", "週二", "週三", "週四", "週五", "週六", "週日")


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


def build_event_notification_flex(raw_event: dict, is_update: bool = False) -> FlexMessage:
    """LIFF 建立/更新行程後，由 bot 推送的通知卡片。raw_event 為 Google Calendar API 回應。"""
    title  = "✅ 行程已更新" if is_update else "✅ 行程已建立"
    color  = "#2980B9" if is_update else "#27AE60"
    summary = raw_event.get("summary", "（無標題）")
    link    = raw_event.get("htmlLink", "")
    event_id = raw_event.get("id", "")

    start = raw_event.get("start", {})
    end   = raw_event.get("end", {})
    if "date" in start:
        from datetime import date as _d, timedelta as _td
        last = (_d.fromisoformat(end["date"]) - _td(days=1)).isoformat() if end.get("date") else start["date"]
        time_str = f"{start['date']}（全天）" if last == start["date"] else f"{start['date']} ～ {last}（全天）"
    else:
        dt_s = start.get("dateTime", "")
        dt_e = end.get("dateTime", "")
        if dt_s and dt_e:
            from datetime import datetime as _dt
            from zoneinfo import ZoneInfo as _ZI
            tz = _ZI("Asia/Taipei")
            s = _dt.fromisoformat(dt_s).astimezone(tz)
            e = _dt.fromisoformat(dt_e).astimezone(tz)
            time_str = f"{s.strftime('%Y/%m/%d %H:%M')} – {e.strftime('%H:%M')}"
        else:
            time_str = dt_s[:16].replace("T", " ") if dt_s else ""
    location = raw_event.get("location", "")

    body_rows = [_info_row("📌", summary, bold=True), _info_row("🕐", time_str)]
    if location:
        body_rows.append(_info_row("📍", location))

    footer_btns = []
    if _LIFF_FORM_ID and event_id:
        footer_btns.append(FlexButton(
            type="button", style="secondary", height="sm", flex=1,
            action=URIAction(label="✏️ 編輯", uri=f"https://liff.line.me/{_LIFF_FORM_ID}?event_id={event_id}"),
        ))
    if _LIFF_CALENDAR_ID:
        footer_btns.append(FlexButton(
            type="button", style="primary", color="#4A90E2", height="sm", flex=1,
            action=URIAction(label="查看行事曆", uri=f"https://liff.line.me/{_LIFF_CALENDAR_ID}"),
        ))
    elif link:
        footer_btns.append(FlexButton(
            type="button", style="primary", color="#4A90E2", height="sm", flex=1,
            action=URIAction(label="查看行事曆", uri=link),
        ))

    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box", layout="vertical", background_color=color, padding_all="14px",
            contents=[FlexText(type="text", text=title, color="#ffffff", size="md", weight="bold")],
        ),
        body=FlexBox(
            type="box", layout="vertical", spacing="sm", padding_all="14px",
            contents=body_rows,
        ),
        footer=FlexBox(
            type="box", layout="horizontal", spacing="sm", padding_all="12px",
            contents=footer_btns,
        ) if footer_btns else None,
    )
    return FlexMessage(alt_text=f"{title}：{summary}", contents=bubble)


def build_success_flex(pending: PendingEvent, link: str, event_id: str = "") -> FlexMessage:
    """建立成功卡片（含「查看行事曆」「繼續新增」按鈕）。"""
    footer_contents = []
    if _LIFF_FORM_ID and event_id:
        footer_contents.append(
            FlexButton(
                type="button",
                style="secondary",
                height="sm",
                action=URIAction(
                    label="✏️ 編輯",
                    uri=f"https://liff.line.me/{_LIFF_FORM_ID}?event_id={event_id}",
                ),
                flex=1,
            )
        )
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


def build_delete_confirm_flex(event_id: str) -> FlexMessage:
    """建立刪除行程確認卡片。"""
    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            background_color="#E74C3C",
            padding_all="16px",
            contents=[
                FlexText(type="text", text="🗑 確認刪除行程？", color="#ffffff", size="md", weight="bold")
            ],
        ),
        body=FlexBox(
            type="box",
            layout="vertical",
            padding_all="16px",
            contents=[
                FlexText(type="text", text="此操作無法復原，確定要刪除嗎？", size="sm", color="#666666", wrap=True)
            ],
        ),
        footer=FlexBox(
            type="box",
            layout="horizontal",
            spacing="sm",
            padding_all="12px",
            contents=[
                FlexButton(
                    type="button", style="primary", color="#E74C3C",
                    action=PostbackAction(label="確認刪除", data=f"delete_confirm:{event_id}"),
                    flex=1,
                ),
                FlexButton(
                    type="button", style="secondary",
                    action=PostbackAction(label="取消", data="cancel"),
                    flex=1,
                ),
            ],
        ),
    )
    return FlexMessage(alt_text="確認刪除行程？", contents=bubble)


def build_reminder_confirmation_flex(remind_at: datetime, reminder_text: str) -> FlexMessage:
    """建立提醒確認卡片（含「✅ 建立提醒」「❌ 取消」按鈕）。"""
    when_text = remind_at.strftime("%Y/%m/%d %H:%M")
    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            background_color="#8E44AD",
            padding_all="16px",
            contents=[
                FlexText(
                    type="text",
                    text="⏰ 確認建立提醒？",
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
            contents=[
                _info_row("📅", when_text),
                _info_row("📝", reminder_text, bold=True),
            ],
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
                    action=PostbackAction(label="✅ 建立提醒", data="reminder:confirm"),
                    flex=1,
                ),
                FlexButton(
                    type="button",
                    style="secondary",
                    action=PostbackAction(label="❌ 取消", data="reminder:cancel"),
                    flex=1,
                ),
            ],
        ),
    )
    return FlexMessage(alt_text=f"確認提醒：{when_text}", contents=bubble)


def build_monthly_reminder_confirmation_flex(items: list[dict], remind_time: str) -> FlexMessage:
    """建立每月提醒確認卡片。"""
    item_rows = []
    for item in items:
        item_rows.append(
            FlexBox(
                type="box",
                layout="horizontal",
                spacing="sm",
                contents=[
                    FlexText(type="text", text="🔔", size="sm", flex=0),
                    FlexText(
                        type="text",
                        text=item["name"],
                        size="sm",
                        weight="bold",
                        color="#333333",
                        flex=1,
                    ),
                    FlexText(
                        type="text",
                        text=f"每月 {item['day']} 日",
                        size="sm",
                        color="#666666",
                        flex=0,
                        align="end",
                    ),
                ],
            )
        )

    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            background_color="#2C7BE5",
            padding_all="16px",
            contents=[
                FlexText(
                    type="text",
                    text="🔁 確認設定每月提醒？",
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
            contents=[
                _info_row("⏰", f"提醒時間：{remind_time}"),
                FlexSeparator(type="separator", margin="md"),
                *item_rows,
            ],
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
                    action=PostbackAction(label="✅ 確認設定", data="monthly_remind:confirm"),
                    flex=1,
                ),
                FlexButton(
                    type="button",
                    style="secondary",
                    action=PostbackAction(label="❌ 取消", data="monthly_remind:cancel"),
                    flex=1,
                ),
            ],
        ),
    )
    return FlexMessage(alt_text="確認設定每月提醒？", contents=bubble)


def build_reminder_arrived_flex(remind_at: datetime, reminder_text: str) -> FlexMessage:
    """到點推播用的提醒卡片（與確認卡風格一致、易讀）。"""
    wk = _WEEKDAY_ZH[remind_at.weekday()]
    date_line = f"{remind_at.strftime('%Y/%m/%d')}（{wk}）"
    time_line = remind_at.strftime("%H:%M")
    alt = f"⏰ 提醒：{reminder_text}"
    if len(alt) > 400:
        alt = alt[:397] + "..."

    bubble = FlexBubble(
        type="bubble",
        header=FlexBox(
            type="box",
            layout="vertical",
            background_color="#8E44AD",
            padding_all="16px",
            contents=[
                FlexText(
                    type="text",
                    text="⏰ 提醒時間到",
                    color="#ffffff",
                    size="md",
                    weight="bold",
                ),
                FlexText(
                    type="text",
                    text="以下是您先前排定的提醒",
                    color="#E8DAEF",
                    size="xs",
                    margin="sm",
                    wrap=True,
                ),
            ],
        ),
        body=FlexBox(
            type="box",
            layout="vertical",
            spacing="md",
            padding_all="16px",
            contents=[
                FlexBox(
                    type="box",
                    layout="vertical",
                    background_color="#F4ECFF",
                    corner_radius="8px",
                    padding_all="12px",
                    spacing="xs",
                    contents=[
                        FlexText(
                            type="text",
                            text="預定時間",
                            size="xs",
                            color="#7D3C98",
                            weight="bold",
                        ),
                        FlexBox(
                            type="box",
                            layout="horizontal",
                            spacing="sm",
                            align_items="flex-end",
                            contents=[
                                FlexText(
                                    type="text",
                                    text=date_line,
                                    size="sm",
                                    color="#333333",
                                    wrap=True,
                                    flex=1,
                                ),
                                FlexText(
                                    type="text",
                                    text=time_line,
                                    size="xl",
                                    weight="bold",
                                    color="#6C3483",
                                    flex=0,
                                ),
                                FlexFiller(type="filler"),
                            ],
                        ),
                    ],
                ),
                FlexSeparator(type="separator", margin="none"),
                FlexBox(
                    type="box",
                    layout="vertical",
                    background_color="#FFFBF0",
                    corner_radius="8px",
                    padding_all="12px",
                    spacing="xs",
                    contents=[
                        FlexText(
                            type="text",
                            text="提醒內容",
                            size="xs",
                            color="#B7950B",
                            weight="bold",
                        ),
                        FlexText(
                            type="text",
                            text=reminder_text,
                            size="md",
                            color="#333333",
                            weight="bold",
                            wrap=True,
                        ),
                    ],
                ),
            ],
        ),
    )
    return FlexMessage(alt_text=alt, contents=bubble)


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

        event_id = event.get("event_id", "")
        action_btns = []
        if _LIFF_FORM_ID and event_id:
            action_btns.append(
                FlexButton(
                    type="button",
                    style="secondary",
                    height="sm",
                    action=URIAction(
                        label="✏️ 編輯",
                        uri=f"https://liff.line.me/{_LIFF_FORM_ID}?event_id={event_id}",
                    ),
                    flex=1,
                )
            )
        if event_id:
            action_btns.append(
                FlexButton(
                    type="button",
                    style="secondary",
                    height="sm",
                    action=PostbackAction(label="🗑 刪除", data=f"delete_event:{event_id}"),
                    flex=1,
                )
            )
        if action_btns:
            event_rows.append(
                FlexBox(
                    type="box",
                    layout="horizontal",
                    spacing="sm",
                    margin="sm",
                    contents=action_btns,
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


# ── 週行程卡片 ────────────────────────────────────────────────────────────────

_WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def build_week_flex(
    events_by_day: dict[str, list[dict]],
    week_start: datetime,
    label: str,
) -> FlexMessage:
    """建立週行程 Carousel（每天一個 Bubble，有行程才顯示；全週無行程時顯示提示）。"""
    from datetime import timedelta

    bubbles = []
    for date_str, events in events_by_day.items():
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        wd = _WEEKDAY_NAMES[date_obj.weekday()]
        date_label = f"{date_obj.strftime('%m/%d')}（{wd}）"

        if not events:
            continue

        body_contents = []
        for i, event in enumerate(events):
            if i > 0:
                body_contents.append(FlexSeparator(type="separator", margin="sm"))
            if event["is_all_day"]:
                time_text = "全天"
                badge_color = "#6C63FF"
            else:
                s = event["start_time"].strftime("%H:%M")
                e = event["end_time"].strftime("%H:%M")
                time_text = f"{s}–{e}"
                badge_color = "#1DB446"

            time_badge = FlexBox(
                type="box",
                layout="vertical",
                background_color=badge_color,
                corner_radius="4px",
                padding_all="4px",
                width="80px",
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
                margin="sm",
            )
            row_contents = [
                FlexBox(
                    type="box",
                    layout="horizontal",
                    contents=[time_badge, title],
                    align_items="center",
                    margin="sm",
                )
            ]
            if event.get("location"):
                row_contents.append(
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
            body_contents.append(FlexBox(type="box", layout="vertical", contents=row_contents))

        bubble = FlexBubble(
            type="bubble",
            size="kilo",
            header=FlexBox(
                type="box",
                layout="vertical",
                background_color="#4A90E2",
                padding_all="12px",
                contents=[
                    FlexText(
                        type="text",
                        text=date_label,
                        color="#ffffff",
                        size="sm",
                        weight="bold",
                    )
                ],
            ),
            body=FlexBox(
                type="box",
                layout="vertical",
                spacing="sm",
                padding_all="12px",
                contents=body_contents,
            ),
        )
        bubbles.append(bubble)

    week_end = week_start + timedelta(days=6)
    range_str = f"{week_start.strftime('%m/%d')}–{week_end.strftime('%m/%d')}"
    alt = f"📆 {label}行程 {range_str}"

    if not bubbles:
        bubble = FlexBubble(
            type="bubble",
            body=FlexBox(
                type="box",
                layout="vertical",
                padding_all="20px",
                contents=[
                    FlexText(
                        type="text",
                        text=f"📆 {label}（{range_str}）\n沒有任何行程。",
                        size="sm",
                        color="#888888",
                        wrap=True,
                        align="center",
                    )
                ],
            ),
        )
        return FlexMessage(alt_text=alt, contents=bubble)

    carousel = FlexCarousel(type="carousel", contents=bubbles)
    return FlexMessage(alt_text=alt, contents=carousel)


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


def send_single_reminder(user_id: str, reminder_text: str, remind_at: datetime) -> None:
    """發送單一使用者提醒訊息（Flex 卡片）。"""
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"].strip()
    flex_msg = build_reminder_arrived_flex(remind_at, reminder_text)
    config = Configuration(access_token=token)
    with ApiClient(config) as client:
        api = MessagingApi(client)
        api.push_message(
            PushMessageRequest(to=user_id, messages=[flex_msg])
        )
    print(f"[LINE] 已發送提醒給 {user_id}")
