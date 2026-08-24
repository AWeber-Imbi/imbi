"""Release version format validation and release-tag ranking.

Provides small, dependency-free validators for the version
formats supported by Imbi releases.  The active format is a
runtime setting (see ``imbi.common.settings.Releases``) so the
model carries a plain ``str`` and validation happens at the
endpoint boundary where the setting is available.

Also home to the ranking used to answer "which tag is the current
release" -- :func:`release_tag_order_key` and
:func:`latest_release_tag`.  Both the projects-list summary and the
per-project release views rank the same ClickHouse ``tags`` rows, and
they must agree: when each endpoint carried its own copy they drifted,
and the two views reported different current releases for the same
project (#279).  This module is the single implementation, and it lives
here -- rather than beside either caller -- because
``project_deployments -> releases -> projects`` is an import cycle.

"""

import collections.abc
import datetime
import re
import typing

__all__ = [
    'COMMITISH_RE',
    'RELEASE_VERSION_RE',
    'SEMVER_RE',
    'SEMVER_TAG_PATTERN',
    'SEMVER_TAG_RE',
    'VersionFormat',
    'get_version_validator',
    'is_commitish',
    'is_semver_tag',
    'latest_release_tag',
    'matches_tag_formats',
    'release_tag_order_key',
    'release_version_key',
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


def short_committish(value: str) -> str:
    """The short, lowercase form a ``Release.committish`` is stored as.

    Every writer records ``sha[:7].lower()`` and the deploy path looks
    releases up by that form, so a full-length SHA yields a node nothing can
    ever match.  Only a SHA-shaped value is shortened: a committish naming a
    branch or tag (``main``, ``release-2.4.0``) is returned unchanged, since
    truncating it would corrupt the identity rather than normalize it.
    """
    if is_commitish(value.lower()):
        return value[:7].lower()
    return value


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


# A release-shaped tag for *ordering* purposes: an optional ``v``, then
# three or more dot-separated numeric components, then any pre-release or
# build metadata.  Deliberately looser than SEMVER_RE, which is used to
# validate and to bump: some tag rebuilds of a version as a fourth
# component (``0.17.0.1``), and those must rank rather than be discarded
# as unparseable -- a project tagged exclusively that way otherwise
# reports no current release at all (#279).  Leading zeros are tolerated
# here for the same reason: ranking a real tag beats rejecting it.
RELEASE_VERSION_RE: typing.Final[re.Pattern[str]] = re.compile(
    r'^v?(\d+(?:\.\d+){2,})(?:[-+].*)?$'
)


def release_version_key(name: str) -> tuple[int, ...] | None:
    """Numeric ordering key for a release tag; ``None`` if not one.

    Pre-release and build metadata are ignored, so ``1.2.3-rc1`` and
    ``1.2.3`` tie and a caller's later tie-break (usually the tag
    timestamp) decides.  That is deliberate: the suffix is a rebuild
    counter in AWeber's tagging, not a semver pre-release, so ordering it
    *before* the bare version would pick the older artifact.

    Tuples may differ in length; Python compares them element-wise, so
    ``(0, 17, 0) < (0, 17, 0, 1) < (1, 0, 0)`` as intended.
    """
    match = RELEASE_VERSION_RE.match(name)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split('.'))


def release_tag_order_key(
    name: str,
    when: typing.Any = None,
    authored_at: datetime.datetime | None = None,
) -> tuple[str, bool, tuple[int, ...], str]:
    """Sort key ranking the latest *release* highest.

    Primary order is the tagged commit's position in the synced history
    (``authored_at``): the tag on the newest commit is the latest release
    even when an earlier versioning scheme used higher numbers (a project
    that re-versioned from ``9.0.0`` down to ``2.32.7`` must base off
    ``2.32.7``, which highest-version ordering would never pick).  A tag
    whose commit isn't synced ranks below every tag whose commit is --
    backports live on unsynced release branches, so a backported
    ``v4.1.3`` tagged after ``v7.1.0`` still can't masquerade as the
    latest release.  Version then tag timestamp break the remaining ties:
    several tags on one commit, or callers with no commit context at all
    (who thereby keep plain highest-version behavior).

    Args:
        name: The tag name.
        when: The tag's own timestamp (``tagged_at``, falling back to
            ``recorded_at``).  Anything that isn't a ``datetime`` is
            treated as absent.
        authored_at: Authored time of the commit the tag points at, or
            ``None`` when that commit isn't in the synced history.

    Returns:
        A tuple ordered so that ``max()`` -- or ``sort(reverse=True)`` --
        yields the current release first.

    """
    key = release_version_key(name)
    when_key = when.isoformat() if isinstance(when, datetime.datetime) else ''
    authored_key = (
        authored_at.isoformat()
        if isinstance(authored_at, datetime.datetime)
        else ''
    )
    return (authored_key, key is not None, key or (), when_key)


def latest_release_tag(
    rows: collections.abc.Sequence[dict[str, typing.Any]],
    authored_by_sha: collections.abc.Mapping[str, datetime.datetime]
    | None = None,
) -> dict[str, typing.Any] | None:
    """Pick the latest release tag from ClickHouse ``tags`` rows.

    Each row is read for ``name``, ``sha``, and ``tagged_at`` (falling
    back to ``recorded_at``).  ``authored_by_sha`` maps a lowercased
    commit sha to that commit's authored time; with it the latest tag is
    the one on the newest synced commit (see
    :func:`release_tag_order_key`).  Without it -- callers ranking
    several tags on a single commit -- the version alone decides.

    Non-release tags are ranked rather than filtered out, so an ad-hoc
    tag on the newest commit can be the answer.  Callers wanting only
    version-shaped tags should filter ``rows`` with
    :func:`release_version_key` first.

    Returns:
        The winning row, or ``None`` when ``rows`` is empty.

    """
    if not rows:
        return None
    authored = authored_by_sha or {}
    return max(
        rows,
        key=lambda r: release_tag_order_key(
            str(r['name']),
            r.get('tagged_at') or r.get('recorded_at'),
            authored.get(str(r.get('sha') or '').lower()),
        ),
    )


def matches_tag_formats(
    tag: str,
    patterns: typing.Sequence[str],
) -> bool:
    """Return ``True`` when *tag* satisfies the configured tag formats.

    *patterns* is the resolved list of regular-expression patterns for
    the project (see ``imbi.common.models.TagFormat``).  Each pattern is
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
