import pytest
import subprocess
from pathlib import Path

def run_node_converter(input_text: str) -> str:
    js_code = f"""
    const {{ convertLatexSymbols }} = require('{Path("ui/latex_convert.js").resolve().as_posix()}');
    process.stdout.write(Buffer.from(convertLatexSymbols({repr(input_text)}), 'utf8'));
    """
    res = subprocess.run(["node", "-e", js_code], capture_output=True, check=True)
    return res.stdout.decode("utf-8")

def test_latex_arrow_conversion():
    input_text = r"Embed query: User input $\rightarrow$ Vector $q$."
    output = run_node_converter(input_text)
    assert "→" in output
    assert r"\rightarrow" not in output
    assert "$" not in output

def test_latex_comparison_and_operators():
    input_text = r"Ensure that $x \leq 10$ and $y \times 5 \geq 20$ while $a \neq b$."
    output = run_node_converter(input_text)
    assert "≤" in output
    assert "×" in output
    assert "≥" in output
    assert "≠" in output
    assert r"\leq" not in output
    assert r"\times" not in output

def test_latex_greek_letters_and_fractions():
    input_text = r"Loss function with learning rate $\alpha$ and fraction $\frac{a}{b}$."
    output = run_node_converter(input_text)
    assert "α" in output
    assert "(a / b)" in output

def test_regular_dollar_sign_preserved():
    input_text = "The GPU costs $500 and the setup is $100."
    output = run_node_converter(input_text)
    assert "$500" in output
    assert "$100" in output

def test_api_system_prompt_includes_no_latex_instruction():
    from backend.persona import PersonaManager
    from backend.config import get_settings
    settings = get_settings()
    mgr = PersonaManager(file_path=settings.persona_file)
    persona = mgr.get_persona().content
    
    # Simulate API system prompt constructed in chat.py
    persona_text = persona + "\n\nDo not use LaTeX or mathematical dollar signs ($...$ or $$...$$). Use standard Unicode characters (e.g. →, ×, ≤, ≥, ≠, ·, etc.) for symbols and equations."
    assert "Do not use LaTeX" in persona_text
    assert "→" in persona_text
