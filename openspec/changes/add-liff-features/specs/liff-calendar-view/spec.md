## ADDED Requirements

### Requirement: LIFF 月曆視圖頁面初始化
系統 SHALL 在 `liff/calendar.html` 頁面載入時執行 `liff.init({ liffId: LIFF_CALENDAR_ID })`，完成後取得 Access Token 並呼叫後端 `/api/events?year=YYYY&month=MM` 取得當月行程。

#### Scenario: 在 LINE 內瀏覽器成功初始化
- **WHEN** 使用者在 LINE 內點選「查看月曆」觸發 LIFF URL
- **THEN** `liff.init()` 成功，頁面取得 Access Token，呼叫後端 API 並顯示月曆

#### Scenario: 在外部瀏覽器未登入時導向 LINE Login
- **WHEN** 使用者在外部瀏覽器開啟 LIFF URL 且未登入
- **THEN** `liff.isLoggedIn()` 回傳 false，頁面自動執行 `liff.login()`

#### Scenario: 後端 API 呼叫失敗顯示錯誤提示
- **WHEN** 後端 `/api/events` 回傳非 200 狀態
- **THEN** 頁面顯示「無法載入行程，請稍後再試」

---

### Requirement: 後端提供月行程 JSON API
系統 SHALL 實作 `GET /api/events?year=YYYY&month=MM` endpoint，回傳指定月份的所有 Google Calendar 行程，格式為 JSON 陣列。

#### Scenario: 成功取得當月行程
- **WHEN** 合法請求帶有 `year=2026&month=6`
- **THEN** 系統回傳 `[{"event_id": "...", "summary": "...", "start": "...", "end": "...", "is_all_day": false, "location": "..."}]`

#### Scenario: 指定月份無行程
- **WHEN** 合法請求但該月無任何行程
- **THEN** 系統回傳空陣列 `[]`，HTTP 200

#### Scenario: 缺少 year 或 month 參數
- **WHEN** 請求缺少 `year` 或 `month` 參數
- **THEN** 系統使用當下年月作為預設值

---

### Requirement: 月曆視圖顯示行程格狀佈局
系統 SHALL 以月曆格式（7 欄）顯示行程，每個有行程的日期格顯示行程名稱（最多 2 筆，超過顯示「+N」），點擊日期格展開當日行程列表。

#### Scenario: 有行程的日期格顯示行程
- **WHEN** 月曆渲染完成，某日有 1 筆行程
- **THEN** 該日期格顯示行程名稱（截斷超過 8 字的標題）

#### Scenario: 超過 2 筆行程顯示摘要
- **WHEN** 某日有 3 筆行程
- **THEN** 日期格顯示前 2 筆標題 + 「+1」

#### Scenario: 點擊日期格展開當日清單
- **WHEN** 使用者點擊有行程的日期格
- **THEN** 頁面下方滑出當日行程清單，包含時間、名稱、地點

---

### Requirement: 月曆視圖支援月份切換
系統 SHALL 提供上一月 / 下一月切換按鈕，切換後重新呼叫後端 API 取得對應月份資料。

#### Scenario: 切換至下個月
- **WHEN** 使用者點擊「▶」按鈕
- **THEN** 月曆切換至下個月，發送新的 `/api/events` 請求並更新顯示

#### Scenario: 點選「新增行程」按鈕
- **WHEN** 使用者點擊月曆頁面右下角的「＋」浮動按鈕
- **THEN** 使用 `liff.openWindow({ url: LIFF_FORM_URL, external: false })` 開啟行程表單頁面
