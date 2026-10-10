const STORAGE_KEY = "ai-planner-middle-learning-v1";

export function emptyRecords() {
  return {
    schema_version: 1,
    active_session: null,
    mistakes: {},
    attempt_history: [],
  };
}

export function validateRecords(value) {
  if (!value || typeof value !== "object") throw new Error("備份內容不是有效物件");
  if (value.schema_version !== 1) throw new Error("不支援的學習紀錄版本");
  if (!value.mistakes || typeof value.mistakes !== "object" || Array.isArray(value.mistakes)) {
    throw new Error("錯題紀錄格式不正確");
  }
  if (!Array.isArray(value.attempt_history)) throw new Error("測驗歷史格式不正確");
  if (value.active_session !== null && typeof value.active_session !== "object") {
    throw new Error("進行中測驗格式不正確");
  }
  return value;
}

export function loadRecords() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return { records: raw ? validateRecords(JSON.parse(raw)) : emptyRecords(), warning: "" };
  } catch (error) {
    return { records: emptyRecords(), warning: `無法讀取瀏覽器紀錄：${error.message}` };
  }
}

export function saveRecords(records) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
    return "";
  } catch (error) {
    return `無法保存瀏覽器紀錄：${error.message}`;
  }
}

export function parseImportedRecords(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("檔案不是有效的 JSON");
  }
  return validateRecords(parsed);
}

export function downloadRecords(records) {
  const content = JSON.stringify(records, null, 2);
  const blob = new Blob([content], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `中級題庫學習紀錄-${new Date().toISOString().slice(0, 10)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function updateMistake(records, questionId, correct, answeredAt = Date.now()) {
  const existing = records.mistakes[questionId];
  if (correct) {
    if (!existing) return;
    existing.correctStreak = Number(existing.correctStreak || 0) + 1;
    existing.lastAnsweredAt = answeredAt;
    if (existing.correctStreak >= 2) delete records.mistakes[questionId];
    return;
  }

  records.mistakes[questionId] = {
    questionId,
    wrongCount: Number(existing?.wrongCount || 0) + 1,
    correctStreak: 0,
    lastAnsweredAt: answeredAt,
  };
}

