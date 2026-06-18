## ADDED Requirements

### Requirement: LIFF App 在 LINE Login Channel 上完成註冊
系統 SHALL 透過 LINE LIFF Server API（`POST /liff/v1/apps`）或 LINE Developers Console 建立三個 LIFF App（月曆視圖、行程表單、提醒管理），並將各自的 `liffId` 儲存為環境變數。

#### Scenario: 三個 LIFF App 均成功建立
- **WHEN** 開發者執行 LIFF 設定腳本或在 Console 手動建立
- **THEN** 系統取得 `LIFF_CALENDAR_ID`、`LIFF_FORM_ID`、`LIFF_REMINDER_ID` 三個 liffId
- **THEN** 三個 App 的 view type 分別為 `full`、`full`、`tall`

#### Scenario: 環境變數未設定時啟動警告
- **WHEN** Flask app 啟動時 `LIFF_CALENDAR_ID` 或 `LIFF_FORM_ID` 或 `LIFF_REMINDER_ID` 任一未設定
- **THEN** 系統印出 WARNING 訊息但不中止啟動（LIFF 功能降級，Flex 卡片不顯示 LIFF 按鈕）

---

### Requirement: Flask 提供 LIFF 靜態頁面服務
系統 SHALL 在 Flask app 中新增 `/liff/<page>` 路由，serve `liff/` 目錄下對應的 HTML 靜態頁面。

#### Scenario: 成功取得月曆頁面
- **WHEN** 使用者（或 LINE 內嵌瀏覽器）發送 `GET /liff/calendar`
- **THEN** 系統回傳 `liff/calendar.html`，HTTP 200

#### Scenario: 成功取得行程表單頁面
- **WHEN** 使用者發送 `GET /liff/event-form`
- **THEN** 系統回傳 `liff/event-form.html`，HTTP 200

#### Scenario: 成功取得提醒管理頁面
- **WHEN** 使用者發送 `GET /liff/reminder-manager`
- **THEN** 系統回傳 `liff/reminder-manager.html`，HTTP 200

#### Scenario: 不存在的頁面回傳 404
- **WHEN** 使用者發送 `GET /liff/unknown-page`
- **THEN** 系統回傳 HTTP 404

---

### Requirement: 後端 API 驗證 LIFF Access Token
系統 SHALL 對所有 `/api/*` 路由驗證請求的 `Authorization: Bearer <token>` 標頭，呼叫 `GET https://api.line.me/v2/profile` 確認 token 有效並取得 userId，再比對 `LINE_USER_IDS` 白名單。

#### Scenario: 合法 token 通過驗證
- **WHEN** LIFF 前端帶有效 Access Token 呼叫 `/api/events`
- **THEN** 後端驗證成功，回傳 HTTP 200 與行程資料

#### Scenario: 缺少或無效 token 拒絕請求
- **WHEN** 請求未帶 Authorization 標頭，或 token 已過期
- **THEN** 後端回傳 HTTP 401 `{"error": "Unauthorized"}`

#### Scenario: userId 不在白名單
- **WHEN** token 有效但對應 userId 不在 `LINE_USER_IDS`
- **THEN** 後端回傳 HTTP 403 `{"error": "Forbidden"}`
