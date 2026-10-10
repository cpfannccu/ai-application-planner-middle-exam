import { marked } from "../vendor/marked.esm.js";
import DOMPurify from "../vendor/purify.es.mjs";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const renderer = {
  html(token) {
    return `<p>${escapeHtml(token.text ?? "")}</p>`;
  },
  image(token) {
    const label = token.text ? `圖片：${token.text}` : "Markdown 內嵌圖片已停用";
    return `<span>${escapeHtml(label)}</span>`;
  },
};

marked.use({ renderer, gfm: true, breaks: true });

const ALLOWED_TAGS = [
  "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "del",
  "ul", "ol", "li", "blockquote", "pre", "code", "a", "hr", "table", "thead",
  "tbody", "tr", "th", "td", "span",
];

export function markdownToSafeHtml(markdown) {
  const rendered = marked.parse(String(markdown ?? ""), { async: false });
  return DOMPurify.sanitize(rendered, {
    ALLOWED_TAGS,
    ALLOWED_ATTR: ["href", "title"],
    ALLOW_DATA_ATTR: false,
    FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form", "input", "button", "textarea", "select", "option", "svg", "math", "img"],
  });
}

export function createMarkdownElement(markdown, className = "markdown-content") {
  const container = document.createElement("div");
  container.className = className;
  container.innerHTML = markdownToSafeHtml(markdown);
  for (const link of container.querySelectorAll("a[href]")) {
    let url;
    try {
      url = new URL(link.getAttribute("href"), document.baseURI);
    } catch {
      link.removeAttribute("href");
      continue;
    }
    if (!new Set(["http:", "https:", "mailto:"]).has(url.protocol)) {
      link.removeAttribute("href");
      continue;
    }
    if (url.protocol === "http:" || url.protocol === "https:") {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
  }
  return container;
}
