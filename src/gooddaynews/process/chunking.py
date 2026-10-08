"""Split article text into passages of roughly 300-500 tokens for the chat's passage search.

Paragraphs are packed together until the target size; a paragraph longer than the maximum
is split at sentence boundaries. Token counts are estimated (about 0.75 words per token),
which is close enough for sizing chunks and avoids a tokenizer dependency.
"""

import re

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘(])")


def estimate_tokens(text: str) -> int:
    return round(len(text.split()) / 0.75)


def _split_long(paragraph: str, max_tokens: int) -> list[str]:
    parts, current = [], ""
    for sentence in _SENTENCE_RE.split(paragraph):
        candidate = f"{current} {sentence}".strip()
        if current and estimate_tokens(candidate) > max_tokens:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def chunk_text(text: str, target_tokens: int = 400, max_tokens: int = 500) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]
    pieces = []
    for p in paragraphs:
        pieces.extend(_split_long(p, max_tokens) if estimate_tokens(p) > max_tokens else [p])

    chunks, current = [], ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}".strip()
        if current and (estimate_tokens(current) >= target_tokens or estimate_tokens(candidate) > max_tokens):
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        # Fold a small tail into the previous chunk rather than leaving a fragment.
        if chunks and estimate_tokens(current) < target_tokens // 4 and estimate_tokens(chunks[-1] + current) <= max_tokens:
            chunks[-1] = f"{chunks[-1]}\n\n{current}"
        else:
            chunks.append(current)
    return chunks
