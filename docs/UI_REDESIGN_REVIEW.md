# HINAKU Modern UI/UX Redesign Review

## 1. Executive Summary

The HINAKU UI/UX redesign transforms the personal AI assistant's desktop interface into a modern, quiet, dark, and highly responsive 3-column experience. Built with strict adherence to HINAKU's core identity—*"a universe without light"*—the new interface provides a tactile, professional workspace with zero light mode, zero external CDN dependencies, and truthful backend telemetry.

All existing backend API contracts and safeguards (sensitive guards, live data guards, private chats, think-harder, detailed mode, model router, memory extraction, curation, and self-build) remain intact and fully passing across the comprehensive test suite (**216 passed, 1 skipped**).

---

## 2. Reference Pattern Mapping Table

The redesign adopts modern desktop AI ergonomics (collapsible 3-column workspace, floating composer dock with removable mode chips, message action bars, transparent backend attribution, and full-page utility navigation) while preserving HINAKU's dark aesthetic.

| Modern Desktop AI Pattern | HINAKU Implementation | Location in Codebase |
| :--- | :--- | :--- |
| **3-Column Collapsible Shell** | Left conversation history sidebar (`Ctrl+B`), center conversation stage, and right contextual drawer (`Ctrl+.`). | `ui/index.html`<br>`ui/css/tokens_and_shell.css` |
| **Status Bar & Top Navigation** | Top bar with editable chat title, model indicator (`status-dot`), and top privacy mode chip. | `ui/index.html`<br>`ui/app.js` |
| **Composer Dock & Mode Chips** | Floating composer card with `+` menu for Think Harder (`num_predict: 2048`) and Detailed (`num_predict: 800`), with dismissible chip badges. | `ui/css/tokens_and_shell.css`<br>`ui/app.js` |
| **Model & Privacy Selector** | In-composer quick selectors for local model switches and privacy modes (Standard, Local-Only, Private). | `ui/app.js`<br>`ui/index.html` |
| **User Message Bubble & Folding** | Right-aligned elevated bubbles with automatic collapse/fold for prompts exceeding 350 characters. | `ui/css/messages.css`<br>`ui/js/message.js` |
| **Truthful Backend Badges** | Meta rows with truthful badges: `local` (cool violet), `API · logged by provider` (blue), and `guard` (subtle amber). | `ui/js/message.js`<br>`ui/css/messages.css` |
| **Collapsible Telemetry Accordion** | "Worked for X s >" summary line showing inference latency and token counts without exposing raw `<think>` thoughts. | `ui/js/message.js`<br>`ui/css/messages.css` |
| **Message Hover Actions** | Hover action bar with Copy, Thumbs Up, Thumbs Down, Edit Reply (curation feedback), Retry, and Continue. | `ui/js/message.js`<br>`ui/app.js` |
| **Markdown & Code Formatting** | Clean typography, syntax-highlighted code blocks with language header and copy button, and formatted tables. | `ui/js/markdown.js`<br>`ui/css/messages.css` |
| **Context Panel (Tabbed)** | Right-hand panel with tabs for live semantic memories and conversation telemetry/parameters. | `ui/css/pages.css`<br>`ui/app.js` |
| **Full Pages (No Intrusive Modals)** | Dedicated full-page view replacing dialogs with left navigation for Memories, Dataset Curation, Model Ratings, Self-Build Approval, and Settings. | `ui/css/pages.css`<br>`ui/js/pages.js` |
| **Settings & Accessibility** | Settings view with model selector, router mode, memory toggles, reduced motion toggle, and data export/wipe. | `ui/css/settings.css`<br>`ui/js/pages.js` |

---

## 3. Regression Verification Matrix

Every existing capability was verified against test suites and manual regression fixtures:

| Feature / Subsystem | Expected Behavior | Verification Status | Test Reference |
| :--- | :--- | :--- | :--- |
| **Sensitive-Data Guard** | PINs, cards, passwords refused immediately; redacted to `[removed]`; no memory extracted; badge labeled `guard`. | **Verified** | `tests/test_guards.py`<br>`tests/test_phase_d.py` |
| **Live-Data Guard** | Refuses real-time market/weather/news queries with search tracker instructions; labeled `guard`. | **Verified** | `tests/test_guards.py`<br>`tests/test_clock_and_persona.py` |
| **Private Chat Auto-Detection** | Triggers private mode when sensitive keywords appear; displays notice banner with 1-click **Undo**. | **Verified** | `tests/test_safety_and_correctness.py`<br>`ui/app.js` |
| **Think-Harder Mode** | Increases `num_predict` to 2048 with low temperature (0.2); indicated via composer chip. | **Verified** | `tests/test_thinking_benchmark.py`<br>`ui/app.js` |
| **Detailed Mode** | Routes to local detail adapter with `num_predict: 800` and detailed prompt formatting. | **Verified** | `tests/test_detail_mode.py`<br>`tests/test_detail_routing.py` |
| **Continue Button** | Sends automated "Continue" prompt to complete long streaming responses seamlessly. | **Verified** | `tests/test_ui_messages.py`<br>`ui/app.js` |
| **Feedback & Edit Reply** | Thumbs up/down and inline text edits save to interaction database to feed the 6-month curation engine. | **Verified** | `tests/test_phase_d.py`<br>`tests/test_ui_messages.py` |
| **Memory Drawer & Semantic Search** | Search, edit, and delete memories; re-index ChromaDB collection on demand. | **Verified** | `tests/test_phase_c.py`<br>`tests/ui/test_ui_pages.py` |
| **Dataset Curation Screen** | Displays approved interaction candidates, minimum training thresholds, and build trigger. | **Verified** | `tests/test_phase_e.py`<br>`tests/ui/test_ui_pages.py` |
| **Model Ratings View** | Renders upvote percentages, latencies, and interaction volume per model backend. | **Verified** | `tests/test_quality.py`<br>`tests/ui/test_ui_pages.py` |
| **Self-Build Approval Gate** | Displays candidate vs baseline evaluation scores with promotion gating. | **Verified** | `tests/test_phase_f.py`<br>`tests/test_phase_g.py` |
| **Settings & Data Management** | Modifies default model, router mode, memory toggle; provides full data export and WIPE_ALL reset. | **Verified** | `tests/test_phase_c.py`<br>`tests/ui/test_ui_settings.py` |
| **Dark Theme Only** | Sole aesthetic is dark; no light mode classes or variables exist; respects OS reduced-motion. | **Verified** | `tests/ui/test_ui_shell.py`<br>`ui/css/tokens_and_shell.css` |

---

## 4. Benchmark & Performance Summary

- **Total Unit & Integration Tests**: 217 items collected (216 passed, 1 skipped).
- **Test Suite Execution Time**: ~123.02s on target HP V15 laptop environment.
- **Zero Real Data Mutation**: 100% of test runs executed against mock databases and temporary chroma clients in `tmp_path`, maintaining `data/hinaku.db` integrity.
- **UI Responsiveness & Layout Breakpoints**:
  - `1280px`: Full 3-column desktop view (Sidebar + Conversation Stage + Context Drawer).
  - `960px`: Compact desktop view with auto-collapsed context drawer and floating composer overlay.
  - `720px`: Focused single-column view with collapsible navigation and wrapped composer actions.

---

## 5. Visual Artifacts & Screenshots

Visual artifacts are generated in demo mode (`HINAKU_UI_DEMO=1`) and stored in `docs/screenshots/`:

| Phase | View / Component | 1280px Wide | 960px Wide | 720px Wide |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1** | Design Tokens & Shell Layout | `phase1_shell_dark_1280px.png` | `phase1_shell_dark_960px.png` | `phase1_shell_dark_720px.png` |
| **Phase 2** | Messages, Code, Badges, & Actions | `phase2_conversation_dark_1280px.png` | `phase2_conversation_dark_960px.png` | `phase2_conversation_dark_720px.png` |
| **Phase 3** | Context Panel & Full Pages | `phase3_context_and_pages_dark_1280px.png` | `phase3_context_and_pages_dark_960px.png` | `phase3_context_and_pages_dark_720px.png` |
| **Phase 4** | Settings & Keybindings View | `phase4_settings_dark_1280px.png` | `phase4_settings_dark_960px.png` | `phase4_settings_dark_720px.png` |

---

## 6. User Hotkey & Navigation Quick Reference

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| `Ctrl + K` | **Search Conversations** | Focuses the search box in the left sidebar to quickly filter chat titles. |
| `Ctrl + N` | **New Chat** | Clears the active viewport and initializes a fresh conversation. |
| `Ctrl + B` | **Toggle Sidebar** | Collapses or expands the left conversation history sidebar. |
| `Ctrl + .` | **Toggle Context Panel** | Toggles the right drawer showing memories and telemetry. |
| `Ctrl + Shift + P` | **Cycle Privacy Mode** | Cycles through Standard → Local-Only → Private mode. |
| `Ctrl + Shift + Space`| **Summon / Hide Window** | Global desktop hotkey managed by pywebview shell to summon or minimize HINAKU. |
| `Esc` | **Stop Generation** | Aborts active streaming generation from the model router. |
| `Enter` | **Send Message** | Submits prompt to HINAKU. |
| `Shift + Enter` | **Newline** | Inserts a line break into the prompt composer without sending. |
