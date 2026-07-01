## Why

calendar-bot 目前只提供文字對話與 Flex 卡片互動，缺乏視覺化介面，在接案 demo 時說服力不足。加入 LIFF（LINE Front-end Framework）後，可在 LINE 對話中直接開啟完整 Web App，讓客戶直觀感受「LINE Bot + 行事曆 App」的完整體驗，大幅提升提案成功率。

## What Changes

- 新增 LIFF Server API 整合（使用 `POST /liff/v1/apps` 註冊 LIFF App，`GET/PUT/DELETE /liff/v1/apps/{liffId}` 管理）
- 新增 LIFF 月曆視圖頁面：在 LINE 內開啟月曆 Web App，顯示 Google Calendar 事件
- 新增 LIFF 行程新增表單：一頁式表單取代多步驟 Wizard，支援日期選擇、時間、地點
- 新增行程編輯與刪除：Flex 卡片加入「編輯」「刪除」按鈕，開啟 LIFF 表單帶入現有資料
- 新增 LIFF 提醒管理頁面：列出進行中的提醒，支援取消
- 新增後端 REST API：Flask 新增提供行事曆資料的 JSON endpoints，供 LIFF 前端呼叫
- LIFF 前端採用 Vanilla JS + LIFF SDK v2.28.0，不引入大型框架，降低接案維護成本

## Capabilities

### New Capabilities

- `liff-app-setup`: 在 LINE Login Channel 上以 LIFF Server API 建立與管理 LIFF App 設定，並整合到 Flask webhook 後端
- `liff-calendar-view`: LIFF 月曆視圖，使用 liff.init + liff.getProfile 取得身份，呼叫後端 API 顯示 Google Calendar 月曆
- `liff-event-form`: LIFF 行程新增／編輯表單，使用 liff.sendMessages 在完成後推送確認訊息回對話，取代 Wizard 精靈流程
- `event-crud`: Google Calendar 事件的完整 CRUD，補齊現有缺少的 update / delete 操作；Flex 卡片加入對應按鈕
- `liff-reminder-manager`: LIFF 提醒管理頁面，支援提醒的完整 CRUD（從 LIFF UI 新增、查詢、編輯時間/內容、取消）；編輯採「刪除舊 Task → 建立新 Task」流程

### Modified Capabilities

<!-- 現有 specs 為空，無需列出 -->

## Impact

- **後端（Flask / webhook_app.py）**：新增 `/api/events`（GET 月行程）、`/api/events/<id>`（PUT/DELETE）、`/api/reminders`（GET 清單 / DELETE 取消）等 JSON endpoints；需加入 LIFF token 驗證（用 liff.getAccessToken() 取得 access token 並向 LINE 驗證身份）
- **calendar_service.py**：補充 `update_event()` 與 `delete_event()` 方法
- **line_service.py**：為現有行程 Flex 卡片加入「編輯」與「刪除」按鈕（URIAction 帶 LIFF URL + event_id 參數）
- **新增 liff/ 前端目錄**：`calendar.html`、`event-form.html`、`reminder-manager.html`，各自引入 LIFF SDK
- **環境變數**：新增 `LIFF_CALENDAR_ID`、`LIFF_FORM_ID`、`LIFF_REMINDER_ID`（LIFF App IDs）
- **依賴**：無新增 Python 套件；前端純靜態 HTML+JS，由 Flask 提供或部署至 Cloud Storage
