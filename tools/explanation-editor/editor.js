import { createMarkdownElement } from "/site/js/markdown.mjs";

const token = new URLSearchParams(window.location.search).get("token") || sessionStorage.getItem("explanation-editor-token");
if (token) sessionStorage.setItem("explanation-editor-token", token);
window.history.replaceState({}, "", "/");

const elements = {
  layout: document.getElementById("editor-layout"),
  loading: document.getElementById("loading"),
  fatal: document.getElementById("fatal"),
  search: document.getElementById("search-input"),
  subject: document.getElementById("subject-filter"),
  status: document.getElementById("status-filter"),
  count: document.getElementById("question-count"),
  list: document.getElementById("question-list"),
  statusBadge: document.getElementById("status-badge"),
  questionTitle: document.getElementById("question-title"),
  questionId: document.getElementById("question-id"),
  questionText: document.getElementById("question-text"),
  questionImages: document.getElementById("question-images"),
  optionList: document.getElementById("option-list"),
  officialAnswer: document.getElementById("official-answer"),
  markdown: document.getElementById("markdown-input"),
  markdownPreview: document.getElementById("markdown-preview"),
  assetList: document.getElementById("asset-list"),
  chooseImage: document.getElementById("choose-image"),
  imageInput: document.getElementById("image-input"),
  imageDrop: document.getElementById("image-drop"),
  review: document.getElementById("review-button"),
  unpublish: document.getElementById("unpublish-button"),
  publish: document.getElementById("publish-button"),
  stateHelp: document.getElementById("editor-state-help"),
  saveStatus: document.getElementById("save-status"),
  toast: document.getElementById("toast"),
};

const STATUS_LABELS = {
  empty: "尚未撰寫",
  draft: "草稿",
  "reviewed-unpublished": "已審核・尚未發布",
  published: "已發布",
  "published-modified": "已發布後修改",
  "unpublish-pending": "等待取消發布",
};

const state = {
  questions: [],
  questionById: new Map(),
  workspace: { items: {} },
  publicItems: {},
  statuses: {},
  selectedId: null,
  saveTimers: new Map(),
  siteUrl: "",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Editor-Token": token || "",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function showToast(message, duration = 3600) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { elements.toast.hidden = true; }, duration);
}

function emptyItem() {
  return { status: "draft", markdown: "", images: [], published_revision: null, unpublish: false };
}

function currentItem(questionId = state.selectedId) {
  return state.workspace.items[questionId] ?? emptyItem();
}

function truncate(value, length = 68) {
  const text = String(value).replace(/\s+/g, " ").trim();
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

function filteredQuestions() {
  const keyword = elements.search.value.trim().toLocaleLowerCase("zh-TW");
  return state.questions.filter((question) => {
    if (elements.subject.value && String(question.subject_code) !== elements.subject.value) return false;
    if (elements.status.value && state.statuses[question.id] !== elements.status.value) return false;
    if (!keyword) return true;
    const haystack = [question.id, question.question_number, question.question, question.subject_name]
      .join(" ")
      .toLocaleLowerCase("zh-TW");
    return haystack.includes(keyword);
  });
}

function renderQuestionList() {
  const rows = filteredQuestions();
  elements.count.textContent = `顯示 ${rows.length}／${state.questions.length} 題`;
  elements.list.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const question of rows) {
    const button = document.createElement("button");
    button.type = "button";
    if (question.id === state.selectedId) button.classList.add("current");
    const heading = document.createElement("strong");
    heading.textContent = `${question.year}-${question.session}・科目 ${question.subject_code}・第 ${question.question_number} 題｜${STATUS_LABELS[state.statuses[question.id]]}`;
    const summary = document.createElement("small");
    summary.textContent = truncate(question.question);
    button.append(heading, summary);
    button.addEventListener("click", () => selectQuestion(question.id));
    fragment.append(button);
  }
  elements.list.append(fragment);
}

function renderMarkdownPreview() {
  elements.markdownPreview.replaceChildren();
  const markdown = elements.markdown.value.trim();
  if (!markdown) {
    elements.markdownPreview.classList.add("muted-empty");
    elements.markdownPreview.textContent = "尚未輸入解析。";
    return;
  }
  elements.markdownPreview.classList.remove("muted-empty");
  elements.markdownPreview.append(createMarkdownElement(markdown));
}

function localAssetUrl(questionId, name) {
  const query = new URLSearchParams({ question: questionId, name, token });
  return `/api/local-asset?${query}`;
}

function renderAssets(item) {
  elements.assetList.replaceChildren();
  for (const image of item.images ?? []) {
    const card = document.createElement("article");
    card.className = "asset-card";
    const preview = document.createElement("img");
    preview.src = localAssetUrl(state.selectedId, image.name);
    preview.alt = image.alt || "解析圖片預覽";
    const label = document.createElement("p");
    label.textContent = image.alt || image.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `移除 ${image.name}`);
    remove.addEventListener("click", () => removeImage(image.name));
    card.append(preview, label, remove);
    elements.assetList.append(card);
  }
}

function renderSelectedQuestion() {
  const question = state.questionById.get(state.selectedId);
  if (!question) return;
  const item = currentItem();
  const itemStatus = state.statuses[question.id] || "empty";
  elements.statusBadge.className = `status-badge ${itemStatus}`;
  elements.statusBadge.textContent = STATUS_LABELS[itemStatus];
  elements.questionTitle.textContent = `${question.year} 年第 ${question.session} 次・科目 ${question.subject_code}・第 ${question.question_number} 題`;
  elements.questionId.textContent = question.id;
  elements.questionText.textContent = question.question;
  elements.officialAnswer.textContent = `官方答案：${question.answer}`;
  elements.questionImages.replaceChildren();
  for (const [index, path] of question.images.entries()) {
    const image = document.createElement("img");
    image.src = `/site/${path}`;
    image.alt = `題目圖片 ${index + 1}`;
    image.loading = "lazy";
    elements.questionImages.append(image);
  }
  elements.optionList.replaceChildren();
  for (const letter of ["A", "B", "C", "D"]) {
    const row = document.createElement("li");
    const key = document.createElement("strong");
    key.textContent = letter;
    row.append(key, document.createTextNode(question[`option_${letter.toLowerCase()}`]));
    elements.optionList.append(row);
  }

  elements.markdown.value = item.markdown ?? "";
  elements.review.textContent = item.status === "reviewed" ? "重新標記草稿" : "標記已審核";
  elements.unpublish.hidden = !state.publicItems[question.id];
  elements.unpublish.textContent = item.unpublish ? "保留正式解析" : "取消發布";
  elements.stateHelp.textContent = itemStatus === "published-modified"
    ? "正式網站仍顯示上一個已發布版本。"
    : itemStatus === "reviewed-unpublished"
      ? "已完成審核，可使用右上角按鈕發布。"
      : "輸入內容會自動保存到本機工作檔。";
  renderAssets(item);
  renderMarkdownPreview();
}

function selectQuestion(questionId) {
  state.selectedId = questionId;
  renderQuestionList();
  renderSelectedQuestion();
  document.querySelector(".question-preview")?.scrollTo({ top: 0 });
  document.querySelector(".explanation-editor")?.scrollTo({ top: 0 });
}

function updateStateFromResponse(questionId, response) {
  state.workspace.items[questionId] = response.item;
  state.statuses[questionId] = response.state;
  elements.saveStatus.textContent = "已保存";
  renderQuestionList();
  if (questionId === state.selectedId) renderSelectedQuestion();
}

async function saveItem(questionId) {
  window.clearTimeout(state.saveTimers.get(questionId));
  state.saveTimers.delete(questionId);
  const item = state.workspace.items[questionId] ?? emptyItem();
  const sentMarkdown = item.markdown;
  elements.saveStatus.textContent = "保存中…";
  try {
    const response = await api("/api/item", {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, item }),
    });
    const liveItem = state.workspace.items[questionId];
    if (liveItem && liveItem.markdown !== sentMarkdown) {
      elements.saveStatus.textContent = "尚未保存";
      return;
    }
    updateStateFromResponse(questionId, response);
  } catch (error) {
    elements.saveStatus.textContent = "保存失敗";
    showToast(`保存失敗：${error.message}`, 6000);
    throw error;
  }
}

function scheduleSave() {
  const questionId = state.selectedId;
  const item = state.workspace.items[questionId] ?? emptyItem();
  item.markdown = elements.markdown.value;
  item.status = "draft";
  item.unpublish = Boolean(item.unpublish);
  state.workspace.items[questionId] = item;
  state.statuses[questionId] = state.publicItems[questionId] ? "published-modified" : (item.markdown.trim() ? "draft" : "empty");
  elements.saveStatus.textContent = "尚未保存";
  renderMarkdownPreview();
  renderQuestionList();
  window.clearTimeout(state.saveTimers.get(questionId));
  state.saveTimers.set(questionId, window.setTimeout(() => saveItem(questionId), 650));
}

async function flushCurrentSave() {
  if (state.saveTimers.has(state.selectedId)) await saveItem(state.selectedId);
}

async function toggleReview() {
  await flushCurrentSave();
  const item = currentItem();
  if (item.status === "reviewed") {
    item.status = "draft";
    const response = await api("/api/item", {
      method: "POST",
      body: JSON.stringify({ question_id: state.selectedId, item }),
    });
    updateStateFromResponse(state.selectedId, response);
    return;
  }
  try {
    const response = await api("/api/review", {
      method: "POST",
      body: JSON.stringify({ question_id: state.selectedId }),
    });
    updateStateFromResponse(state.selectedId, response);
    showToast("已標記為審核完成。正式網站尚未更新。")
  } catch (error) {
    showToast(`無法完成審核：${error.message}`, 6000);
  }
}

async function toggleUnpublish() {
  const item = currentItem();
  const unpublish = !item.unpublish;
  if (unpublish && !window.confirm("發布時會從正式網站移除這題解析，確定標記取消發布嗎？")) return;
  const response = await api("/api/unpublish", {
    method: "POST",
    body: JSON.stringify({ question_id: state.selectedId, unpublish }),
  });
  updateStateFromResponse(state.selectedId, response);
}

async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function addImages(files) {
  for (const file of files) {
    if (!file.type.startsWith("image/")) continue;
    try {
      const response = await api("/api/image", {
        method: "POST",
        body: JSON.stringify({ question_id: state.selectedId, data: await fileToDataUrl(file), alt: file.name }),
      });
      updateStateFromResponse(state.selectedId, response);
    } catch (error) {
      showToast(`${file.name} 加入失敗：${error.message}`, 6000);
    }
  }
}

async function removeImage(name) {
  if (!window.confirm("確定移除這張草稿圖片嗎？正式網站版本會保留到下次發布。")) return;
  const response = await api("/api/image/remove", {
    method: "POST",
    body: JSON.stringify({ question_id: state.selectedId, name }),
  });
  updateStateFromResponse(state.selectedId, response);
}

async function pollDeployment(commit) {
  for (let attempt = 0; attempt < 24; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 5000));
    try {
      const status = await api(`/api/deployment?commit=${encodeURIComponent(commit)}`);
      if (status.status === "completed") {
        showToast(status.conclusion === "success" ? `GitHub Pages 部署成功：${status.site_url}` : `部署失敗：${status.url}`, 10000);
        return;
      }
      elements.saveStatus.textContent = "Pages 部署中…";
    } catch {
      return;
    }
  }
  showToast("內容已推送；GitHub Pages 仍在部署，可稍後查看 Actions。", 8000);
}

async function publish() {
  await flushCurrentSave();
  elements.publish.disabled = true;
  try {
    const preview = await api("/api/publish-preview");
    if (!preview.updates && !preview.unpublishes) {
      showToast("目前沒有已審核且尚未發布的變更。")
      return;
    }
    const message = [
      `準備更新 ${preview.updates} 題、取消發布 ${preview.unpublishes} 題。`,
      `解析圖片共 ${preview.image_count} 張。`,
      "發布會建立 Git commit 並推送 GitHub，確定繼續嗎？",
    ].join("\n");
    if (!window.confirm(message)) return;
    elements.saveStatus.textContent = "正在發布…";
    const result = await api("/api/publish", {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    });
    if (result.no_changes) {
      showToast("沒有可發布的差異。")
      return;
    }
    showToast(`已推送 GitHub：${result.commit.slice(0, 7)}，正在等待 Pages 部署。`, 7000);
    await reloadBootstrap(state.selectedId);
    pollDeployment(result.commit);
  } catch (error) {
    elements.saveStatus.textContent = "發布失敗";
    showToast(`發布失敗：${error.message}`, 10000);
  } finally {
    elements.publish.disabled = false;
  }
}

function insertAroundSelection(before, after = before) {
  const start = elements.markdown.selectionStart;
  const end = elements.markdown.selectionEnd;
  const selected = elements.markdown.value.slice(start, end);
  elements.markdown.setRangeText(`${before}${selected}${after}`, start, end, "end");
  elements.markdown.focus();
  scheduleSave();
}

function insertPrefix(prefix) {
  const start = elements.markdown.selectionStart;
  const lineStart = elements.markdown.value.lastIndexOf("\n", start - 1) + 1;
  elements.markdown.setRangeText(prefix, lineStart, lineStart, "end");
  elements.markdown.focus();
  scheduleSave();
}

async function reloadBootstrap(preferredId = null) {
  const bootstrap = await api("/api/bootstrap");
  state.questions = bootstrap.questions.questions;
  state.questionById = new Map(state.questions.map((question) => [question.id, question]));
  state.workspace = bootstrap.workspace;
  state.publicItems = bootstrap.public.items;
  state.statuses = bootstrap.statuses;
  state.siteUrl = bootstrap.site_url;
  state.selectedId = preferredId && state.questionById.has(preferredId) ? preferredId : state.questions[0]?.id;
  renderQuestionList();
  renderSelectedQuestion();
}

function bindEvents() {
  elements.search.addEventListener("input", renderQuestionList);
  elements.subject.addEventListener("change", renderQuestionList);
  elements.status.addEventListener("change", renderQuestionList);
  elements.markdown.addEventListener("input", scheduleSave);
  elements.review.addEventListener("click", toggleReview);
  elements.unpublish.addEventListener("click", toggleUnpublish);
  elements.publish.addEventListener("click", publish);
  elements.chooseImage.addEventListener("click", () => elements.imageInput.click());
  elements.imageInput.addEventListener("change", () => {
    addImages([...elements.imageInput.files]);
    elements.imageInput.value = "";
  });
  elements.imageDrop.addEventListener("dragover", (event) => { event.preventDefault(); elements.imageDrop.classList.add("dragging"); });
  elements.imageDrop.addEventListener("dragleave", () => elements.imageDrop.classList.remove("dragging"));
  elements.imageDrop.addEventListener("drop", (event) => {
    event.preventDefault();
    elements.imageDrop.classList.remove("dragging");
    addImages([...event.dataTransfer.files]);
  });
  elements.markdown.addEventListener("paste", (event) => {
    const images = [...event.clipboardData.files].filter((file) => file.type.startsWith("image/"));
    if (images.length) addImages(images);
  });
  document.querySelector(".toolbar").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.wrap) insertAroundSelection(button.dataset.wrap);
    if (button.dataset.prefix) insertPrefix(button.dataset.prefix);
    if (button.dataset.block) insertAroundSelection("```\n", "\n```");
    if (button.hasAttribute("data-link")) insertAroundSelection("[", "](https://)");
  });
  window.addEventListener("beforeunload", (event) => {
    if (state.saveTimers.size) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
}

async function init() {
  if (!token) throw new Error("缺少工作階段權杖，請重新執行啟動器。");
  const bootstrap = await api("/api/bootstrap");
  const subjects = [...new Map(bootstrap.questions.questions.map((question) => [question.subject_code, question.subject_name])).entries()];
  for (const [code, name] of subjects) {
    const option = document.createElement("option");
    option.value = String(code);
    option.textContent = `科目 ${code}｜${name}`;
    elements.subject.append(option);
  }
  for (const [value, label] of Object.entries(STATUS_LABELS)) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    elements.status.append(option);
  }
  bindEvents();
  state.questions = bootstrap.questions.questions;
  state.questionById = new Map(state.questions.map((question) => [question.id, question]));
  state.workspace = bootstrap.workspace;
  state.publicItems = bootstrap.public.items;
  state.statuses = bootstrap.statuses;
  state.siteUrl = bootstrap.site_url;
  state.selectedId = state.questions[0]?.id;
  renderQuestionList();
  renderSelectedQuestion();
  elements.loading.hidden = true;
  elements.layout.hidden = false;
  elements.saveStatus.textContent = "已連線";
}

init().catch((error) => {
  elements.loading.hidden = true;
  elements.fatal.hidden = false;
  elements.fatal.textContent = `解析編輯器無法啟動：${error.message}`;
});
