// HINAKU UI Client
document.addEventListener("DOMContentLoaded", () => {
  const messagesContainer = document.getElementById("messages-container");
  const promptInput = document.getElementById("prompt-input");
  const sendButton = document.getElementById("send-button");
  const modelBadge = document.getElementById("model-badge");
  const statusIndicator = document.getElementById("status-indicator");

  let conversationHistory = [];
  let isGenerating = false;
  let activeAbortController = null;

  // Initialize marked settings
  if (window.marked) {
    marked.setOptions({
      breaks: true,
      gfm: true
    });
  }

  // Fetch status info
  async function checkInfo() {
    try {
      const res = await fetch("/api/info");
      if (res.ok) {
        const data = await res.json();
        const modelName = data.default_model || "qwen3.5:4b";
        modelBadge.textContent = `${modelName} • local`;
        if (data.ollama_status && data.ollama_status.online) {
          statusIndicator.classList.remove("offline");
          statusIndicator.title = "Ollama online";
        } else {
          statusIndicator.classList.add("offline");
          statusIndicator.title = "Ollama offline or model not found";
        }
      }
    } catch (e) {
      statusIndicator.classList.add("offline");
      statusIndicator.title = "Backend unreachable";
    }
  }

  checkInfo();

  // Auto-resize input
  promptInput.addEventListener("input", () => {
    promptInput.style.height = "auto";
    promptInput.style.height = `${Math.min(promptInput.scrollHeight, 160)}px`;
  });

  // Handle Enter (send) vs Shift+Enter (newline)
  promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendButton.addEventListener("click", () => {
    sendMessage();
  });

  function renderMessage(role, content, isStreaming = false) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role}`;

    const metaDiv = document.createElement("div");
    metaDiv.className = "message-meta";
    metaDiv.textContent = role === "user" ? "You" : "HINAKU";
    msgDiv.appendChild(metaDiv);

    const bodyDiv = document.createElement("div");
    bodyDiv.className = "message-body";

    if (role === "assistant") {
      if (window.marked && content) {
        bodyDiv.innerHTML = marked.parse(content);
      } else {
        bodyDiv.textContent = content;
      }
      if (isStreaming) {
        const cursor = document.createElement("span");
        cursor.className = "streaming-cursor";
        bodyDiv.appendChild(cursor);
      }
      attachCopyButtons(bodyDiv);
    } else {
      bodyDiv.textContent = content;
    }

    msgDiv.appendChild(bodyDiv);
    messagesContainer.appendChild(msgDiv);
    scrollToBottom();
    return { msgDiv, bodyDiv };
  }

  function attachCopyButtons(container) {
    const preBlocks = container.querySelectorAll("pre");
    preBlocks.forEach((pre) => {
      if (!pre.querySelector(".copy-btn")) {
        const btn = document.createElement("button");
        btn.className = "copy-btn";
        btn.textContent = "Copy";
        btn.addEventListener("click", () => {
          const code = pre.querySelector("code") ? pre.querySelector("code").innerText : pre.innerText;
          navigator.clipboard.writeText(code).then(() => {
            btn.textContent = "Copied!";
            setTimeout(() => (btn.textContent = "Copy"), 2000);
          });
        });
        pre.appendChild(btn);
      }
    });
  }

  function scrollToBottom() {
    const chatContainer = document.querySelector(".chat-container");
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  async function sendMessage() {
    const text = promptInput.value.trim();
    if (!text || isGenerating) return;

    // Reset input
    promptInput.value = "";
    promptInput.style.height = "auto";
    sendButton.disabled = true;
    isGenerating = true;

    // Append user message
    conversationHistory.push({ role: "user", content: text });
    renderMessage("user", text);

    // Create placeholder for assistant response
    let assistantText = "";
    const { bodyDiv } = renderMessage("assistant", "", true);

    activeAbortController = new AbortController();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: conversationHistory,
          stream: true
        }),
        signal: activeAbortController.signal
      });

      if (!response.ok) {
        throw new Error(`Server returned status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop(); // keep last incomplete chunk

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const dataStr = trimmed.slice(5).trim();

          if (dataStr === "[DONE]") {
            break;
          }

          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.chunk) {
              assistantText += parsed.chunk;
              if (window.marked) {
                bodyDiv.innerHTML = marked.parse(assistantText);
              } else {
                bodyDiv.textContent = assistantText;
              }
              const cursor = document.createElement("span");
              cursor.className = "streaming-cursor";
              bodyDiv.appendChild(cursor);
              attachCopyButtons(bodyDiv);
              scrollToBottom();
            }
          } catch (e) {
            console.error("Failed to parse SSE line:", line, e);
          }
        }
      }

      // Remove cursor at end
      const cursor = bodyDiv.querySelector(".streaming-cursor");
      if (cursor) cursor.remove();
      attachCopyButtons(bodyDiv);
      conversationHistory.push({ role: "assistant", content: assistantText });

    } catch (err) {
      if (err.name !== "AbortError") {
        bodyDiv.innerHTML = `<span style="color: #ef4444;">[Error: ${err.message}]</span>`;
      }
    } finally {
      isGenerating = false;
      sendButton.disabled = false;
      promptInput.focus();
    }
  }

  // Starfield subtle ambient motion
  initStarfield();

  function initStarfield() {
    const canvas = document.getElementById("starfield");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener("resize", () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    const starCount = 65;
    const stars = [];

    for (let i = 0; i < starCount; i++) {
      stars.push({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: Math.random() * 1.2 + 0.3,
        alpha: Math.random() * 0.6 + 0.1,
        speed: Math.random() * 0.15 + 0.05
      });
    }

    function render() {
      ctx.clearRect(0, 0, width, height);

      for (let s of stars) {
        s.y -= s.speed;
        if (s.y < 0) {
          s.y = height;
          s.x = Math.random() * width;
        }

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(180, 190, 220, ${s.alpha})`;
        ctx.fill();
      }

      requestAnimationFrame(render);
    }

    render();
  }
});

