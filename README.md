# AI 應用規劃師中級題庫

以官方歷屆試題整理成的靜態自我測驗網站。目前收錄 114 年第 2 次與 115 年第 1 次中級試題，三科合計 300 題。

## 功能

- 立即練習：隨機題序與選項，作答後立即顯示正確答案。
- 模擬考試：50 題、90 分鐘，保留官方題序與選項順序。
- 錯題複習：錯題連續答對兩次後自動移出。
- 本機紀錄：使用 `localStorage`，可匯出／匯入 JSON 備份。
- 公開資料：提供完整 JSON、六份分科 CSV 與整合 Excel。
- 圖片題：圖片與題庫一起部署，不依賴外部圖床。
- 非官方解析：安全 Markdown、解析圖片，以及草稿／審核／發布流程。

## 離線解析編輯器

解析編輯器只在自己的電腦執行，不會部署到 GitHub Pages；公開網站訪客只能閱讀已發布的解析，無法修改內容。

1. 雙擊 `tools/explanation-editor/啟動解析編輯器.cmd`。
2. 在左側搜尋題目，於右側輸入 Markdown 解析；內容會自動存到被 Git 忽略的 `local-data/`。
3. 可拖放、貼上或選擇 PNG、JPEG、WebP 圖片。圖片會先保存在本機，預覽時不需要外部圖床。
4. 完成後按「標記已審核」。只有已審核解析會進入發布預覽。
5. 按右上角「發布已審核解析」，確認清單後才會提交並推送解析 JSON 與圖片。

啟動器只監聽 `127.0.0.1` 並使用每次隨機工作階段權杖。發布功能沿用電腦現有的 Git/GitHub 登入狀態，不會要求在網頁輸入 GitHub Token。若本機分支落後或與遠端分歧，發布會停止並顯示原因。

## 本機預覽

在專案根目錄執行：

```powershell
python -m http.server 4173 --directory site
```

再開啟 `http://127.0.0.1:4173/`。請勿直接雙擊 `index.html`，瀏覽器可能阻擋本機載入 JSON。

## 重新產生題庫

原始 PDF 放在 `中級/`。在專案根目錄執行：

```powershell
python tools/extract_middle_questions.py
python tools/validate_question_bank.py
```

產物位於 `site/data/` 與 `site/assets/questions/`。Excel 成品另存於 `outputs/`，並複製到 `site/data/` 供網站下載。

## 測試

```powershell
node --test tests/quiz-engine.test.mjs
node --check site/js/app.mjs
node --check site/js/quiz-engine.mjs
node --check site/js/storage.mjs
node --check site/js/explanation-data.mjs
node --check site/js/markdown.mjs
python -m unittest tests/test_explanation_editor.py
python tools/validate_question_bank.py
```

## 發布到 GitHub Pages

1. 建立 GitHub repository，將本專案推送到 `main` 分支。
2. 在 repository 的 **Settings → Pages**，將 Source 設為 **GitHub Actions**。
3. `.github/workflows/pages.yml` 會把 `site/` 發布為靜態網站。

網站是非官方自我練習工具；題目與答案來源為官方公告試題，解析內容則為非官方整理。
