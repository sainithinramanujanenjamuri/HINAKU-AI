import re

def normalize_markdown(text: str) -> str:
    """
    Ensure a bold heading line directly after a list item renders as its own paragraph.
    In standard CommonMark / Markdown, a non-empty line directly after a list item without
    a blank line is parsed as a continuation of that list item (nested within <li>).
    Inserting a blank line separates the list and makes the bold heading its own block/paragraph.
    """
    if not text:
        return text

    # Pattern matches:
    # Group 1: A list item line: optional whitespace, bullet (-, *, +) or number (1.) with space and text
    # Followed by a single newline \n
    # Group 2: A bold heading line starting with **...**
    pattern = r"((?:^|\n)[ \t]*(?:[-*+]|\d+\.)[^\n]+)\n([ \t]*\*\*[^*]+?\*\*.*)"
    return re.sub(pattern, r"\1\n\n\2", text)
