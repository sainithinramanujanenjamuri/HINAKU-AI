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

  let html = window.marked ? window.marked.parse(normalized) : parseOfflineMarkdown(normalized);

  // Post-process to decorate pre blocks with code headers and copy buttons
  return wrapCodeBlocks(html);
}

export function parseOfflineMarkdown(text) {
  // Offline-safe markdown parser supporting headers, rules, lists, and inline styles
  let out = "";
  const lines = text.split("\n");
  let inCode = false;
  let codeLang = "";
  let codeBuffer = [];
  let inUl = false;
  let inOl = false;
  let inTable = false;

  function closeLists() {
    if (inUl) { out += "</ul>"; inUl = false; }
    if (inOl) { out += "</ol>"; inOl = false; }
    if (inTable) { out += "</tbody></table>"; inTable = false; }
  }

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const line = rawLine.trimEnd();

    // Code blocks: ```python ... ```
    const codeMatch = line.match(/^```([a-zA-Z0-9_-]*)/);
    if (codeMatch && !inCode) {
      closeLists();
      inCode = true;
      codeLang = codeMatch[1] || "text";
      codeBuffer = [];
      continue;
    } else if (line.startsWith("```") && inCode) {
      inCode = false;
      const escaped = codeBuffer.join("\n").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      out += `<pre><code class="language-${codeLang}">${escaped}</code></pre>`;
      continue;
    }

    if (inCode) {
      codeBuffer.push(rawLine);
      continue;
    }

    // Horizontal rule: --- or *** or ___ (at least 3 characters)
    if (/^\s*([*\-_])\s*(?:\1\s*){2,}$/.test(line)) {
      closeLists();
      out += "<hr>";
      continue;
    }

    // Headings: # to ######
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      closeLists();
      const level = headingMatch[1].length;
      const content = formatInline(headingMatch[2].trim());
      out += `<h${level}>${content}</h${level}>`;
      continue;
    }

    // Blockquote: > quote
    const quoteMatch = line.match(/^>\s*(.*)$/);
    if (quoteMatch) {
      closeLists();
      out += `<blockquote><p>${formatInline(quoteMatch[1])}</p></blockquote>`;
      continue;
    }

    // Unordered list item: - or * or +
    const ulMatch = line.match(/^[\s]*[-*+]\s+(.*)$/);
    if (ulMatch) {
      if (inOl) { out += "</ol>"; inOl = false; }
      if (!inUl) { out += "<ul>"; inUl = true; }
      out += `<li>${formatInline(ulMatch[1])}</li>`;
      continue;
    }

    // Ordered list item: 1. 2. etc.
    const olMatch = line.match(/^[\s]*\d+\.\s+(.*)$/);
    if (olMatch) {
      if (inUl) { out += "</ul>"; inUl = false; }
      if (!inOl) { out += "<ol>"; inOl = true; }
      out += `<li>${formatInline(olMatch[1])}</li>`;
      continue;
    }

    // Non-list line
    closeLists();

    // Empty line
    if (!line.trim()) {
      continue;
    }

    out += `<p>${formatInline(line)}</p>`;
  }

  if (inCode) {
    const escaped = codeBuffer.join("\n").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    out += `<pre><code class="language-${codeLang}">${escaped}</code></pre>`;
  }
  closeLists();

  return out;
}

export function formatInline(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");
}

function wrapCodeBlocks(html) {
  if (typeof document === "undefined") return html;
  const temp = document.createElement("div");
  temp.innerHTML = html;

  const preBlocks = temp.querySelectorAll("pre");
  preBlocks.forEach(pre => {
    const code = pre.querySelector("code");
    if (!code) return;

    let lang = "text";
    code.classList.forEach(cls => {
      if (cls.startsWith("language-")) {
        lang = cls.replace("language-", "");
      }
    });

    const header = document.createElement("div");
    header.className = "code-block-header";

    const langSpan = document.createElement("span");
    langSpan.className = "code-lang-label";
    langSpan.textContent = lang;

    const copyBtn = document.createElement("button");
    copyBtn.className = "code-copy-btn";
    copyBtn.textContent = "Copy";
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(code.textContent).then(() => {
        copyBtn.textContent = "Copied!";
        setTimeout(() => (copyBtn.textContent = "Copy"), 2000);
      });
    };

    header.appendChild(langSpan);
    header.appendChild(copyBtn);
    pre.insertBefore(header, code);
  });

  return temp.innerHTML;
}

export function attachCodeBlockCopyHandlers(container) {
  if (!container) return;
  const buttons = container.querySelectorAll(".code-copy-btn, .copy-code-btn");
  buttons.forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const pre = btn.closest("pre");
      if (!pre) return;
      const codeEl = pre.querySelector("code");
      const textToCopy = codeEl ? codeEl.innerText : pre.innerText;
      navigator.clipboard.writeText(textToCopy).then(() => {
        btn.textContent = "Copied!";
        setTimeout(() => (btn.textContent = "Copy"), 2000);
      });
    };
  });
}

