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
    'CALVER_TAG_PATTERN',
    'CALVER_TAG_RE',
    'COMMITISH_RE',
    'RELEASE_VERSION_RE',
    'SEMVER_RE',
    'SEMVER_TAG_PATTERN',
    'SEMVER_TAG_RE',
    'VersionFormat',
    'calver_scheme_pattern',
    'get_version_validator',
    'is_calver_tag',
    'is_commitish',
    'is_semver_tag',
    'latest_release_tag',
    'matches_tag_formats',
    'next_calver_tag',
    'next_scheme_tag',
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

# Calendar versioning: ``YYYY.MM.DD`` (or ``YYYY-MM-DD``; the separator
# must be consistent) with an optional ``.`` or ``-`` suffix such as a
# same-day build counter (``2026.09.17-0``).  Mirrors the "Calendar
# versioning" built-in in the UI's version-format editor
# (``ui/src/lib/versionFormats.ts``); keep the two in step.
CALVER_TAG_PATTERN: typing.Final[str] = (
    r'^\d{4}([.-])\d{1,2}\1\d{1,2}(?:[.-]\w+)?$'
)
CALVER_TAG_RE: typing.Final[re.Pattern[str]] = re.compile(CALVER_TAG_PATTERN)

# Same shape, broken into the parts :func:`next_calver_tag` needs.
_CALVER_PARTS_RE: typing.Final[re.Pattern[str]] = re.compile(
    r'^(\d{4})([.-])(\d{1,2})\2(\d{1,2})(?:([.-])(\w+))?$'
)

# A calver modifier that ends in a number, such as ``rc1``.
_TRAILING_NUMBER_RE: typing.Final[re.Pattern[str]] = re.compile(
    r'^(.*\D)(\d+)$'
)

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


def is_calver_tag(value: str) -> bool:
    """Return ``True`` if ``value`` is a calendar-versioning tag."""
    return bool(CALVER_TAG_RE.match(value))


def _shows_padding(part: str, other: str) -> bool:
    """Whether a calver month or day component is zero-padded.

    A leading zero shows padding and a single digit shows none.  Two
    digits without a leading zero (``10``) do not show it, so the other
    component decides: ``2026.10.01`` is padded, ``2026.10.12`` is not.
    """
    if len(part) == 1:
        return False
    return part.startswith('0') or other.startswith('0')


def next_calver_tag(
    last_tag: str | None,
    today: datetime.date,
    *,
    pad: bool = False,
) -> str:
    """The calendar-versioning tag that follows ``last_tag`` on ``today``.

    The date is ``today`` in the separator and padding of ``last_tag``.
    With no prior calver tag, the date is unpadded and dot-separated
    (``2026.9.17``): calver.org names unpadded the sensible default, and
    an unpadded date is also valid semver.  The month and day each keep
    the padding of the prior tag (``2026.09.1`` yields ``2026.09.2``).
    A tag such as ``2026.10.12`` does not show its padding, so it is
    taken as unpadded.  Set ``pad`` to zero-pad the month and day
    always, for a tag policy that requires padding.

    The suffix mirrors the prior tag's convention: a tag that carried a
    numeric build counter (``2026.9.16-0``) yields ``2026.9.17-0`` on a
    new day and ``2026.9.16-1`` on the same day.  On the same day, a
    modifier that ends in a number (``rc1``) is kept and its number goes
    up (``rc2``).  A bare tag, or a modifier without a number, yields a
    bare date on a new day and ``-1`` on the same day.
    """
    match = _CALVER_PARTS_RE.match(last_tag or '')
    sep = match.group(2) if match else '.'
    pad_month = pad_day = pad
    if match and not pad:
        prior_month, prior_day = match.group(3), match.group(4)
        pad_month = _shows_padding(prior_month, prior_day)
        pad_day = _shows_padding(prior_day, prior_month)
    month = f'{today.month:02d}' if pad_month else str(today.month)
    day = f'{today.day:02d}' if pad_day else str(today.day)
    date = f'{today.year}{sep}{month}{sep}{day}'
    if not match:
        return date
    year, _, month, day, suffix_sep, suffix = match.groups()
    same_day = (int(year), int(month), int(day)) == (
        today.year,
        today.month,
        today.day,
    )
    counted = suffix is not None and suffix.isdigit()
    if same_day:
        if counted:
            return f'{date}{suffix_sep}{int(suffix) + 1}'
        numbered = _TRAILING_NUMBER_RE.match(suffix or '')
        if numbered:
            stem, number = numbered.groups()
            return f'{date}{suffix_sep}{stem}{int(number) + 1}'
        return f'{date}-1'
    if counted:
        return f'{date}{suffix_sep}0'
    return date


# Calendar-versioning schemes in calver.org notation, such as
# ``YY.0M.MICRO`` or ``YYYY.0M.0D[.MICRO]``.  Each token maps to the
# regular expression for one value.  The UI's version-format editor
# (``ui/src/lib/calverSchemes.ts``) ports this table; keep the two in step.
_SCHEME_TOKENS: typing.Final[dict[str, str]] = {
    'YYYY': r'[1-9]\d{3}',
    'YY': r'0|[1-9]\d{0,2}',
    '0Y': r'\d{2}|[1-9]\d{2}',
    'M': r'1[0-2]|[1-9]',
    '0M': r'1[0-2]|0[1-9]',
    'W': r'5[0-3]|[1-4]\d|[1-9]',
    '0W': r'5[0-3]|[1-4]\d|0[1-9]',
    'D': r'3[01]|[12]\d|[1-9]',
    '0D': r'3[01]|[12]\d|0[1-9]',
    'MINOR': r'0|[1-9]\d*',
    'MICRO': r'0|[1-9]\d*',
    'MODIFIER': r'[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*',
}
# calver.org deprecated these spellings; they mean the unpadded tokens.
_SCHEME_ALIASES: typing.Final[dict[str, str]] = {
    'MM': 'M',
    'WW': 'W',
    'DD': 'D',
}
_YEAR_TOKENS: typing.Final = frozenset({'YYYY', 'YY', '0Y'})
_COUNTER_TOKENS: typing.Final = ('MINOR', 'MICRO')
_PADDED_TOKENS: typing.Final = frozenset({'0Y', '0M', '0W', '0D'})
_SCHEME_RE: typing.Final[re.Pattern[str]] = re.compile(
    r'^(?P<body>[0-9A-Z]+(?:[._-][0-9A-Z]+)*)'
    r'(?:\[(?P<sep>[._-])(?P<optional>[0-9A-Z]+)\])?$'
)


class _Segment(typing.NamedTuple):
    sep: str  # The separator in front of the value; empty for the first.
    token: str
    optional: bool


def _parse_scheme(scheme: str) -> tuple[_Segment, ...]:
    """Split a calver.org scheme into segments and check the rules."""
    match = _SCHEME_RE.match(scheme.strip())
    if not match:
        raise ValueError(
            f'Invalid calver scheme {scheme!r}: use tokens such as YYYY,'
            ' 0M, and MICRO separated by ".", "-", or "_", with an'
            ' optional last segment in brackets, e.g. YYYY.0M.0D[.MICRO]'
        )
    parts = re.split(r'([._-])', match['body'])
    segments = [_Segment('', parts[0], False)]
    segments += [
        _Segment(parts[i], parts[i + 1], False)
        for i in range(1, len(parts), 2)
    ]
    if match['optional']:
        segments.append(_Segment(match['sep'], match['optional'], True))
    segments = [
        s._replace(token=_SCHEME_ALIASES.get(s.token, s.token))
        for s in segments
    ]
    tokens = [s.token for s in segments]
    for token in tokens:
        if token not in _SCHEME_TOKENS:
            raise ValueError(
                f'Unknown calver token {token!r}; use one of '
                + ', '.join(_SCHEME_TOKENS)
            )
    if len(set(tokens)) != len(tokens):
        raise ValueError('A calver token can appear only once')
    if len(_YEAR_TOKENS.intersection(tokens)) != 1:
        raise ValueError('A calver scheme needs one year: YYYY, YY, or 0Y')
    has_week = bool({'W', '0W'}.intersection(tokens))
    has_month = bool({'M', '0M'}.intersection(tokens))
    has_day = bool({'D', '0D'}.intersection(tokens))
    if has_week and (has_month or has_day):
        raise ValueError('Weeks cannot be combined with months or days')
    if has_day and not has_month:
        raise ValueError('A day needs a month')
    for segment in segments:
        if segment.token == 'MODIFIER' and not segment.optional:
            raise ValueError(
                'MODIFIER must be the optional last segment, e.g. [-MODIFIER]'
            )
        if segment.optional and segment.token not in (
            *_COUNTER_TOKENS,
            'MODIFIER',
        ):
            raise ValueError(
                'Only MINOR, MICRO, or MODIFIER can be the optional segment'
            )
    return tuple(segments)


def calver_scheme_pattern(scheme: str) -> str:
    """The regular expression that matches tags of a calver.org ``scheme``.

    Raises:
        ValueError: If ``scheme`` is not a valid calver scheme.

    """
    pattern = ''
    for index, segment in enumerate(_parse_scheme(scheme)):
        part = (
            f'{re.escape(segment.sep)}'
            f'(?P<t{index}>{_SCHEME_TOKENS[segment.token]})'
        )
        pattern += f'(?:{part})?' if segment.optional else part
    return f'^{pattern}$'


def _scheme_calendar(
    segments: collections.abc.Sequence[_Segment],
    today: datetime.date,
) -> dict[str, int]:
    """The value of each calendar token in ``segments`` on ``today``.

    Weeks are ISO 8601 weeks, and a scheme with a week uses the ISO year,
    so the last days of December can belong to week 1 of the next year.
    """
    iso_year, iso_week, _ = today.isocalendar()
    week = any(s.token in ('W', '0W') for s in segments)
    year = iso_year if week else today.year
    values = {
        'YYYY': year,
        'YY': year - 2000,
        '0Y': year - 2000,
        'M': today.month,
        '0M': today.month,
        'W': iso_week,
        '0W': iso_week,
        'D': today.day,
        '0D': today.day,
    }
    return {s.token: values[s.token] for s in segments if s.token in values}


def next_scheme_tag(
    scheme: str,
    last_tag: str | None,
    today: datetime.date,
    bump: typing.Literal['major', 'minor', 'patch'] = 'patch',
) -> str:
    """The tag of a calver.org ``scheme`` that follows ``last_tag``.

    In a new calendar period (the year, month, week, or day changed),
    the counters (``MINOR``, ``MICRO``) go back to 0, and an optional
    counter is left out.  In the same period, a ``major`` or ``minor``
    bump increments ``MINOR`` when the scheme has it; otherwise the last
    counter in the scheme goes up by 1 (an optional counter that was
    left out becomes 1), and the counters after it go back to 0.  A
    ``MODIFIER`` is never suggested.

    A scheme with no counter gives the same tag for two releases in one
    period.  When ``last_tag`` does not match ``scheme``, the result is
    the first tag of the current period.

    Raises:
        ValueError: If ``scheme`` is not a valid calver scheme.

    """
    segments = _parse_scheme(scheme)
    calendar = _scheme_calendar(segments, today)
    last = re.fullmatch(calver_scheme_pattern(scheme), last_tag or '')
    prior: dict[str, str | None] = {
        s.token: last[f't{i}'] if last else None
        for i, s in enumerate(segments)
    }
    same_period = last is not None and all(
        int(prior[token] or 0) == value for token, value in calendar.items()
    )
    counters: dict[str, int | None] = {}
    present = [s for s in segments if s.token in _COUNTER_TOKENS]
    if same_period and present:
        names = [s.token for s in present]
        target = (
            'MINOR'
            if bump in ('major', 'minor') and 'MINOR' in names
            else names[-1]
        )
        reset = False
        for segment in present:
            value = prior[segment.token]
            if reset:
                counters[segment.token] = None if segment.optional else 0
            elif segment.token == target:
                counters[segment.token] = int(value) + 1 if value else 1
                reset = True
            else:
                counters[segment.token] = int(value) if value else None
    else:
        for segment in present:
            counters[segment.token] = None if segment.optional else 0
    tag = ''
    for segment in segments:
        if segment.token in calendar:
            number = calendar[segment.token]
            text = (
                f'{number:02d}'
                if segment.token in _PADDED_TOKENS
                else str(number)
            )
        elif counters.get(segment.token) is not None:
            text = str(counters[segment.token])
        else:
            continue  # An optional counter left out, or a MODIFIER.
        tag += f'{segment.sep}{text}'
    return tag


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
    if match:
        return tuple(int(part) for part in match.group(1).split('.'))
    # A calver tag with ``-`` between the date parts (``2026-09-17``,
    # Stripe's ``2026-09-30.acacia``).  As above, the suffix is ignored.
    calver = _CALVER_PARTS_RE.match(name)
    if calver:
        return int(calver.group(1)), int(calver.group(3)), int(calver.group(4))
    return None


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
