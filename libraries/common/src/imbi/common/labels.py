"""Normalize the labels of tickets and of ticket blueprint filters."""

import re
import unicodedata
from collections import abc

_LABEL_SPACES = re.compile(r'[\s_]+')
_LABEL_HYPHENS = re.compile(r'-{2,}')


def _is_word(char: str) -> bool:
    """Return true for a letter, a combining mark, or a digit, as the
    UI's ``[\\p{L}\\p{M}\\p{N}]``."""
    return unicodedata.category(char)[0] in 'LMN'


def normalize_label(value: str) -> str:
    """Return the stored form of a label or role name.

    Lowercase; each run of spaces and underscores becomes one hyphen,
    and so does each run of hyphens; leading and trailing punctuation
    goes. ``"API"``, ``"api-"``, and ``" Api "`` are all ``"api"``. An
    empty result means the value has no letter or digit.
    """
    value = _LABEL_HYPHENS.sub(
        '-', _LABEL_SPACES.sub('-', value.strip().lower())
    )
    end = len(value)
    start = next((i for i, c in enumerate(value) if _is_word(c)), end)
    while end > start and not _is_word(value[end - 1]):
        end -= 1
    return value[start:end]


def normalize_labels(values: abc.Iterable[str]) -> list[str]:
    """Return the normalized labels without repeats, in order."""
    return list(dict.fromkeys(normalize_label(v) for v in values))
