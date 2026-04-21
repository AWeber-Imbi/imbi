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
    'VersionFormat',
    'get_version_validator',
    'validate_version',
]


VersionFormat = typing.Literal['semver', 'commitish']

# Official regex from https://semver.org/ (Backus-Naur-form to
# regex, verbatim).  Matches MAJOR.MINOR.PATCH with optional
# pre-release and build metadata.  Leading zeros in numeric
# identifiers are rejected.
_SEMVER_RE: typing.Final[re.Pattern[str]] = re.compile(
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

# 7 to 40 lowercase hex chars — matches a git short or full SHA.
_COMMITISH_RE: typing.Final[re.Pattern[str]] = re.compile(r'^[0-9a-f]{7,40}$')


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
