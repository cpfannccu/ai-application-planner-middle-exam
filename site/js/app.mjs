import {
  MODE,
  answerText,
  createSession,
  formatDuration,
  isCorrect,
  paperKey,
  scoreSession,
  selectQuestions,
  shuffle,
} from "./quiz-engine.mjs";
import {
  downloadRecords,
  loadRecords,
  parseImportedRecords,
  saveRecords,
  updateMistake,
} from "./storage.mjs";
import { attachExplanations, parsePublicExplanations } from "./explanation-data.mjs";
import { createMarkdownElement } from "./markdown.mjs";

const app = document.getElementById("app");
const importInput = document.getElementById("record-import");

const MODE_LABEL = {
  [MODE.PRACTICE]: "即時練習",
  [MODE.EXAM]: "模擬考試",
  [MODE.MISTAKES]: "錯題複習",
};

const state = {
  bank: null,
  questionById: new Map(),
  records: null,
  storageWarning: "",
  explanationWarning: "",
  session: null,
  lastResult: null,
  timerId: null,
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function stopTimer() {
  if (state.timerId) window.clearInterval(state.timerId);
  state.timerId = null;
}

function persist() {
  const warning = saveRecords(state.records);
  if (warning) state.storageWarning = warning;
}

function formatDate(timestamp) {
  return new Intl.DateTimeFormat("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function createExplanationDetails(question, expanded = false) {
  const explanation = question.explanation;
  if (!explanation) return null;

  const details = document.createElement("details");
  details.className = "explanation-card";
  details.open = expanded;

  const summary = document.createElement("summary");
  summary.textContent = "查看非官方解析";
  details.append(summary);

  const body = document.createElement("div");
  body.className = "explanation-body";
  body.append(createMarkdownElement(explanation.markdown));

  if (explanation.images.length) {
    const gallery = document.createElement("div");
    gallery.className = "explanation-images";
    for (const [index, path] of explanation.images.entries()) {
      const image = document.createElement("img");
      image.className = "explanation-image";
      image.src = `./${path}`;
      image.alt = `題目 ${question.question_number} 解析圖片 ${index + 1}`;
      image.loading = "lazy";
      image.addEventListener("error", () => {
        const error = document.createElement("div");
        error.className = "image-error";
        error.textContent = `解析圖片載入失敗：${path}`;
        image.replaceWith(error);
      });
      gallery.append(image);
    }
    body.append(gallery);
  }

  if (explanation.updated_at) {
    const updated = document.createElement("p");
    updated.className = "explanation-updated";
    updated.textContent = `最後更新：${explanation.updated_at}`;
    body.append(updated);
  }
  details.append(body);
  return details;
}

function modeDescription(mode) {
  if (mode === MODE.PRACTICE) return "作答後立即看答案，題目與選項隨機排列。";
  if (mode === MODE.EXAM) return "50 題、90 分鐘，交卷後才公布答案。";
  return "複習本機錯題；連續答對兩次後自動移出。";
}

function renderFatal(message) {
  stopTimer();
  app.innerHTML = `
    <main class="page-shell">
      <section class="panel setup-panel">
        <h1 class="brand-title">題庫載入失敗</h1>
        <p class="error-box" role="alert">${escapeHtml(message)}</p>
        <button class="button button-primary" id="reload-page" type="button">重新載入</button>
      </section>
    </main>`;
  document.getElementById("reload-page").addEventListener("click", () => window.location.reload());
}

function validateBank(bank) {
  if (!bank || bank.schema_version !== 1 || !Array.isArray(bank.questions)) {
    throw new Error("題庫格式不正確");
  }
  if (bank.questions.length !== 300) {
    throw new Error(`題庫應有 300 題，目前讀到 ${bank.questions.length} 題`);
  }
  const ids = new Set();
  for (const question of bank.questions) {
    if (!question.id || ids.has(question.id)) throw new Error("題庫包含重複或空白 ID");
    if (!/[A-D]/.test(question.answer)) throw new Error(`${question.id} 的答案格式不正確`);
    ids.add(question.id);
  }
  return bank;
}

function paperLabel(paper) {
  return `${paper.year} 年第 ${paper.session} 次｜科目 ${paper.subject_code} ${paper.subject_name}`;
}

function renderHome() {
  stopTimer();
  state.session = null;
  const mistakes = Object.keys(state.records.mistakes).length;
  const attempts = state.records.attempt_history.length;
  const latest = state.records.attempt_history.at(-1);
  const active = state.records.active_session;

  app.innerHTML = `
    <main class="page-shell">
      <header class="site-header">
        <div>
          <h1 class="brand-title">AI 應用規劃師中級題庫</h1>
          <p class="brand-subtitle">官方歷屆試題整理｜免登入、紀錄只存在目前瀏覽器</p>
        </div>
      </header>

      ${state.storageWarning ? `<p class="warning" role="alert">${escapeHtml(state.storageWarning)}</p>` : ""}
      ${state.explanationWarning ? `<p class="warning" role="status">${escapeHtml(state.explanationWarning)}</p>` : ""}

      <div class="home-grid">
        <section class="panel setup-panel">
          <form id="quiz-setup">
            <div class="section-block">
              <h2 class="section-title">1. 選擇測驗模式</h2>
              <div class="choice-grid">
                ${[MODE.PRACTICE, MODE.EXAM, MODE.MISTAKES].map((mode, index) => `
                  <label class="choice-card">
                    <input type="radio" name="mode" value="${mode}" ${index === 0 ? "checked" : ""}>
                    <span class="choice-name">${MODE_LABEL[mode]}</span>
                    <span class="choice-description">${modeDescription(mode)}</span>
                  </label>`).join("")}
              </div>
            </div>

            <div class="section-block" id="source-section">
              <h2 class="section-title">2. 選擇題目範圍</h2>
              <div class="source-row">
                <label><input type="radio" name="source-type" value="paper" checked> 完整歷屆試卷</label>
                <label><input type="radio" name="source-type" value="random"> 依科目跨年度抽題</label>
              </div>
              <div class="field-grid">
                <div class="field" id="paper-field">
                  <label for="paper-select">歷屆試卷</label>
                  <select id="paper-select"></select>
                </div>
                <div class="field" id="subject-field" hidden>
                  <label for="subject-select">科目</label>
                  <select id="subject-select"></select>
                </div>
                <div class="field" id="count-field" hidden>
                  <label for="count-select">抽題數量</label>
                  <select id="count-select">
                    <option value="10">10 題</option>
                    <option value="20">20 題</option>
                    <option value="50">50 題</option>
                  </select>
                </div>
              </div>
            </div>

            <div class="section-block" id="mistake-section" hidden>
              <h2 class="section-title">2. 錯題範圍</h2>
              <p class="notice">目前共有 <strong>${mistakes}</strong> 題待複習。答對會累積熟練度，連續答對兩次後移出。</p>
            </div>

            <div class="button-row">
              <button class="button button-primary" id="start-quiz" type="submit">開始測驗</button>
              ${active ? '<button class="button" id="resume-quiz" type="button">繼續上次進度</button>' : ""}
            </div>
          </form>
        </section>

        <aside class="panel summary-panel">
          <h2 class="section-title">我的學習紀錄</h2>
          <div class="stat-grid">
            <div class="stat"><span class="stat-value">${attempts}</span><span class="stat-label">完成測驗</span></div>
            <div class="stat"><span class="stat-value">${mistakes}</span><span class="stat-label">目前錯題</span></div>
            <div class="stat"><span class="stat-value">${latest ? `${latest.percentage}%` : "—"}</span><span class="stat-label">最近成績</span></div>
          </div>

          <div class="button-row">
            <button class="button" id="export-records" type="button">匯出紀錄</button>
            <button class="button" id="import-records" type="button">匯入紀錄</button>
            <button class="button button-danger" id="clear-records" type="button">清除紀錄</button>
          </div>

          <div class="section-block">
            <h3 class="section-title">最近完成</h3>
            ${attempts ? `<ul class="history-list">${state.records.attempt_history.slice(-5).reverse().map((attempt) => `
              <li class="history-item">
                <span>${escapeHtml(attempt.sourceLabel)}</span>
                <span>${attempt.percentage}%</span>
              </li>`).join("")}</ul>` : '<p class="muted">尚未完成測驗。</p>'}
          </div>

          <div class="section-block download-block">
            <h3 class="section-title">下載題庫資料</h3>
            <p class="muted">可直接提供網站或試算表使用。</p>
            <div class="download-links">
              <a class="button" href="./data/questions.json" download>JSON</a>
              <a class="button" href="./data/AI應用規劃師中級題庫.xlsx" download>Excel</a>
            </div>
            <details class="csv-details">
              <summary>下載分科 CSV（6 份）</summary>
              <ul>
                <li><a href="./data/csv/114-2-subject-1.csv" download>114 年第 2 次｜科目 1</a></li>
                <li><a href="./data/csv/114-2-subject-2.csv" download>114 年第 2 次｜科目 2</a></li>
                <li><a href="./data/csv/114-2-subject-3.csv" download>114 年第 2 次｜科目 3</a></li>
                <li><a href="./data/csv/115-1-subject-1.csv" download>115 年第 1 次｜科目 1</a></li>
                <li><a href="./data/csv/115-1-subject-2.csv" download>115 年第 1 次｜科目 2</a></li>
                <li><a href="./data/csv/115-1-subject-3.csv" download>115 年第 1 次｜科目 3</a></li>
              </ul>
            </details>
          </div>
        </aside>
      </div>

      <footer class="site-footer">
        本站為非官方自我練習工具；題目與答案來源為官方公告試題，解析由本站整理並非官方內容。
      </footer>
    </main>`;

  const paperSelect = document.getElementById("paper-select");
  for (const paper of state.bank.papers) {
    const option = document.createElement("option");
    option.value = `${paper.paper_code}-S${paper.subject_code}`;
    option.textContent = paperLabel(paper);
    paperSelect.append(option);
  }

  const subjectSelect = document.getElementById("subject-select");
  const subjects = [...new Map(state.bank.questions.map((question) => [question.subject_code, question.subject_name])).entries()];
  for (const [code, name] of subjects) {
    const option = document.createElement("option");
    option.value = String(code);
    option.textContent = `科目 ${code}｜${name}`;
    subjectSelect.append(option);
  }

  const setup = document.getElementById("quiz-setup");
  const updateFields = () => {
    const mode = setup.elements.mode.value;
    const sourceType = setup.elements["source-type"].value;
    const mistakesMode = mode === MODE.MISTAKES;
    document.getElementById("source-section").hidden = mistakesMode;
    document.getElementById("mistake-section").hidden = !mistakesMode;
    document.getElementById("paper-field").hidden = sourceType !== "paper";
    document.getElementById("subject-field").hidden = sourceType !== "random";
    document.getElementById("count-field").hidden = sourceType !== "random";
    const countSelect = document.getElementById("count-select");
    if (mode === MODE.EXAM) countSelect.value = "50";
    countSelect.disabled = mode === MODE.EXAM;
  };
  setup.addEventListener("change", updateFields);
  updateFields();
  setup.addEventListener("submit", startFromForm);

  document.getElementById("resume-quiz")?.addEventListener("click", resumeSession);
  document.getElementById("export-records").addEventListener("click", () => downloadRecords(state.records));
  document.getElementById("import-records").addEventListener("click", () => importInput.click());
  document.getElementById("clear-records").addEventListener("click", clearRecords);
}

function startFromForm(event) {
  event.preventDefault();
  if (state.records.active_session && !window.confirm("開始新測驗會取代尚未完成的進度，確定繼續嗎？")) return;

  const form = event.currentTarget;
  const mode = form.elements.mode.value;
  let selectedQuestions = [];
  let source;

  if (mode === MODE.MISTAKES) {
    const mistakeIds = Object.keys(state.records.mistakes);
    selectedQuestions = shuffle(mistakeIds.map((id) => state.questionById.get(id)).filter(Boolean));
    if (!selectedQuestions.length) {
      window.alert("目前沒有錯題可複習。");
      return;
    }
    source = { type: "mistakes", label: `錯題複習（${selectedQuestions.length} 題）` };
  } else {
    const sourceType = form.elements["source-type"].value;
    const paper = document.getElementById("paper-select").value;
    const subjectCode = Number(document.getElementById("subject-select").value);
    const count = mode === MODE.EXAM ? 50 : Number(document.getElementById("count-select").value);
    selectedQuestions = selectQuestions({
      questions: state.bank.questions,
      sourceType,
      paper,
      subjectCode,
      count,
      mode,
    });
    if (mode === MODE.EXAM && selectedQuestions.length !== 50) {
      window.alert("模擬考必須取得 50 題，目前題數不足。");
      return;
    }
    if (sourceType === "paper") {
      const paperInfo = state.bank.papers.find((item) => `${item.paper_code}-S${item.subject_code}` === paper);
      source = { type: "paper", paper, label: paperInfo ? paperLabel(paperInfo) : "完整歷屆試卷" };
    } else {
      const subject = state.bank.questions.find((question) => question.subject_code === subjectCode);
      source = { type: "random", subjectCode, count, label: `${subject?.subject_name ?? "指定科目"}｜跨年度 ${count} 題` };
    }
  }

  state.session = createSession({ mode, selectedQuestions, source });
  state.records.active_session = state.session;
  persist();
  renderQuiz();
}

function resumeSession() {
  const active = state.records.active_session;
  if (!active) return;
  const missing = active.questionIds.filter((id) => !state.questionById.has(id));
  if (missing.length) {
    window.alert("上次進度引用的題目已不存在，無法續答。");
    return;
  }
  state.session = active;
  if (active.mode === MODE.EXAM && Date.now() >= active.deadline) {
    finishSession({ expired: true, askConfirmation: false });
    return;
  }
  renderQuiz();
}

function questionStatusClass(questionId, index) {
  const classes = ["palette-button"];
  if (state.session.answers[questionId]) classes.push("answered");
  if (index === state.session.currentIndex) classes.push("current");
  return classes.join(" ");
}

function renderQuiz() {
  stopTimer();
  const session = state.session;
  if (!session) return renderHome();
  session.currentIndex = Math.min(Math.max(0, session.currentIndex), session.questionIds.length - 1);
  const questionId = session.questionIds[session.currentIndex];
  const question = state.questionById.get(questionId);
  const selected = session.answers[questionId] ?? "";
  const evaluated = Boolean(session.evaluated[questionId]);
  const immediate = session.mode !== MODE.EXAM;
  const answeredCount = session.questionIds.filter((id) => session.answers[id]).length;
  const progress = Math.round((answeredCount / session.questionIds.length) * 100);

  app.innerHTML = `
    <main class="quiz-shell">
      <header class="quiz-topbar">
        <div>
          <h1 class="quiz-heading">${escapeHtml(MODE_LABEL[session.mode])}｜${escapeHtml(session.source.label)}</h1>
          <button class="button" id="back-home" type="button">返回首頁</button>
        </div>
        <div class="quiz-meta">
          <span>${answeredCount} / ${session.questionIds.length} 已作答</span>
          ${session.mode === MODE.EXAM ? '<span class="timer" id="timer">01:30:00</span>' : ""}
        </div>
      </header>
      <div class="progress-track" role="progressbar" aria-label="作答進度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}">
        <div class="progress-bar" style="width:${progress}%"></div>
      </div>
      <div class="quiz-grid">
        <section class="question-panel">
          <div class="question-kicker">第 ${session.currentIndex + 1}／${session.questionIds.length} 題・原題號 ${question.question_number}</div>
          <p class="question-text">${escapeHtml(question.question)}</p>
          <div class="question-images" id="question-images"></div>
          <div class="option-list" id="option-list"></div>
          <div id="feedback-area"></div>
          <div class="question-actions">
            <button class="button" id="previous-question" type="button" ${session.currentIndex === 0 ? "disabled" : ""}>上一題</button>
            <button class="button button-primary" id="next-question" type="button">${session.currentIndex === session.questionIds.length - 1 ? (session.mode === MODE.EXAM ? "檢查並交卷" : "完成練習") : "下一題"}</button>
          </div>
        </section>
        <aside class="palette" aria-label="題號面板">
          <h2 class="palette-title">點題號快速跳轉</h2>
          <div class="palette-grid" id="palette-grid"></div>
          <div class="palette-legend">
            <span class="legend-item"><span class="legend-swatch current"></span>目前題目</span>
            <span class="legend-item"><span class="legend-swatch answered"></span>已作答</span>
          </div>
          ${session.mode === MODE.EXAM ? '<div class="submit-area"><button class="button button-block" id="submit-exam" type="button">提前交卷</button></div>' : ""}
        </aside>
      </div>
    </main>`;

  const imageArea = document.getElementById("question-images");
  for (const [index, path] of question.images.entries()) {
    const image = document.createElement("img");
    image.className = "question-image";
    image.src = `./${path}`;
    image.alt = `題目 ${question.question_number} 圖片 ${index + 1}`;
    image.loading = "lazy";
    image.addEventListener("error", () => {
      const error = document.createElement("div");
      error.className = "image-error";
      error.setAttribute("role", "alert");
      error.textContent = `圖片載入失敗：${path}`;
      image.replaceWith(error);
    });
    imageArea.append(image);
  }

  const optionList = document.getElementById("option-list");
  for (const letter of session.optionOrders[questionId]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "option-button";
    if (selected === letter) button.classList.add("selected");
    if (immediate && evaluated && letter === question.answer) button.classList.add("correct");
    if (immediate && evaluated && selected === letter && letter !== question.answer) button.classList.add("incorrect");
    button.disabled = immediate && evaluated;
    button.setAttribute("aria-pressed", String(selected === letter));
    const letterNode = document.createElement("span");
    letterNode.className = "option-letter";
    letterNode.textContent = letter;
    const textNode = document.createElement("span");
    textNode.textContent = answerText(question, letter);
    button.append(letterNode, textNode);
    button.addEventListener("click", () => selectAnswer(letter));
    optionList.append(button);
  }

  if (immediate && evaluated) {
    const feedback = document.createElement("div");
    const correct = isCorrect(question, selected);
    feedback.className = `feedback ${correct ? "correct" : "incorrect"}`;
    feedback.textContent = correct ? "回答正確。" : `回答錯誤，正確答案是 ${question.answer}。`;
    const feedbackArea = document.getElementById("feedback-area");
    feedbackArea.append(feedback);
    const explanation = createExplanationDetails(question, !correct);
    if (explanation) feedbackArea.append(explanation);
  }

  const palette = document.getElementById("palette-grid");
  session.questionIds.forEach((id, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = questionStatusClass(id, index);
    button.textContent = String(index + 1);
    button.setAttribute("aria-label", `前往第 ${index + 1} 題`);
    button.addEventListener("click", () => goToQuestion(index));
    palette.append(button);
  });

  document.getElementById("back-home").addEventListener("click", () => {
    if (window.confirm("進度已自動保存，確定返回首頁嗎？")) renderHome();
  });
  document.getElementById("previous-question").addEventListener("click", () => goToQuestion(session.currentIndex - 1));
  document.getElementById("next-question").addEventListener("click", nextQuestion);
  document.getElementById("submit-exam")?.addEventListener("click", () => finishSession({ askConfirmation: true }));

  if (session.mode === MODE.EXAM) startTimer();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function selectAnswer(letter) {
  const session = state.session;
  const questionId = session.questionIds[session.currentIndex];
  const question = state.questionById.get(questionId);
  if (session.mode !== MODE.EXAM && session.evaluated[questionId]) return;
  session.answers[questionId] = letter;
  if (session.mode !== MODE.EXAM) {
    session.evaluated[questionId] = true;
    updateMistake(state.records, questionId, isCorrect(question, letter));
  }
  state.records.active_session = session;
  persist();
  renderQuiz();
}

function goToQuestion(index) {
  if (index < 0 || index >= state.session.questionIds.length) return;
  state.session.currentIndex = index;
  state.records.active_session = state.session;
  persist();
  renderQuiz();
}

function nextQuestion() {
  if (state.session.currentIndex < state.session.questionIds.length - 1) {
    goToQuestion(state.session.currentIndex + 1);
    return;
  }
  finishSession({ askConfirmation: true });
}

function startTimer() {
  const update = () => {
    const remaining = state.session.deadline - Date.now();
    const timer = document.getElementById("timer");
    if (timer) timer.textContent = formatDuration(remaining);
    if (remaining <= 0) finishSession({ expired: true, askConfirmation: false });
  };
  update();
  state.timerId = window.setInterval(update, 1000);
}

function finishSession({ expired = false, askConfirmation = false } = {}) {
  const session = state.session;
  if (!session || session.completed) return;
  const unanswered = session.questionIds.filter((id) => !session.answers[id]).length;
  if (askConfirmation) {
    const message = unanswered
      ? `還有 ${unanswered} 題未作答，確定結束並計分嗎？`
      : "確定結束並計分嗎？";
    if (!window.confirm(message)) return;
  }

  stopTimer();
  if (session.mode === MODE.EXAM) {
    for (const questionId of session.questionIds) {
      if (session.evaluated[questionId]) continue;
      const question = state.questionById.get(questionId);
      updateMistake(state.records, questionId, isCorrect(question, session.answers[questionId]));
      session.evaluated[questionId] = true;
    }
  }

  const score = scoreSession(session, state.questionById);
  const completedAt = Date.now();
  const attempt = {
    id: session.id,
    completedAt,
    mode: session.mode,
    sourceLabel: session.source.label,
    total: score.total,
    correct: score.correct,
    percentage: score.percentage,
    durationMs: completedAt - session.createdAt,
    expired,
  };
  state.records.attempt_history.push(attempt);
  state.records.attempt_history = state.records.attempt_history.slice(-100);
  session.completed = true;
  state.records.active_session = null;
  persist();
  state.lastResult = { score, attempt, session: structuredClone(session) };
  renderResults();
}

function renderResults() {
  stopTimer();
  const { score, attempt, session } = state.lastResult;
  const needsReview = score.details.filter((detail) => !detail.isCorrect);
  app.innerHTML = `
    <main class="page-shell">
      <header class="site-header">
        <div>
          <h1 class="brand-title">測驗完成</h1>
          <p class="brand-subtitle">${escapeHtml(MODE_LABEL[attempt.mode])}｜${escapeHtml(attempt.sourceLabel)}</p>
        </div>
      </header>
      <div class="result-layout">
        <section class="panel result-panel">
          <div class="score-circle"><span class="score-number">${score.percentage}%</span></div>
          <div class="stat-grid">
            <div class="stat"><span class="stat-value">${score.correct}</span><span class="stat-label">答對</span></div>
            <div class="stat"><span class="stat-value">${score.wrong}</span><span class="stat-label">答錯</span></div>
            <div class="stat"><span class="stat-value">${score.unanswered}</span><span class="stat-label">未作答</span></div>
          </div>
          ${attempt.expired ? '<p class="warning">時間已到，系統已自動交卷。</p>' : ""}
          <p class="muted">作答時間：${formatDuration(attempt.durationMs)}</p>
          <div class="button-row">
            <button class="button button-primary" id="result-home" type="button">回到首頁</button>
            <button class="button" id="retry-session" type="button">重做同一題組</button>
          </div>
        </section>
        <section class="panel result-panel">
          <h2 class="section-title">需要複習的題目</h2>
          ${needsReview.length ? '<div class="review-list" id="review-list"></div>' : '<p class="notice">全部答對，表現很好。</p>'}
        </section>
      </div>
    </main>`;

  const reviewList = document.getElementById("review-list");
  for (const detail of needsReview) {
    const question = state.questionById.get(detail.questionId);
    const item = document.createElement("article");
    item.className = "review-item";
    const title = document.createElement("p");
    title.className = "review-title";
    title.textContent = `${question.year} 年第 ${question.session} 次・科目 ${question.subject_code}・第 ${question.question_number} 題`;
    const text = document.createElement("p");
    text.textContent = question.question;
    const answer = document.createElement("p");
    answer.className = "review-answer";
    answer.textContent = `你的答案：${detail.selected || "未作答"}｜正確答案：${detail.correctAnswer}`;
    item.append(title, text, answer);
    const explanation = createExplanationDetails(question, true);
    if (explanation) item.append(explanation);
    reviewList.append(item);
  }

  document.getElementById("result-home").addEventListener("click", renderHome);
  document.getElementById("retry-session").addEventListener("click", () => {
    const selectedQuestions = session.questionIds.map((id) => state.questionById.get(id)).filter(Boolean);
    state.session = createSession({ mode: session.mode, selectedQuestions, source: session.source });
    state.records.active_session = state.session;
    persist();
    renderQuiz();
  });
}

function clearRecords() {
  if (!window.confirm("這會清除目前瀏覽器中的進度、錯題與成績，且無法復原。確定清除嗎？")) return;
  state.records = {
    schema_version: 1,
    active_session: null,
    mistakes: {},
    attempt_history: [],
  };
  persist();
  renderHome();
}

importInput.addEventListener("change", async () => {
  const file = importInput.files?.[0];
  importInput.value = "";
  if (!file) return;
  try {
    const imported = parseImportedRecords(await file.text());
    if (!window.confirm("匯入會取代目前瀏覽器中的學習紀錄，確定繼續嗎？")) return;
    state.records = imported;
    state.storageWarning = saveRecords(state.records);
    window.alert("學習紀錄已成功匯入。");
    renderHome();
  } catch (error) {
    window.alert(`匯入失敗：${error.message}`);
  }
});

async function init() {
  try {
    const [questionResponse, explanationResult] = await Promise.all([
      fetch("./data/questions.json", { cache: "no-store" }),
      fetch("./data/explanations.json", { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return response.json();
        })
        .catch((error) => ({ error })),
    ]);
    if (!questionResponse.ok) throw new Error(`HTTP ${questionResponse.status}`);
    state.bank = validateBank(await questionResponse.json());
    const validQuestionIds = new Set(state.bank.questions.map((question) => question.id));
    if (explanationResult?.error) {
      state.explanationWarning = `解析資料暫時無法載入，題庫仍可正常使用：${explanationResult.error.message}`;
    } else {
      const parsed = parsePublicExplanations(explanationResult, validQuestionIds);
      state.explanationWarning = parsed.warnings.length
        ? `有 ${parsed.warnings.length} 筆解析資料未通過檢核，已安全略過。`
        : "";
      state.bank.questions = attachExplanations(state.bank.questions, parsed.items);
    }
    state.questionById = new Map(state.bank.questions.map((question) => [question.id, question]));
    const loaded = loadRecords();
    state.records = loaded.records;
    state.storageWarning = loaded.warning;
    renderHome();
  } catch (error) {
    renderFatal(`無法載入題庫資料：${error.message}`);
  }
}

init();
