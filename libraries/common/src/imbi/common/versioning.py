"""Release version format validation.

Provides small, dependency-free validators for the version
formats supported by Imbi releases.  The active format is a
runtime setting (see ``imbi_common.settings.Releases``) so the
model carries a plain ``str`` and validation happens at the
endpoint boundary where the setting is available.

"""

import re
import typing

__all__ = [
    'COMMITISH_RE',
    'SEMVER_RE',
    'SEMVER_TAG_PATTERN',
    'SEMVER_TAG_RE',
    'VersionFormat',
    'get_version_validator',
    'is_commitish',
    'is_semver_tag',
    'matches_tag_formats',
    'validate_version',
]


VersionFormat = typing.Literal['semver', 'commitish']

# Official regex from https://semver.org/ (Backus-Naur-form to
# regex, verbatim).  Matches MAJOR.MINOR.PATCH with optional
# pre-release and build metadata.  Leading zeros in numeric
# identifiers are rejected.
SEMVER_RE: typing.Final[re.Pattern[str]] = re.compile(
    r'^(?P<major>0|[1-9]\d*)'
    r'\.(?P<minor>0|[1-9]\d*)'
    r'\.(?P<patch>0|[1-9]\d*)'
    r'(?:-(?P<prerelease>'
    r'(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)'
    r'(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*'
    r'))?'
    r'(?:\+(?P<buildmetadata>'
    r'[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*'
    r'))?$'
)

# Same as SEMVER_RE but tolerates an optional leading ``v`` -- matches
# typical Git tag shape (``v1.2.3``) used by GitHub Releases as well as
# bare semver (``1.2.3``).  Use this to distinguish "already a tag" from
# "raw commitish" when deciding whether to cut a new tag on promote.
SEMVER_TAG_PATTERN: typing.Final[str] = r'^v?' + SEMVER_RE.pattern.lstrip('^')
SEMVER_TAG_RE: typing.Final[re.Pattern[str]] = re.compile(SEMVER_TAG_PATTERN)

# 7 to 40 lowercase hex chars — matches a git short or full SHA.
COMMITISH_RE: typing.Final[re.Pattern[str]] = re.compile(r'^[0-9a-f]{7,40}$')

# Module-internal aliases kept for backwards-compat with this module's
# previous private names.
_SEMVER_RE = SEMVER_RE
_COMMITISH_RE = COMMITISH_RE


def is_semver_tag(value: str) -> bool:
    """Return ``True`` if ``value`` is shaped like a semver release tag.

    Accepts a leading ``v`` (``v1.2.3``) as well as bare semver
    (``1.2.3``).  Use to decide whether a promote target is "already a
    tag" (skip ``create_tag`` + ``create_release``) versus a raw
    committish (cut a tag and create a release).
    """
    return bool(SEMVER_TAG_RE.match(value))


def is_commitish(value: str) -> bool:
    """Return ``True`` if ``value`` looks like a git short or full SHA."""
    return bool(COMMITISH_RE.match(value))


def validate_version(version: str, fmt: VersionFormat) -> str:
    """Validate ``version`` against ``fmt`` and return it.

    Args:
        version: The version string to validate.
        fmt: The active version format.

    Returns:
        The validated version string, returned unchanged.

    Raises:
        ValueError: If ``version`` does not match ``fmt``.

    """
    if fmt == 'semver':
        if not _SEMVER_RE.match(version):
            raise ValueError(
                f'Invalid semver version: {version!r}',
            )
        return version
    if fmt == 'commitish':
        if not _COMMITISH_RE.match(version):
            raise ValueError(
                f'Invalid commitish version: {version!r}',
            )
        return version
    raise ValueError(f'Unknown version format: {fmt!r}')


def get_version_validator(
    fmt: VersionFormat,
) -> typing.Callable[[str], str]:
    """Return a single-argument validator bound to ``fmt``.

    Useful where a caller wants to reuse the validator without
    repeatedly passing the format (e.g. as a ``pydantic``
    ``field_validator`` closure at the endpoint boundary).

    """

    def _validate(version: str) -> str:
        return validate_version(version, fmt)

    return _validate


def matches_tag_formats(
    tag: str,
    patterns: typing.Sequence[str],
) -> bool:
    """Return ``True`` when *tag* satisfies the configured tag formats.

    *patterns* is the resolved list of regular-expression patterns for
    the project (see ``imbi_common.models.TagFormat``).  Each pattern is
    matched against the whole *tag* with :func:`re.fullmatch`, so a
    pattern need not anchor itself with ``^``/``$``.

    An **empty** *patterns* sequence means "no configured policy" and
    matches any tag -- callers that need a stricter default should seed a
    format (e.g. :data:`SEMVER_TAG_PATTERN`) rather than relying on this.

    Invalid patterns are rejected at write time
    (``TagFormat`` validates them), so a bad pattern here is treated as a
    non-match rather than raising.
    """
    if not patterns:
        return True
    for pattern in patterns:
        try:
            if re.fullmatch(pattern, tag):
                return True
        except re.error:
            continue
    return False
