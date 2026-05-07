"""Pattern parsing for the ``log_group_names`` plugin option.

CloudWatch Logs Insights itself only understands two log-group selection
mechanisms (exact names + ``SOURCE logGroups(namePrefix: [...])``); any
mid-pattern wildcard / regex has to be resolved client-side.  This
module owns the parsing layer that classifies each comma-separated
entry the operator authored.  The resolver and the AWS calls live in
``cloudwatch.py`` so the parser stays I/O-free and easy to test.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import re
import typing

from imbi_common.plugins.base import PluginContext
from imbi_common.plugins.templates import expand_template

from imbi_plugin_aws._helpers import template_vars

# CloudWatch Logs Insights caps ``logGroupNames`` at 50 per query.
LOG_GROUP_NAME_LIMIT = 50

# CloudWatch Logs Insights caps ``SOURCE logGroups(namePrefix: [...])`` at 5.
SOURCE_PREFIX_LIMIT = 5

EntryKind = typing.Literal['literal', 'glob', 'regex', 'prefix']

_GLOB_METACHARS = frozenset('*?[')
_REGEX_METACHARS = frozenset('\\.^$*+?{[|()')

_REGEX_MARKER = 'regex:'
_PREFIX_MARKER = 'prefix:'


@dataclasses.dataclass(frozen=True)
class Entry:
    """A single ``log_group_names`` entry after classification.

    ``raw`` keeps the operator-authored text (including the ``regex:`` /
    ``prefix:`` marker, if any) so error messages and warnings can echo
    what they wrote; ``expanded`` is the post-template-substitution
    pattern fed to the matcher / SOURCE clause.
    """

    kind: EntryKind
    raw: str
    expanded: str


def parse_entries(raw_option: str, ctx: PluginContext) -> list[Entry]:
    """Parse a comma-separated ``log_group_names`` option into entries."""
    pieces = [p.strip() for p in raw_option.split(',') if p.strip()]
    if not pieces:
        raise ValueError(
            'aws-cloudwatch-logs: log_group_names expanded to empty'
        )
    return [_classify(p, ctx) for p in pieces]


def _classify(raw: str, ctx: PluginContext) -> Entry:
    if raw.startswith(_REGEX_MARKER):
        body = raw[len(_REGEX_MARKER) :]
        if not body:
            raise ValueError(
                f"aws-cloudwatch-logs: '{_REGEX_MARKER}' marker requires "
                f'a pattern ({raw!r})'
            )
        # Escape interpolated values so a slug containing '.' (etc.)
        # does not accidentally become a regex metachar.
        escaped_vars: dict[str, str | None] = {
            k: re.escape(v) if v else '' for k, v in template_vars(ctx).items()
        }
        expanded = expand_template(body, escaped_vars)
        try:
            re.compile(expanded)
        except re.error as exc:
            raise ValueError(
                f'aws-cloudwatch-logs: invalid regex {body!r}: {exc}'
            ) from exc
        return Entry(kind='regex', raw=raw, expanded=expanded)

    if raw.startswith(_PREFIX_MARKER):
        body = raw[len(_PREFIX_MARKER) :]
        if not body:
            raise ValueError(
                f"aws-cloudwatch-logs: '{_PREFIX_MARKER}' marker requires "
                f'a value ({raw!r})'
            )
        expanded = expand_template(body, template_vars(ctx))
        if any(c in expanded for c in _GLOB_METACHARS):
            raise ValueError(
                f"aws-cloudwatch-logs: '{_PREFIX_MARKER}' entries cannot "
                f'contain wildcards ({raw!r})'
            )
        return Entry(kind='prefix', raw=raw, expanded=expanded)

    expanded = expand_template(raw, template_vars(ctx))
    if any(c in expanded for c in _GLOB_METACHARS):
        return Entry(kind='glob', raw=raw, expanded=expanded)
    return Entry(kind='literal', raw=raw, expanded=expanded)


def literal_prefix(pattern: str, *, is_regex: bool) -> str:
    """Return everything in ``pattern`` before the first metachar.

    Used to bound a ``DescribeLogGroups`` page walk: the literal prefix
    is the most we can usefully feed to ``logGroupNamePrefix`` before
    falling back to in-process matching.  Returns an empty string when
    the pattern starts with a metachar (caller must accept a full scan
    in that case).
    """
    metachars = _REGEX_METACHARS if is_regex else _GLOB_METACHARS
    for i, c in enumerate(pattern):
        if c in metachars:
            return pattern[:i]
    return pattern


def compile_matcher(pattern: str, *, is_regex: bool) -> re.Pattern[str]:
    """Compile a pattern into a regex anchored at the start of the name."""
    if is_regex:
        return re.compile(pattern)
    return re.compile(fnmatch.translate(pattern))


__all__ = [
    'LOG_GROUP_NAME_LIMIT',
    'SOURCE_PREFIX_LIMIT',
    'Entry',
    'EntryKind',
    'compile_matcher',
    'literal_prefix',
    'parse_entries',
]
