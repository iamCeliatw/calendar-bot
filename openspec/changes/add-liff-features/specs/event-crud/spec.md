## ADDED Requirements

### Requirement: calendar_service 支援更新行程
系統 SHALL 在 `calendar_service.py` 新增 `update_event(event_id, summary, start, end, timezone_str, location)` 函數，呼叫 Google Calendar API `events().patch()` 更新指定行程，回傳更新後的事件物件。

#### Scenario: 成功更新有時段的行程
- **WHEN** 呼叫 `update_event("abc123", "新標題", start_dt, end_dt, "Asia/Taipei", "")`
- **THEN** Google Calendar 中對應事件的 summary、start、end 被更新，函數回傳更新後事件 dict

#### Scenario: event_id 不存在時拋出例外
- **WHEN** 呼叫 `update_event("nonexistent", ...)` 且 Google Calendar 回傳 404
- **THEN** 函數拋出 `HttpError`，呼叫方應捕捉並回傳 HTTP 404

---

### Requirement: calendar_service 支援刪除行程
系統 SHALL 在 `calendar_service.py` 新增 `delete_event(event_id)` 函數，呼叫 Google Calendar API `events().delete()` 刪除指定行程。

#### Scenario: 成功刪除行程
- **WHEN** 呼叫 `delete_event("abc123")`
- **THEN** Google Calendar 中對應事件被刪除，函數正常返回（無回傳值）

#### Scenario: 刪除不存在的行程
- **WHEN** 呼叫 `delete_event("nonexistent")`
- **THEN** 函數拋出 `HttpError(404)`

---

### Requirement: 後端提供行程更新 API
系統 SHALL 實作 `PUT /api/events/<event_id>`，接受 JSON body `{summary, date, start_time, end_time, is_all_day, location}`，更新 Google Calendar 行程並回傳更新後物件。

#### Scenario: 成功更新行程
- **WHEN** 合法請求帶有完整欄位且 event_id 存在
- **THEN** 系統更新 Google Calendar 事件，回傳 `{"event_id": "...", "summary": "..."}` HTTP 200

#### Scenario: event_id 不存在
- **WHEN** 指定的 event_id 在 Google Calendar 找不到
- **THEN** 系統回傳 HTTP 404 `{"error": "Event not found"}`

---

### Requirement: 後端提供行程刪除 API
系統 SHALL 實作 `DELETE /api/events/<event_id>`，呼叫 Google Calendar API 刪除行程，並回傳 HTTP 204。

#### Scenario: 成功刪除行程
- **WHEN** 合法請求且 event_id 存在
- **THEN** 系統刪除 Google Calendar 事件，回傳 HTTP 204

#### Scenario: 刪除不存在的行程
- **WHEN** 指定 event_id 不存在
- **THEN** 系統回傳 HTTP 404 `{"error": "Event not found"}`

---

### Requirement: 行程 Flex 卡片加入編輯與刪除按鈕
系統 SHALL 在 `line_service.py` 的 `build_event_list_flex` 和 `build_success_flex` 卡片中，為每個行程加入「✏️ 編輯」按鈕（URIAction，LIFF 表單 URL 帶 event_id）和「🗑 刪除」按鈕（PostbackAction，data 格式 `delete_event:<event_id>`）。僅當 `LIFF_FORM_ID` 環境變數已設定時才顯示編輯按鈕。

#### Scenario: LIFF_FORM_ID 已設定時顯示編輯按鈕
- **WHEN** `LIFF_FORM_ID` 環境變數已設定，渲染行程 Flex 卡片
- **THEN** 卡片 footer 顯示「✏️ 編輯」按鈕，URIAction 指向 `https://liff.line.me/{LIFF_FORM_ID}?event_id={event_id}`

#### Scenario: LIFF_FORM_ID 未設定時不顯示編輯按鈕
- **WHEN** `LIFF_FORM_ID` 為空，渲染行程 Flex 卡片
- **THEN** 卡片不顯示「編輯」按鈕，維持原有版面

#### Scenario: 使用者點擊刪除並確認
- **WHEN** 使用者在 LINE 對話點擊「🗑 刪除」按鈕（PostbackAction）
- **THEN** Webhook 收到 `delete_event:<event_id>` postback，回覆確認 Flex 卡片含「確認刪除」「取消」

#### Scenario: 使用者確認刪除行程
- **WHEN** 使用者點擊「確認刪除」（PostbackAction `delete_confirm:<event_id>`）
- **THEN** 系統呼叫 `calendar_service.delete_event`，成功後回覆「🗑 行程已刪除」文字訊息
