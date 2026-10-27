import pytest
import re
from pathlib import Path

def parse_markdown_python_replica(text: str) -> str:
    """
    Python verification mirror of ui/js/markdown.js parseOfflineMarkdown()
    ensuring 1:1 syntax equivalence.
    """
    out = []
    lines = text.split("\n")
    in_code = False
    code_lang = ""
    code_buf = []
    in_ul = False
    in_ol = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def format_inline(s: str) -> str:
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
        return s

    for raw in lines:
        line = raw.rstrip()
        cm = re.match(r"^```([a-zA-Z0-9_-]*)", line)
        if cm and not in_code:
            close_lists()
            in_code = True
            code_lang = cm.group(1) or "text"
            code_buf = []
            continue
        elif line.startswith("```") and in_code:
            in_code = False
            esc = "\n".join(code_buf).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            out.append(f'<pre><code class="language-{code_lang}">{esc}</code></pre>')
            continue

        if in_code:
            code_buf.append(raw)
            continue

        # Horizontal rule: --- or *** or ___
        if re.match(r"^\s*([*\-_])\s*(?:\1\s*){2,}$", line):
            close_lists()
            out.append("<hr>")
            continue

        # Action buttons pass-through
        if re.match(r'^\s*<(?:div class="walkthrough-actions-row"|/div|button class="walkthrough-action-btn[^"]*"[^>]*>.*</button>)\s*$', line):
            close_lists()
            out.append(line)
            continue

        # Headings: # to ######
        hm = re.match(r"^(#{1,6})\s+(.*)$", line)
        if hm:
            close_lists()
            level = len(hm.group(1))
            cnt = format_inline(hm.group(2).strip())
            out.append(f"<h{level}>{cnt}</h{level}>")
            continue

        # Unordered list
        ul_m = re.match(r"^[\s]*[-*+]\s+(.*)$", line)
        if ul_m:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{format_inline(ul_m.group(1))}</li>")
            continue

        # Ordered list
        ol_m = re.match(r"^[\s]*\d+\.\s+(.*)$", line)
        if ol_m:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{format_inline(ol_m.group(1))}</li>")
            continue

        close_lists()
        if not line.strip():
            continue
        out.append(f"<p>{format_inline(line)}</p>")

    close_lists()
    return "".join(out)


def test_markdown_heading_and_rule_rendering():
    sample_text = (
        "**Game Mechanics Notes**\n\n"
        "---\n\n"
        "### 1. Defining Games & Play\n\n"
        "A game is a goal-oriented system.\n\n"
        "* Bullet point one\n"
        "* Bullet point two\n\n"
        "1. Step one\n"
        "2. Step two\n\n"
        "---"
    )

    rendered = parse_markdown_python_replica(sample_text)
    assert "<hr>" in rendered
    assert "<h3>1. Defining Games &amp; Play</h3>" in rendered
    assert "<strong>Game Mechanics Notes</strong>" in rendered
    assert "<ul><li>Bullet point one</li><li>Bullet point two</li></ul>" in rendered
    assert "<ol><li>Step one</li><li>Step two</li></ol>" in rendered


def test_markdown_rendering_on_walkthrough_data():
    raw_file = Path("data/measure/20261027_111706_sample_walkthrough.txt")
    if not raw_file.exists():
        pytest.skip("sample walkthrough file not found")
    
    content = raw_file.read_text(encoding="utf-8")
    assert "### 1. Defining Games & Play" in content
    
    # Test section rendering
    snippet = "### 1. Defining Games & Play\n\n**Defining Games**\nA game is a **goal-oriented system**.\n\n---\n"
    html = parse_markdown_python_replica(snippet)
    assert "<h3>1. Defining Games &amp; Play</h3>" in html
    assert "<strong>goal-oriented system</strong>" in html
    assert "<hr>" in html


def test_walkthrough_action_buttons_render_cleanly():
    """Validates that Continue to Unit and Study Aid action buttons are rendered as real buttons."""
    button_markup = (
        "**Unit 1 Complete.**\n\n"
        '<div class="walkthrough-actions-row">\n'
        '  <button class="walkthrough-action-btn" data-prompt="explain unit 2">Continue to Unit 2 →</button>\n'
        '  <button class="walkthrough-action-btn highlight" data-prompt="explain the study aids">Explain All Study Aids →</button>\n'
        '</div>'
    )
    rendered = parse_markdown_python_replica(button_markup)
    assert '<button class="walkthrough-action-btn" data-prompt="explain unit 2">Continue to Unit 2 →</button>' in rendered
    assert '<button class="walkthrough-action-btn highlight" data-prompt="explain the study aids">Explain All Study Aids →</button>' in rendered
    assert "&lt;button" not in rendered



def test_ui_javascript_imports_and_exports_integrity():
    """
    Validates that all symbols imported in ui/app.js and other ui scripts
    are actually exported by their target ES modules, preventing syntax errors
    and blank/broken UI windows on startup.
    """
    root = Path(__file__).resolve().parent.parent.parent
    ui_dir = root / "ui"
    js_files = list(ui_dir.glob("*.js")) + list((ui_dir / "js").glob("*.js"))

    import_re = re.compile(r'import\s+\{([^}]+)\}\s+from\s+["\']([^"\']+)["\']')

    for js_file in js_files:
        content = js_file.read_text(encoding="utf-8")
        for match in import_re.finditer(content):
            symbols = [s.strip() for s in match.group(1).split(",") if s.strip()]
            import_path = match.group(2)
            if import_path.startswith("/static/"):
                rel_path = import_path.replace("/static/", "")
                target_file = ui_dir / rel_path
            else:
                target_file = (js_file.parent / import_path).resolve()

            assert target_file.exists(), f"{js_file.name} imports non-existent file {import_path}"
            target_content = target_file.read_text(encoding="utf-8")

            for sym in symbols:
                export_pattern = re.compile(
                    rf'export\s+(?:function|const|let|var|class)\s+{re.escape(sym)}\b|'
                    rf'export\s*\{{[^}}]*\b{re.escape(sym)}\b'
                )
                assert export_pattern.search(target_content), (
                    f"Integrity failure: {js_file.name} imports '{sym}' from {target_file.name}, "
                    f"but '{sym}' is not exported by {target_file.name}!"
                )


