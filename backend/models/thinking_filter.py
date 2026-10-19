import re
from typing import Optional, Tuple

META_PATTERNS = [
    r"^(?:It is a question|The user|I should)\b[^\n]*(?:\n+|$)",
]

def strip_meta_commentary(text: str) -> str:
    """
    Strips leading meta-commentary such as 'It is a question', 'The user', or 'I should'.
    """
    result = text.lstrip()
    changed = True
    while changed:
        changed = False
        for pat in META_PATTERNS:
            new_text = re.sub(pat, "", result, flags=re.IGNORECASE)
            if new_text != result:
                result = new_text.lstrip()
                changed = True
    return result

class ThinkingFilter:
    """
    Filters out <think>...</think> and <thought>...</thought> blocks in real-time
    from streaming chunk tokens and strips leading meta-commentary so internal reasoning
    never reaches the UI.
    """
    def __init__(self, tags: Tuple[str, ...] = ("think", "thought"), strip_meta: bool = True):
        self.tags = tags
        self.strip_meta = strip_meta
        self.in_thinking = False
        self.current_tag = None
        self.buffer = ""
        self.max_open_tag_len = max(len(f"<{t}>") for t in tags)
        self.max_close_tag_len = max(len(f"</{t}>") for t in tags)
        self.meta_checked = not strip_meta
        self.meta_prefixes = ["it is a question", "the user", "i should"]

    def process_chunk(self, chunk: str) -> str:
        self.buffer += chunk
        output = []

        while self.buffer:
            if not self.in_thinking:
                open_pattern = r"<(" + "|".join(self.tags) + r")(?:\s[^>]*)?>"
                match = re.search(open_pattern, self.buffer, re.IGNORECASE)
                if match:
                    normal_text = self.buffer[:match.start()]
                    if normal_text:
                        output.append(normal_text)
                    self.in_thinking = True
                    self.current_tag = match.group(1).lower()
                    self.buffer = self.buffer[match.end():]
                else:
                    # Check if end of buffer might be the start of an open tag
                    partial_len = 0
                    for length in range(min(len(self.buffer), self.max_open_tag_len), 0, -1):
                        tail = self.buffer[-length:]
                        if any(f"<{t}".startswith(tail.lower()) or f"<{t}>".startswith(tail.lower()) for t in self.tags):
                            partial_len = length
                            break
                    if partial_len > 0:
                        safe_text = self.buffer[:-partial_len]
                        self.buffer = self.buffer[-partial_len:]
                        if safe_text:
                            output.append(safe_text)
                        break
                    else:
                        output.append(self.buffer)
                        self.buffer = ""
                        break
            else:
                close_pattern = r"</" + re.escape(self.current_tag) + r">"
                match = re.search(close_pattern, self.buffer, re.IGNORECASE)
                if match:
                    self.buffer = self.buffer[match.end():]
                    if self.buffer.startswith("\r\n"):
                        self.buffer = self.buffer[2:]
                    elif self.buffer.startswith("\n"):
                        self.buffer = self.buffer[1:]
                    self.in_thinking = False
                    self.current_tag = None
                else:
                    partial_len = 0
                    close_tag = f"</{self.current_tag}>"
                    for length in range(min(len(self.buffer), self.max_close_tag_len), 0, -1):
                        tail = self.buffer[-length:]
                        if close_tag.startswith(tail.lower()):
                            partial_len = length
                            break
                    if partial_len > 0:
                        self.buffer = self.buffer[-partial_len:]
                    else:
                        self.buffer = ""
                    break

        raw_out = "".join(output)
        if not self.meta_checked and raw_out:
            low = raw_out.lstrip().lower()
            # If line starts with a meta-commentary prefix
            if any(low.startswith(p) for p in self.meta_prefixes):
                if "\n" not in raw_out:
                    self.buffer = raw_out + self.buffer
                    return ""
                stripped = strip_meta_commentary(raw_out)
                self.meta_checked = True
                return stripped
            # If line is a partial start of a meta-commentary prefix (e.g. "The ")
            elif any(p.startswith(low) for p in self.meta_prefixes if len(low) < len(p)):
                self.buffer = raw_out + self.buffer
                return ""
            else:
                self.meta_checked = True
                return raw_out

        return raw_out

    def flush(self) -> str:
        if not self.in_thinking and self.buffer:
            out = self.buffer
            self.buffer = ""
            if not self.meta_checked:
                out = strip_meta_commentary(out)
                self.meta_checked = True
            return out
        self.buffer = ""
        return ""

def strip_thinking(text: str) -> str:
    """Strips all thinking blocks and meta-commentary from a complete string."""
    cleaned = re.sub(r"<(think|thought)(?:\s[^>]*)?>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<(think|thought)(?:\s[^>]*)?>.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = strip_meta_commentary(cleaned)
    return cleaned.strip()
