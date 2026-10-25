# HINAKU UI/UX Design System (`docs/UI_DESIGN.md`)

## 1. Vision & Identity
**HINAKU (ヒナク)**: Inspired by *Hikari naki uchū* (光なき宇宙) — "a universe without light".
- **Brand Mood**: Darkness, infinity, quiet focus, solitude, precision.
- **Visual Principle**: Calm, modern, uncluttered, desktop-native. High information density when needed, zero fluff.
- **Offline & Private**: Zero external network fonts, CDNs, or telemetry. All SVGs and assets bundled locally.

---

## 2. Color Tokens & Surface Hierarchy

Surfaces follow a neutral warm-dark progression designed to reduce eye strain and provide depth without harsh contrast boundaries:

### Dark Theme (Sole Theme — "A Universe Without Light")
| Token | Value | Purpose |
| :--- | :--- | :--- |
| `--bg-base` | `#141414` / `#171717` | Root application canvas, outer window frame |
| `--bg-surface` | `#1f1f1f` / `#212121` | Sidebar, main conversation background |
| `--bg-raised` | `#2a2a2a` / `#2b2b2b` | Composer container, dropdown menus, cards |
| `--bg-overlay` | `#333333` | Modal dialogs, floating tooltips, active hover states |
| `--bg-subtle` | `rgba(255, 255, 255, 0.04)` | Item hover, inactive pill background |
| `--border-subtle` | `rgba(255, 255, 255, 0.08)` | Dividers, subtle input borders |
| `--border-focus` | `rgba(255, 255, 255, 0.22)` | Focus rings, highlighted boundaries |

### Typography & Text Tokens
All text meets **WCAG AA contrast standards** (minimum 4.5:1 for body copy):
- `--text-primary`: `#f3f4f6` (soft cool-white on dark)
- `--text-secondary`: `#9ca3af` (muted captions, metadata labels)
- `--text-tertiary`: `#6b7280` (timestamps, subtle placeholders)
- `--text-inverse`: `#111827` (on bright badges)

### Semantic & Accent Colors
- `--accent-hinaku`: `#8b5cf6` / `#7c3aed` (Muted violet, brand personality)
- `--color-local`: `#3b82f6` (Blue, local Ollama execution)
- `--color-online`: `#a855f7` (Violet, API model logged by provider)
- `--color-private`: `#10b981` (Emerald green, strictly local, zero memory/logging)
- `--color-warning`: `#f59e0b` (Amber, fallback/guard alerts)
- `--color-error`: `#ef4444` (Crimson red, offline/unreachable notices)

---

## 3. Typography Stack & Scale

- **Primary Font Stack**: `Segoe UI Variable`, `Segoe UI`, -apple-system, BlinkMacSystemFont, `Inter`, sans-serif
- **Monospace Code Stack**: `Cascadia Code`, `Fira Code`, `Consolas`, monospace
- **Body Size**: `14.5px` with a line height of `1.6`
- **Scale**:
  - `Caption`: `11px` / `1.4`
  - `Small / Meta`: `12.5px` / `1.5`
  - `Body`: `14.5px` / `1.6`
  - `Header 3`: `16px` / `1.4` (Medium/Semibold)
  - `Header 2`: `18px` / `1.3` (Semibold)
  - `Header 1`: `22px` / `1.2` (Bold)

---

## 4. Spacing, Geometry & Radii

A strict **4px spacing grid**:
- Spacers: `4px` (`--space-1`), `8px` (`--space-2`), `12px` (`--space-3`), `16px` (`--space-4`), `24px` (`--space-6`), `32px` (`--space-8`).
- Radii:
  - `--radius-sm`: `6px` (badges, chips)
  - `--radius-md`: `10px` (buttons, dropdown menus, user bubbles)
  - `--radius-lg`: `16px` (dialogs, cards)
  - `--radius-composer`: `24px` (pill-shaped rounded modern composer)
- Max Chat Content Width: `720px` centered for optimal readability.

---

## 5. Layout & Key Component Patterns

### A. Slim Left Sidebar (Collapsible)
- Width: `260px` desktop expanded; `0px` collapsed (drawer below `720px`).
- Header: New Chat (`+ New chat` / `Ctrl+N`), Search (`Ctrl+K`).
- Conversation List grouped into date sections:
  1. *Today*
  2. *Yesterday*
  3. *Previous 7 days*
  4. *Older*
- Conversation item actions: Pin, Rename, Delete (with inline confirmation).
- Footer Navigation: Memory, Dataset, Settings, Offline/Model Status indicator.

### B. Top Navigation Bar
- Left: Toggle sidebar button (`Ctrl+B`), active chat editable title.
- Center/Right: Privacy mode chip (`Standard` / `Local only` / `Private`), Model selector chip, Connection status dot, Toggle Context Panel button (`Ctrl+.`).

### C. Empty State
- Subtle HINAKU monochrome mark with faint ambient glow.
- Single quiet greeting: *"What are we working on?"*
- Centered composer card. Clean, no loud promotional clutter.

### D. Modern Composer Card
- Border radius: `24px`, background: `--bg-raised`, subtle border.
- Expanding textarea (Shift+Enter for newline, Enter to send).
- Left-side `+` menu containing:
  - Toggle **Think harder** (active chip shows above/inside composer).
  - Toggle **Detailed mode** (active chip shows above/inside composer).
  - *Skills* (coming soon — disabled).
  - *Attach file* (coming soon — disabled).
- Bottom Toolbar:
  - Privacy chip with explanatory dropdown:
    - **Standard**: May use API for complex queries (logged by provider).
    - **Local only**: Never leaves this machine (Ollama local).
    - **Private**: Local only, no memory storage, no dataset training.
  - Model picker chip with loading indication (`loading model... ~15s`).
  - Mic icon (disabled placeholder, voice planned later).
  - Send button (dynamically switches to Stop generation button while streaming).

### E. Conversation View
- User message: soft tinted bubble aligned to right/center max 720px, timestamp + copy/edit on hover, "Show more" fold for long inputs.
- Assistant message: clean markdown typography, syntax-highlighted code blocks with language tag and copy button.
- Process line: `"Worked for X s >"` collapsible accordion. **Never reveals raw CoT / reasoning tokens**; only surfaces process telemetry (guards verified, route chosen, memories referenced with links, elapsed seconds, post-processing filters applied).
- Meta row under replies: Model name, Backend indicator (`local` / `API - logged by provider` / `guard`), Quality badge (`verified` / `corrected`).
- Action bar on hover: Copy, Thumbs Up, Thumbs Down, Edit, Retry, Continue.

---

## 6. Motion & Accessibility

- Transitions: `150ms` ease-out (`--transition-fast`), `250ms` cubic-bezier (`--transition-standard`).
- Respects `prefers-reduced-motion: reduce` (sets durations to `0ms`).
- Star-field ambient canvas is optional, off by default, and automatically disabled when reduced-motion is requested.
- Keyboard navigation:
  - `Ctrl + K`: Focus chat search
  - `Ctrl + N`: New chat
  - `Ctrl + Shift + P`: Cycle Privacy Mode
  - `Ctrl + B`: Toggle Sidebar
  - `Ctrl + .`: Toggle Context Panel
  - `Esc`: Stop generation / dismiss modals
  - `Enter`: Send message
  - `Shift + Enter`: Multi-line break
- High-contrast focus rings (`outline: 2px solid var(--accent-hinaku)`).
- ARIA live regions for streaming assistant responses.

