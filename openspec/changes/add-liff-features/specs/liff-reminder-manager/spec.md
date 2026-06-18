## ADDED Requirements

### Requirement: 提醒元數據持久化至 reminders.json
系統 SHALL 在每次成功建立 Cloud Task 後，將提醒記錄（`task_name`, `user_id`, `remind_at`, `reminder_text`, `recurring`, `day_of_month`, `remind_time`）以 JSON 格式 append 至 `reminders.json`（路徑由環境變數 `REMINDERS_FILE` 控制，預設 `data/reminders.json`）。

#### Scenario: 建立一次性提醒後記錄寫入
- **WHEN** 使用者確認建立一次性提醒，Cloud Task 成功建立
- **THEN** `reminders.json` 新增一筆記錄，包含 task_name、user_id、remind_at、reminder_text、recurring=false

#### Scenario: 建立月繳提醒後記錄寫入
- **WHEN** 使用者確認建立卡費提醒，每張卡各建立一個 Cloud Task
- **THEN** `reminders.json` 為每張卡新增一筆記錄，recurring=true

#### Scenario: 到點後自動重排的提醒更新記錄
- **WHEN** `/tasks/reminder` 收到到期提醒並觸發下月自動重排
- **THEN** 舊記錄被移除，新的下月提醒記錄寫入

---

### Requirement: LIFF 提醒管理頁面顯示待發提醒清單
系統 SHALL 在 `liff/reminder-manager.html` 初始化後，呼叫 `GET /api/reminders` 取得當前使用者的待發提醒清單並顯示，每筆顯示時間、內容、是否為月繳循環提醒。

#### Scenario: 成功顯示待發提醒
- **WHEN** 頁面初始化完成且使用者有待發提醒
- **THEN** 頁面顯示提醒列表，每筆包含日期時間、內容文字、循環標籤（若適用）

#### Scenario: 無待發提醒時顯示空白提示
- **WHEN** 後端回傳空陣列
- **THEN** 頁面顯示「目前沒有排定的提醒」

---

### Requirement: 後端提供提醒清單 API
系統 SHALL 實作 `GET /api/reminders`，從 `reminders.json` 讀取並過濾出屬於當前已驗證使用者（userId）的記錄，回傳 JSON 陣列，按 `remind_at` 升序排列，只回傳尚未到期的提醒（`remind_at > now`）。

#### Scenario: 成功取得待發提醒
- **WHEN** 合法使用者呼叫 `GET /api/reminders`
- **THEN** 回傳 `[{"task_name": "...", "remind_at": "...", "reminder_text": "...", "recurring": false}]` HTTP 200

#### Scenario: 過期提醒不出現在清單
- **WHEN** reminders.json 中有 `remind_at` 早於現在的記錄
- **THEN** 這些記錄不出現在 API 回應中

---

### Requirement: LIFF 提醒管理頁面支援新增提醒
系統 SHALL 在 `liff/reminder-manager.html` 提供「＋ 新增提醒」按鈕，點擊後展開內嵌表單，欄位包含：提醒日期（date input）、提醒時間（time input）、提醒內容（textarea，必填）。提交後呼叫 `POST /api/reminders`，成功後新記錄出現在清單頂端。

#### Scenario: 成功新增一次性提醒
- **WHEN** 使用者填寫日期、時間、內容後點擊「確認新增」
- **THEN** 前端呼叫 `POST /api/reminders`，成功後表單收起，新提醒出現在清單中

#### Scenario: 提醒時間為過去時間時阻擋提交
- **WHEN** 使用者設定的日期時間早於現在
- **THEN** 表單顯示「不能設定過去時間」，阻擋送出

#### Scenario: 提醒內容為空時阻擋提交
- **WHEN** 使用者未填寫提醒內容
- **THEN** 表單顯示「請輸入提醒內容」，阻擋送出

---

### Requirement: 後端提供提醒新增 API
系統 SHALL 實作 `POST /api/reminders`，接受 JSON body `{remind_at, reminder_text}`，建立 Cloud Task 並寫入 `reminders.json`，回傳 HTTP 201 與新記錄。

#### Scenario: 成功建立提醒
- **WHEN** 合法請求帶有有效的 `remind_at`（未來時間）與非空 `reminder_text`
- **THEN** Cloud Task 成功建立，reminders.json 新增記錄，回傳 `{"task_name": "...", "remind_at": "...", "reminder_text": "..."}` HTTP 201

#### Scenario: remind_at 為過去時間
- **WHEN** `remind_at` 早於目前時間
- **THEN** 系統回傳 HTTP 400 `{"error": "remind_at must be in the future"}`

#### Scenario: 缺少必要欄位
- **WHEN** body 缺少 `remind_at` 或 `reminder_text`
- **THEN** 系統回傳 HTTP 400 `{"error": "missing required fields"}`

---

### Requirement: LIFF 提醒管理頁面支援編輯提醒
系統 SHALL 在每筆提醒旁提供「✏️ 編輯」按鈕，點擊後展開內嵌編輯表單（預填現有日期、時間、內容），提交後呼叫 `PUT /api/reminders/<task_name_encoded>`，成功後列表更新對應記錄。

#### Scenario: 成功開啟編輯表單並預填資料
- **WHEN** 使用者點擊某筆提醒的「✏️ 編輯」按鈕
- **THEN** 該筆記錄下方展開表單，日期、時間、內容欄位帶入現有值

#### Scenario: 成功更新提醒時間
- **WHEN** 使用者修改時間後點擊「確認修改」
- **THEN** 前端呼叫 `PUT /api/reminders/<task_name>`，成功後列表中對應記錄更新為新時間，表單收起

#### Scenario: 更新時間為過去時間時阻擋提交
- **WHEN** 使用者輸入過去的時間後點擊「確認修改」
- **THEN** 表單顯示「不能設定過去時間」，阻擋送出

---

### Requirement: 後端提供提醒更新 API
系統 SHALL 實作 `PUT /api/reminders/<task_name_encoded>`，以「刪除舊 Cloud Task → 建立新 Cloud Task → 更新 reminders.json 記錄」的流程完成更新，回傳 HTTP 200 與更新後記錄。

#### Scenario: 成功更新提醒
- **WHEN** 合法請求帶有有效的 `remind_at`（未來時間）與 `reminder_text`
- **THEN** 舊 Cloud Task 刪除，新 Cloud Task 建立，reminders.json 記錄替換，回傳 `{"task_name": "...", "remind_at": "...", "reminder_text": "..."}` HTTP 200

#### Scenario: task_name 不屬於當前使用者
- **WHEN** 請求的 task_name 在 reminders.json 中屬於不同 user_id
- **THEN** 系統回傳 HTTP 403 `{"error": "Forbidden"}`

#### Scenario: 舊 Cloud Task 已執行（DELETE 回傳 404）仍繼續建立新任務
- **WHEN** 舊 task 已到期執行，Cloud Tasks DELETE 回傳 404
- **THEN** 系統忽略 404，繼續建立新 Cloud Task 並更新記錄，回傳 HTTP 200

---

### Requirement: LIFF 提醒管理頁面支援取消提醒
系統 SHALL 在每筆提醒旁提供「取消」按鈕，點擊後呼叫 `DELETE /api/reminders/<task_name>` 刪除 Cloud Task 並從 `reminders.json` 移除記錄。

#### Scenario: 成功取消一次性提醒
- **WHEN** 使用者點擊某筆提醒的「取消」按鈕，確認後送出 DELETE 請求
- **THEN** Cloud Task 被刪除，reminders.json 中對應記錄被移除，列表重新整理

#### Scenario: 取消月繳循環提醒
- **WHEN** 使用者取消一筆 recurring=true 的提醒
- **THEN** 當前排定的 Cloud Task 被刪除，記錄移除；下月不再自動重排（因記錄已消失）

#### Scenario: Cloud Task 已被自動執行（task 不存在）
- **WHEN** 使用者嘗試取消一個已到期執行的 task
- **THEN** Cloud Tasks DELETE 回傳 404，系統仍從 reminders.json 移除記錄，回傳 HTTP 200（冪等處理）

---

### Requirement: 後端提供取消提醒 API
系統 SHALL 實作 `DELETE /api/reminders/<task_name_encoded>`，呼叫 Cloud Tasks `delete_task()` 刪除指定任務（404 時忽略），並從 `reminders.json` 移除對應記錄，回傳 HTTP 200。

#### Scenario: 成功取消提醒任務
- **WHEN** 合法請求帶有有效的 task_name（URL encoded）
- **THEN** Cloud Task 被刪除，記錄從 reminders.json 移除，回傳 `{"status": "cancelled"}` HTTP 200

#### Scenario: task_name 不屬於當前使用者
- **WHEN** 請求的 task_name 在 reminders.json 中屬於不同 user_id
- **THEN** 系統回傳 HTTP 403 `{"error": "Forbidden"}`
