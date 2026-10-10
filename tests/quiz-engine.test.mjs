import test from "node:test";
import assert from "node:assert/strict";

import {
  EXAM_DURATION_MS,
  MODE,
  createSession,
  paperKey,
  scoreSession,
  selectQuestions,
  shuffle,
} from "../site/js/quiz-engine.mjs";
import { emptyRecords, updateMistake } from "../site/js/storage.mjs";
import { attachExplanations, parsePublicExplanations } from "../site/js/explanation-data.mjs";

function question(id, number, answer = "A", overrides = {}) {
  return {
    id,
    year: 115,
    session: 1,
    subject_code: 2,
    question_number: number,
    answer,
    option_a: "A",
    option_b: "B",
    option_c: "C",
    option_d: "D",
    ...overrides,
  };
}

test("paperKey creates a stable paper selector key", () => {
  assert.equal(paperKey(question("q1", 1)), "115-1-S2");
});

test("shuffle keeps every input item", () => {
  const result = shuffle([1, 2, 3, 4], () => 0);
  assert.deepEqual([...result].sort(), [1, 2, 3, 4]);
  assert.notDeepEqual(result, [1, 2, 3, 4]);
});

test("exam sessions preserve official order and option order", () => {
  const items = [question("q2", 2), question("q1", 1)];
  const selected = selectQuestions({
    questions: items,
    sourceType: "paper",
    paper: "115-1-S2",
    count: 50,
    mode: MODE.EXAM,
  });
  const session = createSession({ mode: MODE.EXAM, selectedQuestions: selected, source: {}, now: 1000 });
  assert.deepEqual(session.questionIds, ["q1", "q2"]);
  assert.deepEqual(session.optionOrders.q1, ["A", "B", "C", "D"]);
  assert.equal(session.deadline, 1000 + EXAM_DURATION_MS);
});

test("random selection respects requested count", () => {
  const items = Array.from({ length: 10 }, (_, index) => question(`q${index + 1}`, index + 1));
  const selected = selectQuestions({
    questions: items,
    sourceType: "random",
    subjectCode: 2,
    count: 4,
    mode: MODE.PRACTICE,
    random: () => 0.25,
  });
  assert.equal(selected.length, 4);
  assert.equal(new Set(selected.map((item) => item.id)).size, 4);
});

test("scoreSession separates wrong and unanswered answers", () => {
  const items = [question("q1", 1, "A"), question("q2", 2, "B"), question("q3", 3, "C")];
  const session = createSession({ mode: MODE.EXAM, selectedQuestions: items, source: {}, now: 1 });
  session.answers = { q1: "A", q2: "D" };
  const score = scoreSession(session, new Map(items.map((item) => [item.id, item])));
  assert.deepEqual(
    { correct: score.correct, wrong: score.wrong, unanswered: score.unanswered, percentage: score.percentage },
    { correct: 1, wrong: 1, unanswered: 1, percentage: 33 },
  );
});

test("a mistake is removed after two consecutive correct answers", () => {
  const records = emptyRecords();
  updateMistake(records, "q1", false, 1);
  assert.equal(records.mistakes.q1.wrongCount, 1);
  updateMistake(records, "q1", true, 2);
  assert.equal(records.mistakes.q1.correctStreak, 1);
  updateMistake(records, "q1", true, 3);
  assert.equal(records.mistakes.q1, undefined);
});

test("a new wrong answer resets the correct streak", () => {
  const records = emptyRecords();
  updateMistake(records, "q1", false, 1);
  updateMistake(records, "q1", true, 2);
  updateMistake(records, "q1", false, 3);
  assert.equal(records.mistakes.q1.correctStreak, 0);
  assert.equal(records.mistakes.q1.wrongCount, 2);
});

test("public explanations are validated and attached by stable question id", () => {
  const payload = {
    schema_version: 1,
    items: {
      q1: {
        markdown: "**解析**",
        images: ["assets/explanations/q1/image-01.png"],
        updated_at: "2026-09-02",
      },
    },
  };
  const parsed = parsePublicExplanations(payload, new Set(["q1"]));
  assert.deepEqual(parsed.warnings, []);
  const [attached] = attachExplanations([question("q1", 1)], parsed.items);
  assert.equal(attached.explanation.markdown, "**解析**");
});

test("invalid explanation image paths are isolated instead of breaking the bank", () => {
  const payload = {
    schema_version: 1,
    items: {
      q1: { markdown: "解析", images: ["../secret.png"] },
      q2: { markdown: "有效解析", images: [] },
    },
  };
  const parsed = parsePublicExplanations(payload, new Set(["q1", "q2"]));
  assert.equal(parsed.items.has("q1"), false);
  assert.equal(parsed.items.get("q2").markdown, "有效解析");
  assert.equal(parsed.warnings.length, 1);
});
