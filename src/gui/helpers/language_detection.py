"""Language heuristics for AniList synonym filtering.

This module intentionally keeps a lightweight, dependency-free approach
for classifying synonyms that are likely outside EN/romaji.
"""

from __future__ import annotations

import re


def is_other_language_synonym(text: str) -> bool:
    """Return True when synonym text is likely non-English/non-romaji.

    Heuristic rules:
    - Any non-ASCII codepoint is treated as other-language.
    - ASCII text shorter than 3 words is treated as not-other.
    - For 3+ word ASCII text, if there are no common English/romaji
      marker tokens, treat it as other-language.
    """
    value = str(text or '').strip()
    if not value:
        return False

    # Any non-ASCII content (including accented/Unicode scripts) counts as other-language.
    if any(ord(ch) > 127 for ch in value):
        return True

    words = re.findall(r"[A-Za-z]+", value.lower())
    if len(words) < 3:
        return False

    english_markers = {
        'the', 'of', 'and', 'to', 'in', 'a', 'an', 'for', 'with', 'on', 'from', 'my', 'your',
        'is', 'are', 'at', 'after', 'before',
    }
    romaji_markers = {
        'no', 'to', 'ga', 'wo', 'ni', 'de', 'wa', 'kara', 'mo', 'na', 'da', 'desu', 'kun',
        'chan', 'sama', 'san',
    }
    tokens = set(words)
    return not bool(tokens & (english_markers | romaji_markers))
