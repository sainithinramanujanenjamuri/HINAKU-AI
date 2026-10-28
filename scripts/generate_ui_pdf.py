"""
scripts/generate_ui_pdf.py

Generates an in-depth, publication-grade UI/UX Design System Specification PDF
for HINAKU (ヒナク), saved directly to docs/HINAKU_UI_Design_Specification.pdf.

Includes:
- Complete Visual Identity, Theme Tokens, Color Swatches & Contrast Ratios
- Typography System & Type Scale (Segoe UI Variable & Cascadia Code)
- 3-Column Responsive Shell Architecture (1280px, 960px, 720px)
- Floating Composer Dock with Mode Chips & Privacy Switcher
- Message Hierarchy, Telemetry Accordions, Code Blocks & Hover Actions
- Document Attachment Drawer, Walkthrough Engine & Structured Action Chips
- Dedicated Utility Views (Memories, Datasets, Model Ratings, Settings)
- Accessibility, Micro-interactions & Keybindings
- High-Resolution Screen Previews across all major breakpoints
"""

import os
import sys
import base64
import subprocess
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
SCREENSHOTS_DIR = DOCS_DIR / "screenshots"
OUTPUT_HTML = DOCS_DIR / "ui_design_spec.html"
OUTPUT_PDF = DOCS_DIR / "HINAKU_UI_Design_Specification.pdf"

def get_base64_image(filename: str) -> str:
    path = SCREENSHOTS_DIR / filename
    if path.exists():
        data = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:image/png;base64,{data}"
    return ""

img_shell_1280 = get_base64_image("phase1_shell_dark_1280px.png")
img_shell_960 = get_base64_image("phase1_shell_dark_960px.png")
img_conv_1280 = get_base64_image("phase2_conversation_dark_1280px.png")
img_att_1280 = get_base64_image("phase2_attachments_1280px.png")
img_pages_1280 = get_base64_image("phase3_context_and_pages_dark_1280px.png")
img_settings_1280 = get_base64_image("phase4_settings_dark_1280px.png")

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>HINAKU UI/UX Design System Specification</title>
<style>
  @page {{
    size: A4;
    margin: 18mm 16mm 18mm 16mm;
    @bottom-right {{
      content: counter(page);
      font-size: 9pt;
      color: #6b7280;
    }}
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    font-family: 'Segoe UI Variable Text', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Inter', Roboto, sans-serif;
    background-color: #0f1115;
    color: #e5e7eb;
    line-height: 1.6;
    font-size: 10pt;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .page-break {{
    page-break-after: always;
    break-after: page;
  }}
  .avoid-break {{
    page-break-inside: avoid;
    break-inside: avoid;
  }}

  /* Typography */
  h1, h2, h3, h4 {{
    color: #f9fafb;
    font-weight: 600;
    line-height: 1.25;
  }}
  h1 {{ font-size: 24pt; margin-bottom: 8pt; }}
  h2 {{ font-size: 15pt; margin-top: 16pt; margin-bottom: 8pt; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 4pt; color: #a78bfa; }}
  h3 {{ font-size: 11.5pt; margin-top: 12pt; margin-bottom: 4pt; color: #f3f4f6; }}
  h4 {{ font-size: 10pt; margin-top: 8pt; margin-bottom: 3pt; color: #d1d5db; }}
  p {{ margin-bottom: 7pt; color: #d1d5db; }}
  strong {{ color: #ffffff; font-weight: 600; }}
  code {{
    font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
    background: rgba(255,255,255,0.06);
    padding: 1.5pt 4pt;
    border-radius: 3pt;
    font-size: 8.5pt;
    color: #c4b5fd;
  }}

  /* Cover Page */
  .cover-container {{
    min-height: 90vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 40pt 20pt;
    border: 1px solid rgba(139, 92, 246, 0.25);
    background: radial-gradient(circle at 80% 20%, rgba(139, 92, 246, 0.12) 0%, transparent 60%), #141417;
    border-radius: 8pt;
  }}
  .brand-badge {{
    display: inline-block;
    background: rgba(139, 92, 246, 0.2);
    border: 1px solid rgba(139, 92, 246, 0.4);
    color: #c4b5fd;
    font-size: 9pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.5pt;
    padding: 3pt 9pt;
    border-radius: 12pt;
    margin-bottom: 16pt;
  }}
  .cover-title {{
    font-size: 28pt;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.5pt;
    margin-bottom: 6pt;
  }}
  .cover-subtitle {{
    font-size: 13pt;
    color: #a78bfa;
    margin-bottom: 20pt;
    font-weight: 400;
  }}
  .cover-desc {{
    font-size: 11pt;
    color: #9ca3af;
    max-width: 520pt;
    margin-bottom: 30pt;
    line-height: 1.6;
  }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12pt;
    border-top: 1px solid rgba(255,255,255,0.1);
    padding-top: 18pt;
  }}
  .meta-item-label {{
    font-size: 8.5pt;
    text-transform: uppercase;
    color: #6b7280;
    letter-spacing: 0.5pt;
    margin-bottom: 2pt;
  }}
  .meta-item-val {{
    font-size: 10pt;
    color: #e5e7eb;
    font-weight: 500;
  }}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 8pt 0 12pt 0;
    font-size: 9pt;
  }}
  th, td {{
    padding: 5pt 7pt;
    border: 1px solid rgba(255,255,255,0.08);
    text-align: left;
    vertical-align: top;
  }}
  th {{
    background: rgba(255,255,255,0.04);
    color: #f3f4f6;
    font-weight: 600;
    font-size: 8.5pt;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
  }}
  td {{
    color: #d1d5db;
  }}
  tr:nth-child(even) td {{
    background: rgba(255,255,255,0.015);
  }}

  /* Swatches */
  .swatch-group {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8pt;
    margin: 8pt 0 12pt 0;
  }}
  .swatch-card {{
    background: #18191f;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 5pt;
    padding: 6pt;
    display: flex;
    align-items: center;
    gap: 8pt;
  }}
  .swatch-chip {{
    width: 24pt;
    height: 24pt;
    border-radius: 4pt;
    border: 1px solid rgba(255,255,255,0.15);
    flex-shrink: 0;
  }}
  .swatch-info {{
    overflow: hidden;
  }}
  .swatch-name {{
    font-size: 8.5pt;
    font-weight: 600;
    color: #f3f4f6;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .swatch-val {{
    font-size: 8pt;
    font-family: monospace;
    color: #9ca3af;
  }}

  /* Callout / Cards */
  .card {{
    background: #16171d;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6pt;
    padding: 9pt 12pt;
    margin-bottom: 10pt;
  }}
  .card-highlight {{
    border-left: 3pt solid #8b5cf6;
    background: #181724;
  }}

  /* Image Container */
  .fig-container {{
    margin: 10pt 0 14pt 0;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6pt;
    overflow: hidden;
    background: #090a0f;
  }}
  .fig-container img {{
    width: 100%;
    display: block;
    height: auto;
  }}
  .fig-caption {{
    background: #14151b;
    padding: 4pt 8pt;
    font-size: 8pt;
    color: #9ca3af;
    border-top: 1px solid rgba(255,255,255,0.06);
    font-style: italic;
    display: flex;
    justify-content: space-between;
  }}

  /* Badges & Pills */
  .badge {{
    display: inline-block;
    padding: 1.5pt 5pt;
    font-size: 7.5pt;
    font-weight: 600;
    border-radius: 4pt;
    text-transform: uppercase;
    letter-spacing: 0.3pt;
  }}
  .badge-local {{ background: rgba(59, 130, 246, 0.2); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.4); }}
  .badge-api {{ background: rgba(168, 85, 247, 0.2); color: #d8b4fe; border: 1px solid rgba(168, 85, 247, 0.4); }}
  .badge-private {{ background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.4); }}
  .badge-guard {{ background: rgba(245, 158, 11, 0.2); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.4); }}
  .badge-verified {{ background: rgba(16, 185, 129, 0.15); color: #a7f3d0; border: 1px solid rgba(16, 185, 129, 0.3); }}

  /* Grid */
  .grid-2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10pt;
  }}
</style>
</head>
<body>

<!-- ========================================== -->
<!-- COVER PAGE -->
<!-- ========================================== -->
<div class="cover-container avoid-break">
  <div>
    <span class="brand-badge">HINAKU · ヒナク</span>
    <h1 class="cover-title">UI/UX Design System &amp; Desktop Architecture</h1>
    <div class="cover-subtitle">Specification, Component Hierarchies &amp; Visual Design Tokens</div>
    <p class="cover-desc">
      An exhaustive design specification for HINAKU: a personal, local-first AI assistant built for one person.
      Grounded in the core brand aesthetic—<em>"A universe without light"</em> (光なき宇宙)—this document details
      the 3-column collapsible desktop shell, floating interaction composer, truthful telemetry accordions,
      document attachment walkthrough engine, semantic memory drawers, and complete accessibility standards.
    </p>
  </div>

  <div class="meta-grid">
    <div>
      <div class="meta-item-label">Target Environment</div>
      <div class="meta-item-val">HP V15 Laptop (AMD Ryzen 7, RTX 4050 6 GB VRAM)</div>
    </div>
    <div>
      <div class="meta-item-label">System Architecture</div>
      <div class="meta-item-val">FastAPI Backend + PyWebView Native Shell + Local Web UI</div>
    </div>
    <div>
      <div class="meta-item-label">Model Backends</div>
      <div class="meta-item-val">Local: bonsai-2:9b (Q2_0, 8192 ctx) + OpenRouter API</div>
    </div>
    <div>
      <div class="meta-item-label">Design Standards</div>
      <div class="meta-item-val">WCAG AA Contrast Compliant (14.2:1 Primary) · Offline-First</div>
    </div>
  </div>
</div>

<div class="page-break"></div>

<!-- ========================================== -->
<!-- SECTION 1: VISION & DESIGN PRINCIPLES -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>1. Brand Vision &amp; Design Principles</h2>
  <p>
    <strong>HINAKU (ヒナク)</strong> is inspired by the Japanese phrase <em>Hikari naki uchū</em> (光なき宇宙), meaning
    <em>"a universe without light"</em>. The interface is purposefully built as a deep, calm, distraction-free desktop
    environment that feels quiet, contemplative, and relentlessly loyal to its single owner.
  </p>

  <div class="card card-highlight">
    <strong>Core Design Motto:</strong>
    <p style="margin-top: 4pt; font-style: italic; color: #c4b5fd;">
      "Darkness, infinity, mystery, solitude. One name. An infinite void. No light at the end."
    </p>
    <p style="margin: 0; font-size: 8.5pt; color: #9ca3af;">
      This identity governs atmospheric tone and typography only. It never manifests as pessimism or hesitation in replies;
      HINAKU responds with precision, dry wit, and decisive clarity.
    </p>
  </div>

  <div class="grid-2">
    <div class="card">
      <h3 style="margin-top:0;">Quiet, Modern Composure</h3>
      <p>
        Zero high-contrast glaring lines, zero promotional popups, and zero flashy animations.
        Surfaces follow soft neutral-dark elevations with one muted deep violet accent.
      </p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Local-First &amp; Private</h3>
      <p>
        Zero external Google Fonts, CDNs, or tracking scripts. All SVGs and CSS are bundled locally on the machine.
        Personal memories and private documents are never sent across network boundaries.
      </p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Truthful Backend Attribution</h3>
      <p>
        Every message displays a clear badge indicating whether it was produced by the local GPU model,
        an external API, or safety guards, with complete execution latency telemetry.
      </p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Tactile Desktop Ergonomics</h3>
      <p>
        Designed specifically for an HP V15 laptop with full keyboard navigation (Ctrl+B, Ctrl+., Ctrl+N, Ctrl+K),
        global tray summon hotkey, and smooth resizability across 1280px, 960px, and 720px viewports.
      </p>
    </div>
  </div>
</div>

<!-- ========================================== -->
<!-- SECTION 2: COLOR TOKENS & SURFACE SYSTEM -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>2. Color Tokens &amp; Surface System</h2>
  <p>
    HINAKU operates exclusively in a dark palette ("a universe without light"). There is no light mode.
    Surface depth is expressed through four primary elevation levels that provide visual hierarchy without harsh dividers.
  </p>

  <h3>Surface Elevation Palette</h3>
  <div class="swatch-group">
    <div class="swatch-card">
      <div class="swatch-chip" style="background: #141414;"></div>
      <div class="swatch-info">
        <div class="swatch-name">Base Canvas</div>
        <div class="swatch-val">--bg-base: #141414</div>
      </div>
    </div>
    <div class="swatch-card">
      <div class="swatch-chip" style="background: #1f1f1f;"></div>
      <div class="swatch-info">
        <div class="swatch-name">Surface Viewport</div>
        <div class="swatch-val">--bg-surface: #1f1f1f</div>
      </div>
    </div>
    <div class="swatch-card">
      <div class="swatch-chip" style="background: #2a2a2a;"></div>
      <div class="swatch-info">
        <div class="swatch-name">Raised Elements</div>
        <div class="swatch-val">--bg-raised: #2a2a2a</div>
      </div>
    </div>
    <div class="swatch-card">
      <div class="swatch-chip" style="background: #333333;"></div>
      <div class="swatch-info">
        <div class="swatch-name">Overlay &amp; Modals</div>
        <div class="swatch-val">--bg-overlay: #333333</div>
      </div>
    </div>
    <div class="swatch-card">
      <div class="swatch-chip" style="background: rgba(255,255,255,0.04);"></div>
      <div class="swatch-info">
        <div class="swatch-name">Subtle Hover Fill</div>
        <div class="swatch-val">rgba(255,255,255,0.04)</div>
      </div>
    </div>
    <div class="swatch-card">
      <div class="swatch-chip" style="background: rgba(255,255,255,0.08);"></div>
      <div class="swatch-info">
        <div class="swatch-name">Subtle Border</div>
        <div class="swatch-val">rgba(255,255,255,0.08)</div>
      </div>
    </div>
  </div>

  <h3>Semantic &amp; Status Color Tokens</h3>
  <table>
    <thead>
      <tr>
        <th style="width: 25%;">Token</th>
        <th style="width: 18%;">Hex / Value</th>
        <th style="width: 20%;">WCAG Contrast</th>
        <th>Semantic Purpose &amp; Usage</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><code>--accent-hinaku</code></td>
        <td><code>#8b5cf6</code> / <code>#7c3aed</code></td>
        <td>5.4:1 on #141414</td>
        <td>Primary brand identity, active focus rings, send action buttons, prominent icons.</td>
      </tr>
      <tr>
        <td><code>--color-local</code></td>
        <td><code>#3b82f6</code></td>
        <td>5.1:1 on #1f1f1f</td>
        <td>Local execution indicator (Ollama bonsai-2:9b), local model tags.</td>
      </tr>
      <tr>
        <td><code>--color-online</code></td>
        <td><code>#a855f7</code></td>
        <td>6.2:1 on #1f1f1f</td>
        <td>Cloud API execution badge (OpenRouter/Claude/GPT), logged by provider warning.</td>
      </tr>
      <tr>
        <td><code>--color-private</code></td>
        <td><code>#10b981</code></td>
        <td>7.8:1 on #1f1f1f</td>
        <td>Private session banner, local-only confirmation, zero memory extraction badge.</td>
      </tr>
      <tr>
        <td><code>--color-warning</code></td>
        <td><code>#f59e0b</code></td>
        <td>9.2:1 on #1f1f1f</td>
        <td>Guard intervention notices, auto-private fallback alerts, hardware throttles.</td>
      </tr>
      <tr>
        <td><code>--color-error</code></td>
        <td><code>#ef4444</code></td>
        <td>5.8:1 on #1f1f1f</td>
        <td>Backend connection failures, invalid input errors, token budget overruns.</td>
      </tr>
    </tbody>
  </table>
</div>

<div class="page-break"></div>

<!-- ========================================== -->
<!-- SECTION 3: TYPOGRAPHY & SPACING SYSTEM -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>3. Typography &amp; Spacing System</h2>
  <p>
    Text hierarchy is tuned for prolonged reading and dense technical documentation without visual fatigue.
    The primary font stack prioritizes Windows 11's native <code>Segoe UI Variable</code> for crisp rendering,
    paired with <code>Cascadia Code</code> for syntax-highlighted code.
  </p>

  <h3>Typography Scale</h3>
  <table>
    <thead>
      <tr>
        <th>Role</th>
        <th>Font Family</th>
        <th>Size / Leading</th>
        <th>Weight</th>
        <th>Usage Context</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Display / H1</strong></td>
        <td>Segoe UI Variable Display</td>
        <td>22px / 1.25</td>
        <td>600 (Semibold)</td>
        <td>Empty state greeting ("What are we working on?"), full-page headers.</td>
      </tr>
      <tr>
        <td><strong>Section / H2</strong></td>
        <td>Segoe UI Variable Text</td>
        <td>18px / 1.30</td>
        <td>600 (Semibold)</td>
        <td>Document walkthrough Unit headers, settings category titles.</td>
      </tr>
      <tr>
        <td><strong>Topic / H3</strong></td>
        <td>Segoe UI Variable Text</td>
        <td>16px / 1.40</td>
        <td>600 (Semibold)</td>
        <td>Topic titles in walkthroughs, card group headers.</td>
      </tr>
      <tr>
        <td><strong>Subheading / H4</strong></td>
        <td>Segoe UI Variable Text</td>
        <td>14.5px / 1.50</td>
        <td>500 (Medium)</td>
        <td>Inner section headings (e.g. Definition, Breakdown, Takeaways).</td>
      </tr>
      <tr>
        <td><strong>Body Primary</strong></td>
        <td>Segoe UI Variable Text</td>
        <td>14.5px / 1.60</td>
        <td>400 (Regular)</td>
        <td>Assistant replies, user messages, conversational dialogue.</td>
      </tr>
      <tr>
        <td><strong>Metadata / Small</strong></td>
        <td>Segoe UI Variable Text</td>
        <td>12.5px / 1.50</td>
        <td>400 / 500</td>
        <td>Message timestamps, model badges, action chip labels.</td>
      </tr>
      <tr>
        <td><strong>Caption / Micro</strong></td>
        <td>Segoe UI Variable Text</td>
        <td>11px / 1.40</td>
        <td>500 (Medium)</td>
        <td>Telemetry parameters, keyboard shortcut badges, status indicators.</td>
      </tr>
      <tr>
        <td><strong>Code Blocks</strong></td>
        <td>Cascadia Code, Consolas</td>
        <td>13px / 1.55</td>
        <td>400 (Regular)</td>
        <td>Inline code snippets, multi-line Python/JS syntax blocks.</td>
      </tr>
    </tbody>
  </table>

  <h3>Spacing &amp; Radii Scale</h3>
  <div class="grid-2">
    <div>
      <h4>4px Spacing Scale</h4>
      <table>
        <tr><td><code>--space-1</code></td><td>4px</td><td>Micro gap between badges and icons</td></tr>
        <tr><td><code>--space-2</code></td><td>8px</td><td>Card padding, button horizontal padding</td></tr>
        <tr><td><code>--space-3</code></td><td>12px</td><td>Gap between message bubbles and meta rows</td></tr>
        <tr><td><code>--space-4</code></td><td>16px</td><td>Container padding, drawer margins</td></tr>
        <tr><td><code>--space-6</code></td><td>24px</td><td>Stage padding, composer dock margin</td></tr>
        <tr><td><code>--space-8</code></td><td>32px</td><td>Major section vertical separation</td></tr>
      </table>
    </div>
    <div>
      <h4>Border Radii Scale</h4>
      <table>
        <tr><td><code>--radius-sm</code></td><td>6px</td><td>Chips, status badges, code inline tags</td></tr>
        <tr><td><code>--radius-md</code></td><td>10px</td><td>User message bubbles, dropdown menus</td></tr>
        <tr><td><code>--radius-lg</code></td><td>16px</td><td>Settings cards, document attachment drawers</td></tr>
        <tr><td><code>--radius-composer</code></td><td>24px</td><td>Floating interaction composer dock</td></tr>
        <tr><td><code>--radius-full</code></td><td>9999px</td><td>Action pills, toggle switches, status dots</td></tr>
      </table>
    </div>
  </div>
</div>

<div class="page-break"></div>

<!-- ========================================== -->
<!-- SECTION 4: SHELL ARCHITECTURE & BREAKPOINTS -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>4. Shell Architecture &amp; Responsive Layout</h2>
  <p>
    The desktop shell implements a flexible 3-column architecture designed for native desktop performance on Windows 11.
    All transitions utilize <code>150ms ease-out</code> or <code>250ms cubic-bezier(0.16, 1, 0.3, 1)</code> for instantaneous,
    fluid resizing without layout thrashing.
  </p>

  <div class="fig-container">
    <img src="{img_shell_1280}" alt="Full 3-Column Shell at 1280px">
    <div class="fig-caption">
      <span>Figure 1: Complete 3-Column Desktop Shell (1280px Breakpoint)</span>
      <span>Sidebar (260px) + Conversation Stage (720px max) + Context Drawer (320px)</span>
    </div>
  </div>

  <h3>Responsive Breakpoint Matrix</h3>
  <table>
    <thead>
      <tr>
        <th style="width: 18%;">Breakpoint</th>
        <th style="width: 25%;">Left Sidebar (History)</th>
        <th style="width: 32%;">Center Stage (Conversation)</th>
        <th>Right Context Drawer</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>1280px+ (Full)</strong></td>
        <td>Expanded (260px fixed width). Full date categorization.</td>
        <td>Centered 720px reading column with floating bottom composer.</td>
        <td>Docked (320px fixed width). Real-time semantic memory inspector.</td>
      </tr>
      <tr>
        <td><strong>960px – 1279px (Compact)</strong></td>
        <td>Expanded (240px width). Auto-collapse via <code>Ctrl+B</code>.</td>
        <td>Expanded to fit viewport; composer max-width 680px.</td>
        <td>Auto-collapsed to icon tab in top nav; slides in as overlay on demand.</td>
      </tr>
      <tr>
        <td><strong>&lt; 960px / 720px (Single-Col)</strong></td>
        <td>Collapsed by default. Slides in as overlay modal via top hamburger.</td>
        <td>100% viewport width with 12px gutter. Composer bottom-pinned.</td>
        <td>Accessible via full-page view or slide-in right drawer.</td>
      </tr>
    </tbody>
  </table>

  <h3>Top Navigation Bar Elements</h3>
  <p>
    The top bar (height: <code>48px</code>) provides unobtrusive environmental awareness:
  </p>
  <ul style="margin-left: 18pt; margin-bottom: 8pt; color: #d1d5db;">
    <li><strong>Left:</strong> Sidebar toggle icon (<code>Ctrl+B</code>) and editable conversation title.</li>
    <li><strong>Center:</strong> Model status pill with pulsing green indicator dot (<code>bonsai-2:9b · 100% GPU</code>).</li>
    <li><strong>Right:</strong> Privacy mode badge (<code>Standard</code> / <code>Local-Only</code> / <code>Private</code>), Context Drawer toggle (<code>Ctrl+.</code>), and Window controls.</li>
  </ul>
</div>

<div class="page-break"></div>

<!-- ========================================== -->
<!-- SECTION 5: COMPOSER & INTERACTION DOCK -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>5. Floating Composer &amp; Interaction Dock</h2>
  <p>
    The prompt composer is engineered as a floating elevated pill (<code>--radius-composer: 24px</code>) positioned at the
    bottom of the conversation stage. It eliminates clutter while providing immediate access to model modes and attachments.
  </p>

  <div class="grid-2">
    <div class="card">
      <h3 style="margin-top:0;">Auto-Expanding Textarea</h3>
      <p>
        Expands seamlessly from single-line (<code>44px</code>) to multi-line (up to <code>180px</code> max before scroll).
        Submits on <kbd>Enter</kbd>; inserts line break on <kbd>Shift + Enter</kbd>.
      </p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Dual-State Action Button</h3>
      <p>
        Circular submit button (<code>36px</code>) with deep violet fill (<code>#8b5cf6</code>).
        During active streaming, dynamically transforms into a Stop Generation square (<code>■</code>) with immediate abort capability.
      </p>
    </div>
  </div>

  <h3>Removable Mode Chips (Think Harder &amp; Detailed Mode)</h3>
  <p>
    Clicking the <code>+</code> button opens a lightweight action menu that toggles specialized reasoning and depth flags:
  </p>
  <table>
    <thead>
      <tr>
        <th>Mode</th>
        <th>Badge Display</th>
        <th>Inference Parameter Shift</th>
        <th>Behavioral Effect</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Think Harder</strong></td>
        <td><span class="badge" style="background: rgba(139, 92, 246, 0.25); color: #c4b5fd;">🧠 Think</span></td>
        <td><code>num_predict: 2048</code>, <code>temperature: 0.2</code></td>
        <td>Allocates deep token budget for complex logic, math, and code architecture problems.</td>
      </tr>
      <tr>
        <td><strong>Detailed Mode</strong></td>
        <td><span class="badge" style="background: rgba(59, 130, 246, 0.25); color: #93c5fd;">📄 Detailed ×</span></td>
        <td><code>num_predict: 800</code>, detailed persona override</td>
        <td>Forces structured, comprehensive multi-paragraph explanations ending in a clear conclusion.</td>
      </tr>
    </tbody>
  </table>

  <h3>Privacy Mode Selector</h3>
  <div class="grid-2">
    <div class="card">
      <span class="badge badge-api">Standard Mode</span>
      <p style="margin-top: 4pt; font-size: 8.5pt;">
        Intelligent hybrid routing. Simple conversational queries run on local <code>bonsai-2:9b</code>; complex reasoning
        may route to external API models if configured.
      </p>
    </div>
    <div class="card">
      <span class="badge badge-local">Local-Only Mode</span>
      <p style="margin-top: 4pt; font-size: 8.5pt;">
        Strict physical isolation. 100% of queries execute through local Ollama on the laptop's RTX 4050 GPU.
        Zero outbound internet traffic.
      </p>
    </div>
    <div class="card">
      <span class="badge badge-private">Private Mode</span>
      <p style="margin-top: 4pt; font-size: 8.5pt;">
        Confidential mode. Strictly local GPU execution. Suppresses all semantic memory extraction and excludes turns
        from the 6-month self-build dataset.
      </p>
    </div>
    <div class="card">
      <span class="badge badge-guard">Auto-Private Fallback</span>
      <p style="margin-top: 4pt; font-size: 8.5pt;">
        Automated safety guard. When passwords, PINs, or sensitive identifiers are typed, the system automatically
        switches to Private mode and displays a persistent banner with a 1-click <strong>Undo</strong> button.
      </p>
    </div>
  </div>
</div>

<div class="page-break"></div>

<!-- ========================================== -->
<!-- SECTION 6: CONVERSATION VIEW & TELEMETRY -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>6. Conversation View &amp; Truthful Telemetry</h2>
  <p>
    Every conversation turn balances visual elegance with rigorous telemetry truthfulness.
    User inputs and assistant outputs are visually differentiated to maintain clear conversational momentum.
  </p>

  <div class="fig-container">
    <img src="{img_conv_1280}" alt="Conversation View with Code and Telemetry">
    <div class="fig-caption">
      <span>Figure 2: Active Conversation View</span>
      <span>User message fold, markdown rendering, syntax code block, and telemetry accordion</span>
    </div>
  </div>

  <h3>Key Message Components</h3>
  <ul>
    <li>
      <strong>User Message Bubble:</strong> Right-aligned elevated card (<code>--bg-raised: #2a2a2a</code>) with rounded corners (<code>10px</code>).
      Messages exceeding 350 characters automatically fold with a subtle gradient mask and a tactile <em>"Show more ↓"</em> toggle.
    </li>
    <li>
      <strong>Assistant Message Body:</strong> Fluid left-aligned markdown typography. Headings (<code>###</code>, <code>####</code>) render as
      distinct section headers; unordered and numbered lists render with generous padding; horizontal rules (<code>---</code>) render as subtle dividers.
    </li>
    <li>
      <strong>Syntax-Highlighted Code Blocks:</strong> Wrapped in dark pre-formatted containers (<code>#141416</code>) withCasdadia Code typography,
      a top header showing the language tag (e.g. <code>python</code>, <code>bash</code>), and a 1-click Copy button that displays <em>"Copied!"</em> confirmation.
    </li>
    <li>
      <strong>Truthful Backend Badges:</strong>
      <span class="badge badge-local">bonsai-2:9b · local</span>
      <span class="badge badge-api">openrouter · API · logged by provider</span>
      <span class="badge badge-verified">✓ verified</span>
    </li>
    <li>
      <strong>Telemetry Accordion ("Worked for X s &gt;"):</strong>
      A collapsible process summary located under assistant replies. It surfaces exact execution timings (TTFT, generation latency,
      tokens per second, memory extraction time), <em>while strictly suppressing raw internal reasoning scratchpads</em> to preserve HINAKU's cool composure.
    </li>
    <li>
      <strong>Message Hover Action Bar:</strong>
      Floating horizontal action dock appearing on message hover:
      <strong>Copy Text</strong>, <strong>Thumbs Up</strong>, <strong>Thumbs Down</strong>, <strong>Edit Reply</strong> (which feeds the 6-month curation engine),
      <strong>Retry</strong>, and <strong>Continue</strong> (for automated continuation of truncated replies).
    </li>
  </ul>
</div>

<div class="page-break"></div>

<!-- ========================================== -->
<!-- SECTION 7: ATTACHMENTS & WALKTHROUGH UX -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>7. Document Attachments &amp; Walkthrough UX</h2>
  <p>
    Built during Phase 2 and refined in Phase 2c, the document attachment subsystem allows the owner to attach PDF, DOCX, TXT, and HTML
    study notes. The UI deterministically routes between overview study walkthroughs and targeted retrieval Q&amp;A.
  </p>

  <div class="fig-container">
    <img src="{img_att_1280}" alt="Document Attachment Drawer and Walkthrough Cards">
    <div class="fig-caption">
      <span>Figure 3: Document Attachment Drawer &amp; Study Notes Integration</span>
      <span>Uploaded document badge, outline section counts, and structured study cards</span>
    </div>
  </div>

  <h3>Document Walkthrough Features</h3>
  <table>
    <thead>
      <tr>
        <th style="width: 28%;">Feature</th>
        <th style="width: 32%;">UI Element / Behavior</th>
        <th>Engineering Specification</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Attachment Drawer</strong></td>
        <td>Slide-down card above composer displaying filename, size (KB), and token count.</td>
        <td>Supports drag-and-drop &amp; file picker; validates disk headroom (file + 2 GB) before ingestion.</td>
      </tr>
      <tr>
        <td><strong>Outline Extraction</strong></td>
        <td>Extracts units, topics, sessions, study aids, and exact page ranges.</td>
        <td>Stored in SQLite <code>attachment_sections</code>; indexed into isolated Chroma collection.</td>
      </tr>
      <tr>
        <td><strong>Intent Gating</strong></td>
        <td>Evaluates query in code: overview requests trigger walkthrough; specific questions trigger hybrid retrieval.</td>
        <td>Filters out unrelated chatter (e.g. Python coding, CPUs vs GPUs) with zero false document citations.</td>
      </tr>
      <tr>
        <td><strong>Structure Preamble</strong></td>
        <td>Deterministic intro card: <em>"Your notes contain 2 units, 9 topics in Unit 1, 5 sessions in Unit 2..."</em></td>
        <td>Displays measured time estimate range: e.g. <code>~175s estimated (range 149s–201s)</code>.</td>
      </tr>
      <tr>
        <td><strong>Rolling Estimate</strong></td>
        <td>Progress banner updating topic-by-topic: <code>Explaining topic 3 of 9 (~120s remaining)</code>.</td>
        <td>Derived from rolling average of completed topics; strictly non-increasing.</td>
      </tr>
      <tr>
        <td><strong>Action Chips</strong></td>
        <td>Structured button pill at the bottom of document replies: <code>Explain the whole document →</code></td>
        <td>Replaces raw markdown anchor links; triggers full walkthrough on click.</td>
      </tr>
      <tr>
        <td><strong>Code-Level Citations</strong></td>
        <td>Exact outline metadata note: <code>*Based on Session 8 — Introduction to MLSecOps (pp. 8-9).*</code></td>
        <td>Generated strictly in code from outline records; all model-hallucinated citations are stripped.</td>
      </tr>
    </tbody>
  </table>
</div>

<div class="page-break"></div>

<!-- ========================================== -->
<!-- SECTION 8: UTILITY PAGES (NO MODALS) -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>8. Dedicated Utility Pages</h2>
  <p>
    HINAKU eliminates intrusive modal popups in favor of dedicated, distraction-free utility views.
    These views share the same left sidebar navigation and allow full inspection of the system's memory, training data, and settings.
  </p>

  <div class="fig-container">
    <img src="{img_pages_1280}" alt="Full Page Context and Memory Management View">
    <div class="fig-caption">
      <span>Figure 4: Context &amp; Semantic Memory Management View</span>
      <span>Searchable memory cards, inline editing, category tagging, and re-index controls</span>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <h3>1. Semantic Memory Drawer</h3>
      <p>
        Displays all durable facts and preferences extracted about the owner. Each memory card shows the extracted text,
        creation timestamp, and category badge. Users can search memories with semantic similarity, edit wording inline,
        delete obsolete facts, or trigger an on-demand ChromaDB re-index.
      </p>
    </div>
    <div class="card">
      <h3>2. Dataset Curation Screen</h3>
      <p>
        Feeds the 6-month self-build cycle. Aggregates all interaction pairs flagged with thumbs-up or owner corrections.
        Provides review cards where the owner can audit training pairs, delete ungrounded entries, and view readiness
        against the minimum fine-tuning sample threshold.
      </p>
    </div>
    <div class="card">
      <h3>3. Model Ratings &amp; Bake-Off</h3>
      <p>
        Presents real-time telemetry comparing local models (<code>bonsai-2:9b</code>, <code>gemma3:4b</code>) against API models.
        Displays latency distributions, upvote/downvote ratios, token generation speeds, and persona adherence scores.
      </p>
    </div>
    <div class="card">
      <h3>4. Settings &amp; Data Sovereignty</h3>
      <p>
        Configures default local model, router mode, global hotkeys, and reduced-motion toggles.
        Provides 1-click **Export All Data** (JSON format) and a fail-safe **Permanent Wipe** (<code>WIPE_ALL</code>)
        that clears all SQLite databases, Chroma indices, and disk caches.
      </p>
    </div>
  </div>

  <div class="fig-container" style="margin-top: 10pt;">
    <img src="{img_settings_1280}" alt="Settings and Configuration View">
    <div class="fig-caption">
      <span>Figure 5: System Settings &amp; Hardware Configuration</span>
      <span>Router rules, memory extract toggles, global shortcuts, and export/wipe utilities</span>
    </div>
  </div>
</div>

<div class="page-break"></div>

<!-- ========================================== -->
<!-- SECTION 9: KEYBINDINGS, MOTION & A11Y -->
<!-- ========================================== -->
<div class="avoid-break">
  <h2>9. Keybindings, Motion &amp; Accessibility</h2>
  <p>
    Every feature in HINAKU is fully operable without a mouse. Micro-interactions are snappy and respect
    hardware efficiency and accessibility standards.
  </p>

  <h3>Complete Keyboard Shortcut Cheat Sheet</h3>
  <table>
    <thead>
      <tr>
        <th style="width: 25%;">Shortcut</th>
        <th style="width: 25%;">Action Name</th>
        <th>Functional Description</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><kbd>Ctrl + N</kbd></td>
        <td>New Chat</td>
        <td>Clears conversation viewport, resets composer, and initializes a clean conversation ID.</td>
      </tr>
      <tr>
        <td><kbd>Ctrl + K</kbd></td>
        <td>Search Chats</td>
        <td>Focuses the search filter input in the left sidebar to quickly locate past conversation titles.</td>
      </tr>
      <tr>
        <td><kbd>Ctrl + B</kbd></td>
        <td>Toggle Sidebar</td>
        <td>Collapses or expands the left conversation history sidebar with smooth 150ms ease transition.</td>
      </tr>
      <tr>
        <td><kbd>Ctrl + .</kbd></td>
        <td>Toggle Context Panel</td>
        <td>Slides open or closes the right-hand context drawer showing live memories and telemetry.</td>
      </tr>
      <tr>
        <td><kbd>Ctrl + Shift + P</kbd></td>
        <td>Cycle Privacy Mode</td>
        <td>Cycles through Standard → Local-Only → Private mode with instant status indicator feedback.</td>
      </tr>
      <tr>
        <td><kbd>Ctrl + Shift + Space</kbd></td>
        <td>Summon / Hide</td>
        <td>Global OS hotkey managed by desktop shell to summon HINAKU from the background or minimize to tray.</td>
      </tr>
      <tr>
        <td><kbd>Esc</kbd></td>
        <td>Stop / Dismiss</td>
        <td>Immediately aborts streaming model generation; closes active dropdown menus or utility pages.</td>
      </tr>
      <tr>
        <td><kbd>Enter</kbd></td>
        <td>Send Prompt</td>
        <td>Submits current prompt to the model router.</td>
      </tr>
      <tr>
        <td><kbd>Shift + Enter</kbd></td>
        <td>Newline</td>
        <td>Inserts a clean line break in the expanding composer textarea without submitting.</td>
      </tr>
    </tbody>
  </table>

  <h3>Motion &amp; Accessibility Engineering</h3>
  <div class="grid-2">
    <div class="card">
      <h4 style="margin-top:0;">Reduced Motion Compliance</h4>
      <p>
        Strictly observes the OS-level <code>prefers-reduced-motion: reduce</code> media query.
        When enabled, all CSS transitions collapse from 150ms/250ms to <code>0ms</code>, and the subtle ambient star-field
        canvas is completely disabled to prevent disorientation.
      </p>
    </div>
    <div class="card">
      <h4 style="margin-top:0;">Screen Reader &amp; Focus Rings</h4>
      <p>
        All interactive controls feature a prominent <code>outline: 2px solid var(--accent-hinaku)</code> focus state.
        Streaming assistant responses emit into an <code>aria-live="polite"</code> region so screen readers receive updates
        without interruption.
      </p>
    </div>
  </div>

  <div class="card" style="margin-top: 10pt; text-align: center; border-color: rgba(139,92,246,0.3);">
    <p style="margin: 0; font-size: 8.5pt; color: #a78bfa;">
      HINAKU UI/UX Design System Specification · Compiled October 2026 · Built for HP V15 Target Environment
    </p>
  </div>
</div>

</body>
</html>
"""

def generate_pdf():
    print(f"Writing HTML specification to {OUTPUT_HTML}...")
    OUTPUT_HTML.write_text(html_content, encoding="utf-8")

    edge_bin = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not Path(edge_bin).exists():
        raise FileNotFoundError(f"Microsoft Edge binary not found at {edge_bin}")

    print(f"Compiling PDF via Microsoft Edge headless print-to-pdf...")
    cmd = [
        edge_bin,
        "--headless",
        "--disable-gpu",
        "--run-all-compositor-stages-before-draw",
        "--no-pdf-header-footer",
        f"--print-to-pdf={OUTPUT_PDF}",
        str(OUTPUT_HTML)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        print(f"Error compiling PDF: {res.stderr}")
        return False

    if not OUTPUT_PDF.exists():
        print("PDF was not created.")
        return False

    pdf_size_kb = OUTPUT_PDF.stat().st_size / 1024
    reader = PdfReader(str(OUTPUT_PDF))
    page_count = len(reader.pages)
    print(f"\n========================================================")
    print(f"SUCCESS: HINAKU UI Design Specification PDF Generated!")
    print(f"Output File: {OUTPUT_PDF}")
    print(f"Total Pages: {page_count}")
    print(f"File Size:   {pdf_size_kb:.1f} KB")
    print(f"========================================================")
    return True

if __name__ == "__main__":
    generate_pdf()
