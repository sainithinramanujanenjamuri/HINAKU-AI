// LaTeX Math to Plain Unicode Symbols converter for HINAKU UI
(function (global) {
  const LATEX_MAP = [
    // Arrows
    [/\\rightarrow\b/g, "→"],
    [/\\to\b/g, "→"],
    [/\\leftarrow\b/g, "←"],
    [/\\leftrightarrow\b/g, "↔"],
    [/\\Rightarrow\b/g, "⇒"],
    [/\\Leftarrow\b/g, "⇐"],
    [/\\Leftrightarrow\b/g, "⇔"],
    [/\\uparrow\b/g, "↑"],
    [/\\downarrow\b/g, "↓"],

    // Relations & comparisons
    [/\\leq\b/g, "≤"],
    [/\\le\b/g, "≤"],
    [/\\geq\b/g, "≥"],
    [/\\ge\b/g, "≥"],
    [/\\neq\b/g, "≠"],
    [/\\ne\b/g, "≠"],
    [/\\approx\b/g, "≈"],
    [/\\equiv\b/g, "≡"],
    [/\\sim\b/g, "~"],

    // Arithmetic & operators
    [/\\times\b/g, "×"],
    [/\\cdot\b/g, "·"],
    [/\\div\b/g, "÷"],
    [/\\pm\b/g, "±"],
    [/\\mp\b/g, "∓"],
    [/\\sum\b/g, "∑"],
    [/\\prod\b/g, "∏"],
    [/\\int\b/g, "∫"],
    [/\\infty\b/g, "∞"],
    [/\\sqrt\{([^}]+)\}/g, "√($1)"],
    [/\\sqrt\b/g, "√"],

    // Greek letters
    [/\\alpha\b/g, "α"],
    [/\\beta\b/g, "β"],
    [/\\gamma\b/g, "γ"],
    [/\\delta\b/g, "δ"],
    [/\\epsilon\b/g, "ε"],
    [/\\theta\b/g, "θ"],
    [/\\lambda\b/g, "λ"],
    [/\\mu\b/g, "μ"],
    [/\\pi\b/g, "π"],
    [/\\sigma\b/g, "σ"],
    [/\\omega\b/g, "ω"],
    [/\\Delta\b/g, "Δ"],
    [/\\Sigma\b/g, "Σ"],
    [/\\Omega\b/g, "Ω"],

    // Set theory & logic
    [/\\in\b/g, "∈"],
    [/\\notin\b/g, "∉"],
    [/\\subset\b/g, "⊂"],
    [/\\subseteq\b/g, "⊆"],
    [/\\cup\b/g, "∪"],
    [/\\cap\b/g, "∩"],
    [/\\forall\b/g, "∀"],
    [/\\exists\b/g, "∃"],

    // Formatting macros
    [/\\mathbf\{([^}]+)\}/g, "$1"],
    [/\\mathit\{([^}]+)\}/g, "$1"],
    [/\\mathrm\{([^}]+)\}/g, "$1"],
    [/\\text\{([^}]+)\}/g, "$1"],
    [/\\frac\{([^}]+)\}\{([^}]+)\}/g, "($1 / $2)"]
  ];

  function convertLatexSymbols(text) {
    if (!text) return "";
    let result = text;

    // Convert block math: $$ ... $$ -> plain content
    result = result.replace(/\$\$([\s\S]*?)\$\$/g, (match, inner) => {
      let converted = inner;
      for (const [pattern, repl] of LATEX_MAP) {
        converted = converted.replace(pattern, repl);
      }
      return converted.trim();
    });

    // Convert inline math: $ ... $ -> plain content (ensure not preceded/followed by digits/currency)
    result = result.replace(/(^|[^\w\$\\])\$([^\$\n]+?)\$(?=[^\w\$]|$)/g, (match, prefix, inner) => {
      let converted = inner;
      for (const [pattern, repl] of LATEX_MAP) {
        converted = converted.replace(pattern, repl);
      }
      return prefix + converted.trim();
    });

    // Fallback pass for standalone macro occurrences outside delimiters
    for (const [pattern, repl] of LATEX_MAP) {
      result = result.replace(pattern, repl);
    }

    return result;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { convertLatexSymbols, LATEX_MAP };
  } else {
    global.convertLatexSymbols = convertLatexSymbols;
  }
})(typeof window !== "undefined" ? window : globalThis);

