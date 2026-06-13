"""Unit tests for language detection heuristics."""

from src.services.language_detection import is_other_language_synonym


def test_detects_non_ascii_as_other_language():
    assert is_other_language_synonym("おまごと") is True
    assert is_other_language_synonym("กระจอกอย่างแกยังไงก็แพ้จอมมาร") is True
    assert is_other_language_synonym("處刑少女的生存之道") is True


def test_keeps_short_ascii_aliases_as_not_other_language():
    assert is_other_language_synonym("Omagoto") is False
    assert is_other_language_synonym("Virgin Road") is False


def test_keeps_english_marker_phrases_as_not_other_language():
    assert is_other_language_synonym("The Executioner and Her Way of Life") is False


def test_keeps_romaji_marker_phrases_as_not_other_language():
    assert is_other_language_synonym("Omae Gotoki ga Maou ni Kateru") is False


def test_flags_ascii_without_english_or_romaji_markers_as_other_language():
    assert is_other_language_synonym("atelier spiczastych kapeluszy") is True
