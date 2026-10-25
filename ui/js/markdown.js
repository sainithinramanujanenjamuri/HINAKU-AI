/**
 * Markdown & Code rendering utility
 * Syntax tags, table normalization, and copy buttons
 */
export function formatMarkdown(text) {
  if (!text) return "";

  // Convert LaTeX math notation to plain Unicode symbols
  let processed = (typeof window.convertLatexSymbols === "function")
    ? window.convertLatexSymbols(text)
    : text;

  // Ensure bold headings directly following list items render cleanly
  const normalized = processed.replace(/((?:^|\n)[ \t]*(?:[-*+]|\d+\.)[^\n]+)\n([ \t]*\*\*[^*]+?\*\*.*)/g, "$1\n\n$2");

  let html = window.marked ? window.marked.parse(normalized) : normalized;

  // Post-process to decorate pre blocks with code headers and copy buttons
  return wrapCodeBlocks(html);
}

function wrapCodeBlocks(html) {
  const temp = document.createElement("div");
  temp.innerHTML = html;

  const preBlocks = temp.querySelectorAll("pre");
  preBlocks.forEach(pre => {
    const code = pre.querySelector("code");
    let lang = "code";
    if (code) {
      const cls = Array.from(code.classList).find(c => c.startsWith("language-"));
      if (cls) lang = cls.replace("language-", "");
    }

    const header = document.createElement("div");
    header.className = "code-header-bar";
    header.innerHTML = `
      <span>${lang}</span>
      <button class="copy-code-btn" type="button">📋 Copy</button>
    `;

    pre.insertBefore(header, pre.firstChild);
  });

  return temp.innerHTML;
}

export function attachCodeBlockCopyHandlers(container) {
  if (!container) return;
  const buttons = container.querySelectorAll(".copy-code-btn");
  buttons.forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const pre = btn.closest("pre");
      if (!pre) return;
      const codeEl = pre.querySelector("code");
      const textToCopy = codeEl ? codeEl.innerText : pre.innerText;
      navigator.clipboard.writeText(textToCopy).then(() => {
        btn.textContent = "✓ Copied";
        setTimeout(() => (btn.textContent = "📋 Copy"), 2000);
      });
    };
  });
}

