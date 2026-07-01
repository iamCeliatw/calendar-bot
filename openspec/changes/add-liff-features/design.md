## Context

calendar-bot 是以 Flask + LINE Messaging API 為基礎的行事曆助理，目前所有互動均透過文字訊息和 Flex 卡片完成。後端部署在 Cloud Run，使用 Google Cloud Tasks 排程提醒推播，Google Calendar API 讀寫行事曆。

加入 LIFF 後，系統需要同時服務兩條流量：
1. LINE Webhook（現有）：POST /callback
2. LIFF Web App API（新增）：提供 JSON 資料給 LIFF 前端頁面

LIFF 前端以靜態 HTML + Vanilla JS 實作，LIFF SDK v2.28.0，由 Flask 提供（或部署至 Cloud Storage/CDN）。

## Goals / Non-Goals

**Goals:**
- 月曆視圖、行程表單、提醒管理三個 LIFF 頁面可在 LINE 內正常開啟與操作
- 後端 JSON API 通過 LIFF Access Token 驗證使用者身份
- 行程 CRUD 完整（建立、讀取、編輯、刪除），現有 Flex 卡片加入編輯/刪除按鈕
- 提醒支援完整 CRUD：從 LIFF 頁面新增、查詢、編輯、刪除

**Non-Goals:**
- 多用戶共用日曆（Phase 3，本次不實作）
- LIFF Share Target Picker（Phase 3）
- 行動端推播通知（PWA / Push API）
- 使用 React / Vue 等前端框架

## Decisions

### D1：LIFF 頁面由 Flask 靜態服務，不分開部署

**選擇**：在現有 Flask app 新增 `/liff/<page>` 路由，直接 serve `liff/` 目錄下的 HTML 檔案。

**理由**：不需額外 CDN 或 Cloud Storage 設定，接案 demo 環境最簡單。Cloud Run 的靜態檔案大小限制不影響三個輕量頁面。

**替代方案考慮**：部署至 Firebase Hosting → 需額外帳號設定，增加 demo 準備成本。

---

### D2：後端 API 驗證使用 LIFF Access Token

**選擇**：LIFF 前端呼叫 `liff.getAccessToken()` 取得 short-lived access token，每次 API 請求帶入 `Authorization: Bearer <token>`；Flask 後端呼叫 `GET https://api.line.me/v2/profile` 驗證 token 並取得 userId，再比對白名單。

**理由**：
- LIFF Access Token 有效 12 小時，足夠一次操作週期
- 不需自建 session 或 JWT，LINE 官方驗證是標準做法
- 現有白名單機制（`LINE_USER_IDS`）可直接沿用

**替代方案考慮**：使用 ID Token（JWT）→ 需在後端驗證簽章，實作較複雜；LIFF token 驗證更直接。

---

### D3：提醒元數據另存 JSON 檔（reminders.json）

**選擇**：建立提醒 Cloud Task 時，同步將 `{task_name, user_id, remind_at, reminder_text, recurring}` 寫入 `reminders.json`（持久化至 Cloud Run Volume 或 Cloud Storage）；取消提醒時從 Cloud Tasks 刪除任務並移除記錄；**編輯提醒時採用「刪除舊 Task → 建立新 Task → 替換 JSON 記錄」三步驟**，因 Cloud Tasks 不支援原地更新。

**理由**：Cloud Tasks API 本身不提供「列出屬於特定 user 的 tasks」功能（只能 list 整個 queue），需要 side-car 儲存。本專案規模輕量，JSON 檔優於引入 Firestore 等額外依賴。

**替代方案考慮**：Firestore → 查詢能力強但增加一個 GCP 服務依賴；直接 list Cloud Tasks queue → API 有每秒 quota 限制且無法過濾 user。

**風險**：Cloud Run 本身是 stateless，JSON 檔需掛載 Cloud Run Volume（需設定）。Demo 環境可先用本地檔案，正式上線補 Volume 掛載。

---

### D4：行程 Flex 卡片加入按鈕使用 URIAction + LIFF URL

**選擇**：「編輯」按鈕使用 `URIAction(uri=f"https://liff.line.me/{LIFF_FORM_ID}?event_id={event_id}")`，「刪除」按鈕使用 PostbackAction（直接在對話中確認刪除，不透過 LIFF）。

**理由**：
- 編輯需要表單介面，LIFF 最合適
- 刪除是一次性操作，在對話中 Postback 確認比開 LIFF 頁面更快
- 分開處理符合最小介面原則

---

### D5：calendar_service 補充 update_event / delete_event

**選擇**：在現有 `calendar_service.py` 中新增兩個函數：
- `update_event(event_id, summary, start, end, timezone_str, location)`
- `delete_event(event_id)`

使用 Google Calendar API `events().patch()` 和 `events().delete()`。

**理由**：維持現有架構一致性，不引入新模組。

## Risks / Trade-offs

| 風險 | 緩解措施 |
|---|---|
| LIFF Access Token 驗證每次都需呼叫 LINE API，增加延遲 | 在同一請求中快取驗證結果（request-scope），可加 simple TTL cache |
| reminders.json 在多 instance Cloud Run 下可能不一致 | Demo 環境 min-instance=1；正式上線改用 Cloud Storage JSON 或 Firestore |
| LIFF 頁面在外部瀏覽器（非 LINE 內）需先執行 `liff.login()` | 用 `liff.isInClient()` 檢查，外部瀏覽器自動導向 login |
| 刪除事件後 Flex 卡片仍在對話中，按鈕會失效 | 刪除成功後在對話回覆一則「行程已刪除」訊息（透過 `liff.sendMessages`）|
| Google Calendar event_id 暴露在 LIFF URL 中 | 非敏感資料（event_id 是不可猜測的隨機字串），LIFF URL 本身需登入，風險可接受 |

## Migration Plan

1. 建立 LIFF App（透過 LINE Developers Console 或 Server API），記錄三個 LIFF ID
2. 在 Cloud Run 環境變數加入 `LIFF_CALENDAR_ID`, `LIFF_FORM_ID`, `LIFF_REMINDER_ID`
3. 部署更新後的 Flask app（含新路由與 LIFF HTML）
4. 測試：從 LINE 點選「查看月曆」按鈕，確認 LIFF 頁面正常開啟與資料呈現
5. 測試：建立行程後點「編輯」，確認 LIFF 表單帶入正確資料

**Rollback**：移除 Flex 卡片中的 LIFF 按鈕（`line_service.py` 改回舊版），LIFF 頁面路由對主流程無影響，可獨立移除。

## Open Questions

- `reminders.json` 的持久化方案：Demo 用本地掛載檔案 OK，但若要多人接案交付，需確認客戶 GCP 環境支援 Cloud Run Volume 或改 Cloud Storage
- LIFF App 的 scope 設定：需要 `profile`（取得 userId）和 `chat_message.write`（sendMessages），是否還需要 `openid`？（目前不需要 email，暫不申請）
