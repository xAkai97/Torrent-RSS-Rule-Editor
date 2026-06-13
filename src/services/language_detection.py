"""
Language Detection — Heuristic Classifier for AniList Synonyms.

When AniList returns title synonyms (alternative names for an anime), many
of them are in languages like Chinese, Korean, or Thai. We need to filter
those out because we only want English and Romaji synonyms for RSS matching.

This module provides a lightweight, dependency-free heuristic to detect
"other-language" synonyms without needing a full NLP library.

Detection strategy:
  1. Any non-ASCII character (Unicode scripts like CJK, Thai, etc.) → other-language
  2. Short ASCII text (< 3 words) → assume English/Romaji (too short to tell)
  3. Longer ASCII text → check for common English articles ("the", "of", "and")
     or Romaji particles ("no", "ga", "wo"). If none found → other-language
"""

from __future__ import annotations

import re

# Regex to extract ASCII word tokens from text
_RE_WORDS = re.compile(r"[A-Za-z]+")


def is_other_language_synonym(text: str) -> bool:
    """
    Determine if a synonym string is likely NOT in English or Romaji.

    This is used to filter out synonyms like "进击的巨人" (Chinese for
    Attack on Titan) while keeping "Shingeki no Kyojin" (Romaji).

    Heuristic rules:
      - Any non-ASCII codepoint → treat as other-language (CJK, Thai, etc.)
      - ASCII text with < 3 words → assume English/Romaji (too short to classify)
      - ASCII text with 3+ words → check for known English/Romaji marker words.
        If none found, treat as other-language.

    Args:
        text: The synonym string to classify.

    Returns:
        True if the text is likely in a non-English/non-Romaji language.
    """
    value = str(text or '').strip()
    if not value:
        return False

    # Fast path: any non-ASCII character means it's definitely not English/Romaji
    if any(ord(ch) > 127 for ch in value):
        return True

    # Extract ASCII words for further analysis
    words = _RE_WORDS.findall(value.lower())
    if len(words) < 3:
        return False  # Too short to reliably classify — assume it's okay

    # Common English articles/prepositions — if any are present, it's probably English
    english_markers = {
        'the', 'of', 'and', 'to', 'in', 'a', 'an', 'for', 'with', 'on', 'from', 'my', 'your',
        'is', 'are', 'at', 'after', 'before',
    }
    # Common Romaji particles/honorifics — if any are present, it's probably Romaji
    romaji_markers = {
        'no', 'to', 'ga', 'wo', 'ni', 'de', 'wa', 'kara', 'mo', 'na', 'da', 'desu', 'kun',
        'chan', 'sama', 'san',
    }
    # If the text contains any recognized English or Romaji tokens, it's NOT other-language
    tokens = set(words)
    return not bool(tokens & (english_markers | romaji_markers))
