# 中級題庫解析編輯器實作計畫

日期：2026-09-02
依據：`docs/superpowers/specs/2026-09-02-explanation-editor-design.md`

## 1. 修正題庫抽取邊界

- 在 `tools/extract_middle_questions.py` 將共用情境正文與題號提示分級，優先選擇提示前的情境正文。
- 在 `tools/validate_question_bank.py` 增加第 48～50 題固定回歸檢核與一般共用情境污染檢核。
- 重新產生 JSON、六份 CSV 與題目圖片。
- 驗證 300 題、六份試卷、圖片路徑及第 48～50 題內容。

## 2. 建立公開解析資料與安全 Markdown

- 新增空白 `site/data/explanations.json`。
- 新增共用 Markdown 渲染模組，使用專案內保存的解析器與清理器，不依賴 CDN。
- 實作 Markdown 清理、外部連結安全屬性及解析圖片顯示。
- 增加解析資料結構驗證與按題目 ID 合併。

## 3. 整合正式測驗網站

- 題庫初始化時非阻斷式載入解析檔。
- 即時練習／錯題複習：答錯展開、答對收合。
- 模擬考：交卷後在檢討區顯示解析。
- 更新非官方解析聲明、缺圖與載入錯誤處理。
- 補充解析樣式及手機版長內容／程式碼區塊排版。

## 4. 建立本機解析編輯器

- 新增 `tools/explanation-editor/server.py`，僅綁定 `127.0.0.1` 並產生工作階段權杖。
- 新增啟動器、三欄編輯器介面、搜尋／篩選、題目預覽、Markdown 編輯與即時預覽。
- 實作原子草稿保存、備份、狀態推導、圖片上傳／驗證／移除及取消發布標記。
- 將本機工作檔與草稿圖片加入 `.gitignore`。

## 5. 建立受限制的一鍵發布

- 新增發布預覽，列出新增、更新、取消發布及圖片變更。
- 發布前 fetch 遠端並拒絕落後或分歧分支。
- 僅產生及 stage `site/data/explanations.json` 和 `site/assets/explanations/`。
- 使用固定提交訊息推送 `origin/main`，回傳 commit、Actions workflow 與正式網址。
- 禁止 shell 字串拼接、路徑跳脫及未帶正確權杖／Origin 的寫入請求。

## 6. 同步 Excel 與下載檔

- 使用既有 artifact-tool builder 重新產生整合 Excel。
- 保留九個工作表、表格、欄寬、凍結窗格、驗證及資料檢核樣式。
- 複製更新後 Excel 至 `site/data/`。
- 檢查關鍵範圍、公式錯誤，並渲染九張工作表預覽做視覺 QA。

## 7. 測試與發布

- Python 單元測試：共用情境切分、本機路徑安全、草稿／審核／取消發布及公開資料編譯。
- Node 單元測試：既有測驗邏輯與解析資料合併。
- 語法檢查：所有 Python、JavaScript／MJS。
- 瀏覽器測試：離線編輯器儲存／審核／預覽、正式網站答對／答錯／模擬考及手機版。
- Git 只加入本次核准檔案，提交後推送 `main`。
- 監看 GitHub Pages 成功，驗證公開首頁、解析 JSON、圖片及 Excel URL。
