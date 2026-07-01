## ADDED Requirements

### Requirement: LIFF 行程表單支援新增模式
系統 SHALL 在 `liff/event-form.html` 提供行程新增表單，包含欄位：標題（必填）、日期（必填）、開始時間、結束時間、地點（選填）、全天切換開關。表單提交後呼叫後端 `POST /api/events`。

#### Scenario: 成功提交有效的新行程
- **WHEN** 使用者填寫標題與日期後點擊「建立行程」
- **THEN** 前端呼叫 `POST /api/events`，成功後使用 `liff.sendMessages` 在 LINE 對話中發送成功 Flex 卡片，並執行 `liff.closeWindow()`

#### Scenario: 標題為空時阻擋提交
- **WHEN** 使用者未填寫標題直接點擊「建立行程」
- **THEN** 表單顯示「請輸入行程名稱」驗證錯誤，不發送請求

#### Scenario: 開始時間晚於結束時間時顯示警告
- **WHEN** 使用者設定開始時間 > 結束時間
- **THEN** 表單顯示「結束時間須晚於開始時間」，阻擋提交

#### Scenario: 切換全天開關時隱藏時間欄位
- **WHEN** 使用者開啟「全天」開關
- **THEN** 開始/結束時間欄位隱藏，提交時建立全天事件

---

### Requirement: LIFF 行程表單支援編輯模式
系統 SHALL 在 `liff/event-form.html` 偵測 URL query string `?event_id=<id>`，若存在則以 `GET /api/events/<id>` 取得現有行程資料，預填表單欄位；提交時呼叫 `PUT /api/events/<id>`。

#### Scenario: 成功開啟編輯模式並預填資料
- **WHEN** 頁面 URL 含 `?event_id=abc123`
- **THEN** 頁面標題顯示「編輯行程」，各欄位帶入現有標題、日期、時間、地點

#### Scenario: event_id 對應的行程不存在
- **WHEN** URL 含 `?event_id=nonexistent`，後端回傳 404
- **THEN** 頁面顯示「找不到此行程」，表單切換為新增模式

#### Scenario: 成功更新行程
- **WHEN** 使用者修改標題後點擊「更新行程」
- **THEN** 前端呼叫 `PUT /api/events/<id>`，成功後 `liff.sendMessages` 發送「行程已更新」訊息，執行 `liff.closeWindow()`

---

### Requirement: 後端提供行程建立 API
系統 SHALL 實作 `POST /api/events`，接受 JSON body `{summary, date, start_time, end_time, is_all_day, location}`，在 Google Calendar 建立行程並回傳 `{event_id, htmlLink}`。

#### Scenario: 成功建立有時段的行程
- **WHEN** 合法請求帶有 summary、date、start_time、end_time
- **THEN** 系統在 Google Calendar 建立事件，回傳 `{"event_id": "...", "htmlLink": "..."}` HTTP 201

#### Scenario: 成功建立全天行程
- **WHEN** 合法請求帶有 summary、date 且 `is_all_day: true`
- **THEN** 系統建立全天事件，回傳 HTTP 201

#### Scenario: 缺少必要欄位
- **WHEN** 請求 body 缺少 `summary` 或 `date`
- **THEN** 系統回傳 HTTP 400 `{"error": "missing required fields"}`
