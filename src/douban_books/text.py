from __future__ import annotations

import re
import unicodedata


_WHITESPACE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    """Preserve Unicode while making HTML-derived text safe for tabular output."""
    if not value:
        return ""
    value = unicodedata.normalize("NFC", value)
    value = "".join(_clean_character(char) for char in value)
    return _WHITESPACE.sub(" ", value).strip()


def _clean_character(char: str) -> str:
    if char in "\t\r\n":
        return " "
    return "\ufffd" if unicodedata.category(char) in {"Cc", "Cs"} else char
