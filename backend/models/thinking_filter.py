import re
from typing import Tuple

class ThinkingFilter:
    """
    Filters out <think>...</think> and <thought>...</thought> blocks in real-time
    from streaming chunk tokens so internal reasoning never reaches the UI.
    """
    def __init__(self, tags: Tuple[str, ...] = ("think", "thought")):
        self.tags = tags
        self.in_thinking = False
        self.current_tag = None
        self.buffer = ""
        self.max_open_tag_len = max(len(f"<{t}>") for t in tags)
        self.max_close_tag_len = max(len(f"</{t}>") for t in tags)

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
                    # Strip any immediate newline after thinking block
                    if self.buffer.startswith("\r\n"):
                        self.buffer = self.buffer[2:]
                    elif self.buffer.startswith("\n"):
                        self.buffer = self.buffer[1:]
                    self.in_thinking = False
                    self.current_tag = None
                else:
                    # In thinking mode: discard text but preserve potential closing tag prefix
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

        return "".join(output)

    def flush(self) -> str:
        if not self.in_thinking and self.buffer:
            out = self.buffer
            self.buffer = ""
            return out
        self.buffer = ""
        return ""

def strip_thinking(text: str) -> str:
    """Strips all thinking blocks from a complete string."""
    cleaned = re.sub(r"<(think|thought)(?:\s[^>]*)?>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<(think|thought)(?:\s[^>]*)?>.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()

