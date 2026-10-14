"""Output filtering for ``run_with_secret`` (plan section 9.6 step 4).

Defense in depth only (plan section 11): a command that the model
chooses can always encode a value in a way that this filter does not
know.
"""

import base64
import re
import typing
import urllib.parse

if typing.TYPE_CHECKING:
    import collections.abc

MARK = b'[REDACTED]'
#: The largest output, in characters, that the model gets.
MAX_OUTPUT = 64 * 1024
#: Bytes after the output limit that the executor keeps, so that a
#: value that the cut splits is still found. Longer than the longest
#: encoding of any value it filters.
OVERLAP = 64 * 1024
#: A shorter base64 fragment is not matched: it matches too much text.
MIN_FRAGMENT = 8


def variants(value: bytes) -> set[bytes]:
    """Return the value and its common encodings.

    A base64 encoder can put the value at any of three positions in its
    3-byte groups, for example ``echo "$TOKEN" | base64`` or a value
    inside a JSON document. For each position, the characters that
    depend only on the value are a fragment that the output contains.
    """
    found = {
        value,
        value.hex().encode(),
        value.hex().upper().encode(),
        urllib.parse.quote(value, safe='').encode(),
        urllib.parse.quote_plus(value).encode(),
    }
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        for shift in range(3):
            text = encode(b'\0' * shift + value)
            start = -(-4 * shift // 3)
            end = 4 * (shift + len(value)) // 3
            if end - start >= MIN_FRAGMENT:
                found.add(text[start:end])
    return {item for item in found if item}


def redact(
    output: bytes,
    values: collections.abc.Iterable[bytes],
    *,
    truncated: bool = False,
) -> str:
    """Replace each value and its encodings, then limit the size.

    The size limit comes after the replacement, so a cut cannot leave
    a part of a value. ``truncated``: the reader dropped bytes after
    the end of ``output``, so its last :data:`OVERLAP` bytes can hold
    a part of a value; they are removed.
    """
    patterns = {item for value in values if value for item in variants(value)}
    for pattern in sorted(patterns, key=len, reverse=True):
        output = output.replace(pattern, MARK)
    if truncated:
        output = output[:-OVERLAP]
    text = output.decode('utf-8', 'replace')
    if truncated or len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + '\n[output truncated]'
    return text


#: Known secret formats (plan section 6.6): GitHub tokens, Anthropic and
#: OpenAI style keys, AWS access key ids, Slack tokens, JWTs (the agent
#: token is one), and PEM private keys.
_FORMATS = re.compile(
    r'\b(?:gh[pousr]_[A-Za-z0-9]{36,255}'
    r'|github_pat_[A-Za-z0-9_]{22,255}'
    r'|sk-[A-Za-z0-9_-]{20,}'
    r'|(?:AKIA|ASIA)[A-Z0-9]{16}'
    r'|xox[abposr]-[A-Za-z0-9-]{10,}'
    r'|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?'
    r'-----END [A-Z ]*PRIVATE KEY-----'
)
_MARK_TEXT = MARK.decode()


class Redactor:
    """Redacts task event payloads before each append (plan 6.6).

    It removes the known formats and each value that it was given: the
    runner's own credentials, the model key, and every value that the
    executor delivered (plan section 9.6 step 4), with their encodings.
    """

    def __init__(self) -> None:
        self._patterns: list[str] = []

    def add(self, *values: str) -> None:
        found = set(self._patterns)
        for value in values:
            if value:
                found |= {
                    item.decode('utf-8', 'replace')
                    for item in variants(value.encode())
                }
        self._patterns = sorted(found, key=len, reverse=True)

    def text(self, value: str) -> str:
        for pattern in self._patterns:
            value = value.replace(pattern, _MARK_TEXT)
        return _FORMATS.sub(_MARK_TEXT, value)

    def payload(self, value: typing.Any) -> typing.Any:
        """Redact every string in a JSON value, keys included."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {
                self.text(str(key)): self.payload(item)
                for key, item in typing.cast(
                    'dict[str, typing.Any]', value
                ).items()
            }
        if isinstance(value, list):
            items: list[typing.Any] = value  # pyright: ignore[reportUnknownVariableType]
            return [self.payload(item) for item in items]
        return value
