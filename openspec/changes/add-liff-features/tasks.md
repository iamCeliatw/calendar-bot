## 1. LIFF App 設定與後端基礎建設

- [ ] 1.1 在 LINE Developers Console（或 LIFF Server API）建立三個 LIFF App：月曆（full）、行程表單（full）、提醒管理（tall），記錄各自 liffId
- [x] 1.2 在 `.env` 與 Cloud Run 環境變數加入 `LIFF_CALENDAR_ID`、`LIFF_FORM_ID`、`LIFF_REMINDER_ID`
- [x] 1.3 在 `webhook_app.py` 新增 `/liff/<page>` 路由，serve `liff/` 目錄下的靜態 HTML；不存在的 page 回傳 404
- [x] 1.4 實作 `_verify_liff_token(auth_header)` helper，呼叫 `GET https://api.line.me/v2/profile` 驗證 Access Token，回傳 userId 或拋出 401/403
- [x] 1.5 實作 `@require_liff_auth` Flask decorator，包裝所有 `/api/*` 路由的 token 驗證邏輯
- [x] 1.6 建立 `liff/` 目錄與三個空白 HTML 骨架（含 LIFF SDK script tag `https://static.line-scdn.net/liff/edge/2/sdk.js`）

## 2. Google Calendar CRUD 擴充

- [x] 2.1 在 `calendar_service.py` 新增 `get_event(event_id)` 函數，呼叫 `events().get()` 回傳單一事件 dict
- [x] 2.2 在 `calendar_service.py` 新增 `update_event(event_id, summary, start, end, timezone_str, location)` 函數，呼叫 `events().patch()`
- [x] 2.3 在 `calendar_service.py` 新增 `delete_event(event_id)` 函數，呼叫 `events().delete()`
- [x] 2.4 在 `webhook_app.py` 新增 `POST /api/events` endpoint，解析 JSON body 並呼叫 `create_timed_event` 或 `create_all_day_event`，回傳 201
- [x] 2.5 在 `webhook_app.py` 新增 `GET /api/events` endpoint（含 year/month 參數），呼叫 `get_events_for_days` 回傳月行程 JSON
- [x] 2.6 在 `webhook_app.py` 新增 `GET /api/events/<event_id>` endpoint，回傳單一行程資料
- [x] 2.7 在 `webhook_app.py` 新增 `PUT /api/events/<event_id>` endpoint，呼叫 `update_event`，回傳 200
- [x] 2.8 在 `webhook_app.py` 新增 `DELETE /api/events/<event_id>` endpoint，呼叫 `delete_event`，回傳 204

## 3. Flex 卡片加入編輯 / 刪除按鈕

- [x] 3.1 在 `line_service.py` 的 `build_event_list_flex` 每個事件 row 加入「✏️ 編輯」`URIAction`（僅 `LIFF_FORM_ID` 有設定時）和「🗑 刪除」`PostbackAction(data=f"delete_event:{event_id}")`
- [x] 3.2 在 `line_service.py` 的 `build_success_flex` 加入「✏️ 編輯」按鈕（同上條件）
- [x] 3.3 在 `webhook_app.py` `_on_postback` 新增 `delete_event:` 前綴處理：回覆確認 Flex 卡片（「確認刪除」/「取消」按鈕）
- [x] 3.4 在 `webhook_app.py` `_on_postback` 新增 `delete_confirm:` 前綴處理：呼叫 `calendar_service.delete_event`，成功回覆「🗑 行程已刪除」

## 4. 提醒元數據持久化

- [x] 4.1 建立 `reminder_store.py`：實作 `append_reminder(record)`、`remove_reminder(task_name)`、`update_reminder(task_name, new_record)`、`list_reminders(user_id)` 四個函數，讀寫 `data/reminders.json`（路徑由 `REMINDERS_FILE` env var 控制）；所有寫入操作需 file lock 避免並發覆寫
- [x] 4.2 在 `webhook_app.py` 的 `_create_reminder_task` 成功後呼叫 `reminder_store.append_reminder` 寫入記錄
- [x] 4.3 在 `webhook_app.py` `/tasks/reminder` 自動重排邏輯中：移除舊記錄、寫入新記錄
- [x] 4.4 在 `webhook_app.py` 新增 `GET /api/reminders` endpoint，呼叫 `reminder_store.list_reminders(user_id)` 過濾未到期記錄，回傳 200
- [x] 4.5 在 `webhook_app.py` 新增 `POST /api/reminders` endpoint：驗證 `remind_at` 為未來時間，呼叫 `_create_reminder_task`，再呼叫 `reminder_store.append_reminder`，回傳 201
- [x] 4.6 在 `webhook_app.py` 新增 `PUT /api/reminders/<task_name_encoded>` endpoint：刪除舊 Cloud Task（404 時忽略）→ 建立新 Cloud Task → `reminder_store.update_reminder`，回傳 200
- [x] 4.7 在 `webhook_app.py` 新增 `DELETE /api/reminders/<task_name_encoded>` endpoint：呼叫 Cloud Tasks `delete_task()`（404 時忽略），再呼叫 `reminder_store.remove_reminder`，回傳 200

## 5. LIFF 月曆視圖前端

- [x] 5.1 實作 `liff/calendar.html`：`liff.init()` → 取得 Access Token → 呼叫 `GET /api/events?year=&month=`
- [x] 5.2 實作月曆格狀佈局（7 欄 CSS Grid），根據回傳行程在對應日期格顯示標題（截斷 8 字，超過 2 筆顯示「+N」）
- [x] 5.3 實作點擊日期格展開當日行程清單（時間 badge + 標題 + 地點）
- [x] 5.4 實作上一月 / 下一月切換按鈕，切換時重新呼叫 API
- [x] 5.5 加入右下角「＋」浮動按鈕，`liff.openWindow({ url: LIFF_FORM_URL })` 開啟行程表單
- [x] 5.6 實作外部瀏覽器 login 流程：`liff.isLoggedIn()` 為 false 時執行 `liff.login()`

## 6. LIFF 行程表單前端

- [x] 6.1 實作 `liff/event-form.html`：`liff.init()` 後偵測 URL `?event_id=`，有則呼叫 `GET /api/events/<id>` 預填表單
- [x] 6.2 實作表單欄位：標題（text）、日期（date input）、全天切換（checkbox）、開始時間（time input）、結束時間（time input）、地點（text）
- [x] 6.3 實作全天開關：勾選後隱藏時間欄位
- [x] 6.4 實作表單驗證：標題必填、結束時間須晚於開始時間
- [x] 6.5 實作新增提交：呼叫 `POST /api/events`，成功後 `liff.sendMessages` 發送成功訊息，`liff.closeWindow()`
- [x] 6.6 實作編輯提交：呼叫 `PUT /api/events/<event_id>`，成功後 `liff.sendMessages` 發送更新確認訊息，`liff.closeWindow()`

## 7. LIFF 提醒管理前端（完整 CRUD）

- [x] 7.1 實作 `liff/reminder-manager.html`：`liff.init()` 後呼叫 `GET /api/reminders` 取得待發提醒清單
- [x] 7.2 渲染提醒列表：顯示日期時間、提醒內容、循環標籤（月繳）；無提醒時顯示「目前沒有排定的提醒」
- [x] 7.3 實作「＋ 新增提醒」按鈕：點擊後展開內嵌表單（日期 date input、時間 time input、內容 textarea）
- [x] 7.4 實作新增表單驗證：內容必填、時間不可為過去；提交呼叫 `POST /api/reminders`，成功後新記錄插入清單頂端，表單收起
- [x] 7.5 每筆提醒加入「✏️ 編輯」按鈕：點擊後在該筆記錄下方展開內嵌編輯表單，預填現有日期、時間、內容
- [x] 7.6 實作編輯表單驗證（同新增）；提交呼叫 `PUT /api/reminders/<task_name>`，成功後列表原地更新該記錄，表單收起
- [x] 7.7 每筆提醒加入「取消」按鈕，點擊後 inline 二次確認，確認後呼叫 `DELETE /api/reminders/<task_name>`
- [x] 7.8 取消成功後從列表移除該筆記錄（不重新整理整頁）；同一時間只允許一個表單展開（開另一個時自動收起前一個）

## 8. 整合測試與部署

- [ ] 8.1 在本機用 ngrok 測試：從 LINE 點選「查看月曆」確認 LIFF 頁面正常開啟
- [ ] 8.2 測試行程編輯：點「✏️ 編輯」→ LIFF 表單帶入現有資料 → 更新 → LINE 對話收到確認訊息
- [ ] 8.3 測試行程刪除：點「🗑 刪除」→ 確認 Postback → LINE 對話回覆「行程已刪除」
- [ ] 8.4 測試提醒管理 CRUD：從 LIFF 新增提醒 → 確認出現 → 點編輯修改時間 → 確認更新 → 點取消 → 確認消失
- [ ] 8.5 更新 Cloud Run 環境變數（三個 LIFF ID）並重新部署
- [ ] 8.6 更新 `README.md` 或 LIFF 設定說明文件（LIFF App 建立步驟、環境變數清單）
