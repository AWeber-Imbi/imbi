"""Output filtering for ``run_with_secret`` (plan section 9.6 step 4).

Defense in depth only (plan section 11): a command that the model
chooses can always encode a value in a way that this filter does not
know.
"""

import base64
import typing
import urllib.parse

if typing.TYPE_CHECKING:
    import collections.abc

MARK = b'[REDACTED]'
#: The largest output, in characters, that the model gets.
MAX_OUTPUT = 64 * 1024
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


def redact(output: bytes, values: collections.abc.Iterable[bytes]) -> str:
    """Replace each value and its encodings, then limit the size.

    The size limit comes after the replacement, so a cut cannot leave
    a part of a value.
    """
    patterns = {item for value in values if value for item in variants(value)}
    for pattern in sorted(patterns, key=len, reverse=True):
        output = output.replace(pattern, MARK)
    text = output.decode('utf-8', 'replace')
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + '\n[output truncated]'
    return text
