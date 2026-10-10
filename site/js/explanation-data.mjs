const PUBLIC_IMAGE_PATTERN = /^assets\/explanations\/([A-Za-z0-9-]+)\/[a-z0-9-]+\.(?:png|jpe?g|webp)$/i;

export function parsePublicExplanations(payload, validQuestionIds) {
  const items = new Map();
  const warnings = [];
  const validIds = validQuestionIds instanceof Set
    ? validQuestionIds
    : new Set(validQuestionIds ?? []);

  if (!payload || payload.schema_version !== 1 || !payload.items || Array.isArray(payload.items)) {
    return { items, warnings: ["解析資料格式不正確，已略過全部解析。"] };
  }

  for (const [questionId, source] of Object.entries(payload.items)) {
    if (!validIds.has(questionId)) {
      warnings.push(`解析引用不存在的題目：${questionId}`);
      continue;
    }
    if (!source || typeof source !== "object" || typeof source.markdown !== "string") {
      warnings.push(`${questionId} 的解析格式不正確`);
      continue;
    }
    const markdown = source.markdown.trim();
    if (!markdown || markdown.length > 50000) {
      warnings.push(`${questionId} 的解析為空白或超過長度限制`);
      continue;
    }
    const images = [];
    let imageError = false;
    for (const imagePath of Array.isArray(source.images) ? source.images : []) {
      const match = typeof imagePath === "string" ? PUBLIC_IMAGE_PATTERN.exec(imagePath) : null;
      if (!match || match[1] !== questionId) {
        warnings.push(`${questionId} 的解析圖片路徑不正確`);
        imageError = true;
        break;
      }
      images.push(imagePath);
    }
    if (imageError) continue;

    items.set(questionId, Object.freeze({
      markdown,
      images: Object.freeze(images),
      updated_at: typeof source.updated_at === "string" ? source.updated_at : "",
    }));
  }

  return { items, warnings };
}

export function attachExplanations(questions, explanationItems) {
  return questions.map((question) => ({
    ...question,
    explanation: explanationItems.get(question.id) ?? null,
  }));
}
