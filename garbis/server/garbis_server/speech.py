"""
Text for speech (ARCHITECTURE.md §9).

SentenceSplitter: v2's streaming splitter (garbis-v2/brain.py). The first chunk may be cut
at a comma so the first audio starts sooner.

speakable(): v2's emoji/markdown strip plus v3's spoken symbols, because models still write
"(3 + 12) / 7 ≈ 2.14" and emojis even when told not to (PLAN.md §7).
"""
import re

_SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*\s+")
_CLAUSE_END = re.compile(r"[,;:—–]\s+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")

_LIST_MARKER = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+")
_MONEY = re.compile(r"\$(\d+)(?:\.(\d{1,2}))?\b")
_NUM_L = r"(?<=[\d)])"            # a number or closing bracket on the left
_NUM_R = r"(?=\s*[\d(])"          # a number or opening bracket on the right


def _money(m: re.Match) -> str:
    dollars = int(m.group(1))
    cents = int((m.group(2) or "0").ljust(2, "0"))
    if dollars == 0 and cents:
        return f"{cents} cent" + ("s" if cents != 1 else "")
    word = "dollar" if dollars == 1 else "dollars"
    return f"{dollars} {word} {cents}" if cents else f"{dollars} {word}"


def speakable(text: str) -> str:
    text = _EMOJI.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = _MONEY.sub(_money, text)
    # math, before markdown stripping eats the '*'
    text = re.sub(r"\s*≈\s*", " is about ", text)
    text = re.sub(r"(?<=\d)\s*%", " percent", text)
    for symbol, word in ((r"[×*]", " times "), (r"/", " divided by "), (r"\+", " plus ")):
        text = re.sub(_NUM_L + r"\s*" + symbol + _NUM_R, word, text)                 # 15/7, (3 + 12)
        text = re.sub(r"(?<=[\w)])\s+" + symbol + r"\s+(?=[\w(])", word, text)      # kills + assists (spaced only, so and/or stays)
    text = re.sub(_NUM_L + r"\s+-\s+" + r"(?=[\d(])", " minus ", text)     # only spaced, so 2-3 stays a range
    text = re.sub(r"(?<=[\w)])\s*=\s*(?=[\w($-])", " equals ", text)
    # markdown and brackets
    text = re.sub(r"[*_`#~]", "", text)
    text = text.replace("(", "").replace(")", "")
    # whitespace and punctuation spacing
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([.,!?])", r"\1", text).strip()


def has_words(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


class SentenceSplitter:
    """Cuts streamed tokens into speakable chunks (same idea as LocalAIVtuber2's cut5)."""

    def __init__(self, first_clause_min: int = 30, max_len: int = 220):
        self.buf = ""
        self.first = True
        self.first_clause_min = first_clause_min
        self.max_len = max_len

    def push(self, text: str) -> list[str]:
        self.buf += text
        out = []
        while True:
            cut = None
            m = _SENTENCE_END.search(self.buf)
            if m:
                cut = m.end()
            elif "\n" in self.buf:
                cut = self.buf.index("\n") + 1
            elif self.first and len(self.buf) >= self.first_clause_min:
                c = None
                for c in _CLAUSE_END.finditer(self.buf):
                    pass
                if c and c.end() >= 15:
                    cut = c.end()
            if cut is None and len(self.buf) > self.max_len:
                space = self.buf.rfind(" ", 0, self.max_len)
                cut = space + 1 if space > 0 else self.max_len
            if cut is None:
                break
            piece, self.buf = self.buf[:cut], self.buf[cut:]
            piece = speakable(piece)
            if has_words(piece):
                out.append(piece)
                self.first = False
        return out

    def flush(self) -> list[str]:
        piece = speakable(self.buf)
        self.buf = ""
        return [piece] if has_words(piece) else []
