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

function parseOfflineMarkdown(text) {
  // Simple, offline-safe markdown parser for dark desktop assistant
  let out = "";
  const lines = text.split("\n");
  let inCode = false;
  let codeLang = "";
  let codeBuffer = [];
  let inList = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const codeMatch = line.match(/^```([a-zA-Z0-9_-]*)/);

    if (codeMatch && !inCode) {
      if (inList) { out += "</ul>"; inList = false; }
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
      codeBuffer.push(line);
      continue;
    }

    // List item
    const listMatch = line.match(/^[-*+]\s+(.*)/);
    if (listMatch) {
      if (!inList) { out += "<ul>"; inList = true; }
      out += `<li>${formatInline(listMatch[1])}</li>`;
      continue;
    } else if (inList) {
      out += "</ul>";
      inList = false;
    }

    // Empty line -> paragraph break
    if (!line.trim()) {
      out += "<br>";
      continue;
    }

    out += `<p>${formatInline(line)}</p>`;
  }

  if (inCode) {
    const escaped = codeBuffer.join("\n").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    out += `<pre><code class="language-${codeLang}">${escaped}</code></pre>`;
  }
  if (inList) {
    out += "</ul>";
  }

  return out;
}

function formatInline(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
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

