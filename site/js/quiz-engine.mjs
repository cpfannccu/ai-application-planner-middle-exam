export const MODE = Object.freeze({
  PRACTICE: "practice",
  EXAM: "exam",
  MISTAKES: "mistakes",
});

export const EXAM_DURATION_MS = 90 * 60 * 1000;
const LETTERS = Object.freeze(["A", "B", "C", "D"]);

export function shuffle(items, random = Math.random) {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1));
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }
  return result;
}

export function paperKey(question) {
  return `${question.year}-${question.session}-S${question.subject_code}`;
}

export function sortOfficialOrder(questions) {
  return [...questions].sort((left, right) =>
    left.year - right.year ||
    left.session - right.session ||
    left.subject_code - right.subject_code ||
    left.question_number - right.question_number,
  );
}

export function selectQuestions({ questions, sourceType, paper, subjectCode, count, mode, random = Math.random }) {
  let candidates;
  if (sourceType === "paper") {
    candidates = questions.filter((question) => paperKey(question) === paper);
  } else {
    candidates = questions.filter((question) => Number(question.subject_code) === Number(subjectCode));
  }

  if (sourceType === "random") {
    candidates = shuffle(candidates, random).slice(0, Math.min(count, candidates.length));
  }

  if (mode === MODE.EXAM) {
    return sortOfficialOrder(candidates);
  }
  return shuffle(candidates, random);
}

export function createSession({ mode, selectedQuestions, source, now = Date.now(), random = Math.random }) {
  if (!Object.values(MODE).includes(mode)) throw new Error("不支援的測驗模式");
  if (!selectedQuestions.length) throw new Error("沒有可用題目");

  const questionIds = selectedQuestions.map((question) => question.id);
  const optionOrders = {};
  for (const question of selectedQuestions) {
    optionOrders[question.id] = mode === MODE.EXAM ? [...LETTERS] : shuffle(LETTERS, random);
  }

  return {
    schema_version: 1,
    id: `session-${now}`,
    mode,
    source,
    createdAt: now,
    deadline: mode === MODE.EXAM ? now + EXAM_DURATION_MS : null,
    questionIds,
    optionOrders,
    answers: {},
    evaluated: {},
    currentIndex: 0,
    completed: false,
  };
}

export function answerText(question, letter) {
  return question[`option_${letter.toLowerCase()}`] ?? "";
}

export function isCorrect(question, selectedLetter) {
  return Boolean(selectedLetter) && question.answer === selectedLetter;
}

export function scoreSession(session, questionById) {
  let correct = 0;
  let wrong = 0;
  let unanswered = 0;
  const details = [];

  for (const questionId of session.questionIds) {
    const question = questionById.get(questionId);
    if (!question) continue;
    const selected = session.answers[questionId] ?? "";
    const correctAnswer = question.answer;
    const result = selected ? selected === correctAnswer : false;
    if (!selected) unanswered += 1;
    else if (result) correct += 1;
    else wrong += 1;
    details.push({ questionId, selected, correctAnswer, isCorrect: result });
  }

  const total = details.length;
  return {
    total,
    correct,
    wrong,
    unanswered,
    percentage: total ? Math.round((correct / total) * 100) : 0,
    details,
  };
}

export function formatDuration(milliseconds) {
  const safe = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  return [hours, minutes, seconds].map((part) => String(part).padStart(2, "0")).join(":");
}

