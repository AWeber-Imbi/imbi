"""Render the Home tab and the Customize Home modal.

:func:`render` is a pure function of its inputs: it does no I/O, so
tests can compare the view for fixed inputs. All Block Kit of the Home
tab is here.

"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import typing
import urllib.parse
import zoneinfo

from imbi.slackbot import blocks as b
from imbi.slackbot import identity
from imbi.slackbot.home import prefs as p
from imbi.slackbot.home import sources

type Block = b.Block
type Row = dict[str, typing.Any]

CUSTOMIZE = 'home:customize'
_MINUS = '\u2212'
PRIORITIES = ('urgent', 'high', 'normal', 'low')
_PRIORITY_EMOJI = {
    'urgent': ':red_circle:',
    'high': ':large_orange_circle:',
    'normal': ':white_circle:',
    'low': ':white_circle:',
}
_DISPLAY_LABELS: dict[p.Display, str] = {
    'expanded': 'Expanded',
    'collapsed': 'Collapsed',
    'hidden': 'Hidden',
}
_OPTIONS = {
    'hide_empty': 'Hide sections with nothing in them',
    'max_items': 'Show at most 5 items per section',
    'count_expanded_only': 'Count only expanded sections in the header',
}


@dataclasses.dataclass
class Part:
    """The content of one section, before the item limit."""

    count: int
    #: Groups of items, each with an optional subheading. Each item is
    #: one or more blocks.
    groups: list[tuple[str | None, list[list[Block]]]]
    summary: str
    subtitle: str | None = None
    more: tuple[int, str | None] | None = None
    #: Blocks to show when the section is empty.
    empty: list[Block] | None = None
    #: Show the section also when it is empty.
    always: bool = False
    #: ``section`` fields in place of item blocks (My projects).
    fields: list[str] | None = None


class _Links:
    """Build absolute links to the Imbi UI. Without ``IMBI_UI_URL``,
    links are plain text and link buttons are left out."""

    def __init__(self, ui_url: str, org: str) -> None:
        self.base = ui_url.rstrip('/')
        self.org = org

    def url(self, path: str) -> str | None:
        return f'{self.base}{path}' if self.base else None

    def a(self, path_or_url: str | None, text: str) -> str:
        """Return a link with escaped ``text``."""
        url = path_or_url
        if url and url.startswith('/'):
            url = self.url(url)
        return b.link(url, text)

    def ticket(self, short_id: str) -> str:
        return f'/tickets/{self.org}/{short_id}'

    def button(
        self,
        text: str,
        action_id: str,
        path_or_url: str | None,
        style: typing.Literal['primary', 'danger'] | None = None,
    ) -> Block | None:
        url = path_or_url
        if url and url.startswith('/'):
            url = self.url(url)
        safe = b.safe_url(url)
        if not safe:
            return None
        return b.button(text, action_id, url=safe, style=style)


# ----- time --------------------------------------------------------


def _when(value: str | datetime.datetime | None) -> datetime.datetime | None:
    if value is None or isinstance(value, datetime.datetime):
        return value
    when = datetime.datetime.fromisoformat(value)
    return when if when.tzinfo else when.replace(tzinfo=datetime.UTC)


def _span(seconds: float) -> str:
    seconds = abs(seconds)
    if seconds < 3600:
        return f'{max(1, int(seconds // 60))} min'
    if seconds < 86400:
        return f'{int(seconds // 3600)}h'
    return f'{int(seconds // 86400)}d'


def ago(value: str | datetime.datetime | None, now: datetime.datetime) -> str:
    """Return a relative time such as ``3h ago`` (R6)."""
    when = _when(value)
    if when is None:
        return ''
    seconds = (now - when).total_seconds()
    return 'just now' if seconds < 60 else f'{_span(seconds)} ago'


def _clock(now: datetime.datetime, tz: zoneinfo.ZoneInfo) -> str:
    local = now.astimezone(tz)
    return local.strftime('%I:%M %p').lstrip('0')


def _greeting(now: datetime.datetime, tz: zoneinfo.ZoneInfo) -> str:
    hour = now.astimezone(tz).hour
    if 5 <= hour < 12:
        return 'Good morning'
    if 12 <= hour < 17:
        return 'Good afternoon'
    return 'Good evening'


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f'{n} {word if n == 1 else many or word + "s"}'


def _names(names: list[str], limit: int = 3) -> str:
    shown = ', '.join(b.escape(n) for n in names[:limit])
    rest = len(names) - limit
    return f'{shown}, +{rest}' if rest > 0 else shown


def _repo(url: str) -> str:
    """Return ``repo`` of a GitHub pull request URL."""
    parts = urllib.parse.urlparse(url).path.strip('/').split('/')
    return parts[1] if len(parts) >= 2 else ''


def _money(value: object) -> str:
    try:
        return f'${decimal.Decimal(str(value)):.2f}'
    except decimal.InvalidOperation:
        return ''


# ----- sections ----------------------------------------------------


def _item(text: str, accessory: Block | None = None) -> list[Block]:
    return [b.section(text, accessory=accessory)]


def _needs_attention(data: Row, links: _Links, now: datetime.datetime) -> Part:
    # Each kind sorted oldest first; the kinds in the order of §4.3.
    kinds: list[tuple[str, list[Row], str]] = [
        ('incident', data['incidents'], 'created_at'),
        ('request', data['requests'], 'opened_at'),
        ('held', data['held'], 'updated_at'),
        ('advisory', data['advisories'], 'published_at'),
        ('run', data['runs'], 'created_at'),
    ]
    items: list[list[Block]] = []
    for kind, rows, field in kinds:
        for row in sorted(rows, key=lambda r: str(r.get(field) or '')):
            items.append(_attention_item(kind, row, links, now))
    return Part(
        count=len(items),
        groups=[(None, items)],
        subtitle='Agent requests, held tickets, and alerts on projects '
        'of your teams',
        summary=_plural(len(items), 'item'),
        more=(len(items), '/tickets/waiting'),
        empty=[b.context('Nothing waits on you.')],
        always=True,
    )


def _attention_item(
    kind: str, row: Row, links: _Links, now: datetime.datetime
) -> list[Block]:
    if kind == 'incident':
        emoji = (
            ':red_circle:'
            if row['status'] == 'triggered'
            else ':large_orange_circle:'
        )
        urgency = f' · {row["urgency"]} urgency' if row.get('urgency') else ''
        text = (
            f'{emoji} *Incident {b.escape(row["status"])} on '
            f'{links.a(f"/projects/{row['project_id']}", row["project"])}*'
            f'{b.escape(urgency)}\n“{b.escape(row["title"])}” · '
            f'{ago(row["created_at"], now)}'
        )
        return _item(
            text,
            links.button('Acknowledge', 'home:incident:open', row.get('url')),
        )
    if kind == 'request':
        ticket = links.ticket(row['short_id'])
        expires_at = _when(row.get('expires_at'))
        expires = (
            f' · expires in {_span((expires_at - now).total_seconds())}'
            if expires_at
            else ''
        )
        agent = row.get('agent_name')
        who = (
            f'{b.escape(agent)} is waiting on you'
            if agent
            else 'Waiting on you'
        )
        text = (
            f':large_orange_circle: *{who}* · '
            f'{links.a(ticket, row["short_id"])} '
            f'{b.escape(row["ticket_title"])}\n“{b.escape(row["title"])}” · '
            f'asked {ago(row["opened_at"], now)}{expires}'
        )
        # Phase 1: the answers are links to the ticket in Imbi.
        if row['kind'] == 'approval':
            answers = [
                links.button(
                    'Approve', 'home:request:approve', ticket, 'primary'
                ),
                links.button(
                    'Reject', 'home:request:reject', ticket, 'danger'
                ),
            ]
        else:
            answers = [
                links.button('Reply', 'home:request:reply', ticket, 'primary')
            ]
        answers.append(links.button('Hand off', 'home:ticket:handoff', ticket))
        buttons = [x for x in answers if x]
        return [b.section(text), *([b.actions(buttons)] if buttons else [])]
    if kind == 'held':
        ticket = links.ticket(row['short_id'])
        failed_ids: list[str] = row.get('failed') or []
        failed = ', '.join(b.escape(f) for f in failed_ids)
        text = (
            f':white_circle: *Held:* {links.a(ticket, row["short_id"])} '
            f'{b.escape(row["title"])}\nPrerequisite {failed} closed with '
            'an outcome that does not release this ticket'
        )
        return _item(
            text, links.button('Open ticket', 'home:ticket:open', ticket)
        )
    if kind == 'advisory':
        projects: list[str] = row['projects']
        text = (
            f':red_circle: *Critical advisory '
            f'{links.a(row.get("url"), row["cve_id"])}* in '
            f'`{b.escape(row["package"])} {b.escape(row["version"])}`\n'
            f'Used by {len(projects)} of your projects: '
            f'{_names(projects)}'
        )
        return _item(
            text,
            links.button(
                'View', 'home:advisory:open', '/reports/problem-packages'
            ),
        )
    # A failed or stuck workflow run that the user started.
    path = f'/agents/workflows/{row["workflow_slug"]}?run={row["id"]}'
    error = f'{b.escape(row["error"])} · ' if row.get('error') else ''
    text = (
        f':red_circle: *Workflow run {row["reason"]}* · '
        f'{links.a(path, row["workflow_name"])}\n'
        f'{error}started by you {ago(row["created_at"], now)}'
    )
    return _item(text, links.button('Open run', 'home:run:open', path))


def _my_tickets(data: Row, links: _Links, _now: datetime.datetime) -> Part:
    def order(t: Row) -> tuple[int, float, str]:
        priority = t.get('priority') or 'normal'
        rank = t.get('backlog_rank')
        return (
            PRIORITIES.index(priority) if priority in PRIORITIES else 2,
            float(rank) if rank is not None else float('inf'),
            str(t.get('created_at') or ''),
        )

    tickets = sorted(data['tickets'], key=order)
    items: list[list[Block]] = []
    for t in tickets:
        path = links.ticket(t['short_id'])
        priority = t.get('priority') or 'normal'
        due = f' · due {t["due_date"]}' if t.get('due_date') else ''
        text = (
            f'{_PRIORITY_EMOJI.get(priority, ":white_circle:")} '
            f'{links.a(path, t["short_id"])} {b.escape(t["title"])}\n'
            f'{b.escape(t["status"].replace("_", " ").capitalize())} · '
            f'{priority.capitalize()}{due}'
        )
        # Phase 1: Start is a link to the ticket in Imbi.
        if t['status'] == 'open':
            button = links.button('Start', 'home:ticket:start', path)
        else:
            button = links.button('Open', 'home:ticket:open', path)
        items.append(_item(text, button))
    return Part(
        count=len(items),
        groups=[(None, items)],
        subtitle='Assigned to you, not closed · sorted by priority, then rank',
        summary=_names([t['short_id'] for t in tickets]),
        more=(len(items), '/tickets/waiting'),
    )


def _review_line(pr: Row) -> str:
    reviewers: list[Row] = list(pr.get('reviewers') or [])
    approvals = sum(r['state'] == 'approved' for r in reviewers)
    changes = [
        r['login'] for r in reviewers if r['state'] == 'changes_requested'
    ]
    pending = sum(
        r['state'] == 'requested' and not r.get('team') for r in reviewers
    )
    parts: list[str] = []
    if changes:
        parts.append(f'changes requested by {b.escape(", ".join(changes))}')
    if approvals:
        parts.append(_plural(approvals, 'approval'))
    if pending:
        parts.append(f'{pending} pending')
    return ', '.join(parts) or 'no reviews'


def _pull_requests(data: Row, links: _Links, now: datetime.datetime) -> Part:
    def title(pr: Row) -> str:
        name = f'{_repo(pr["url"])}#{pr["pr_number"]}'
        return f'{links.a(pr["url"], name)} {b.escape(pr["title"])}'

    review = [
        _item(
            f'{title(pr)}\n{b.escape(pr["author"])} · +{pr["additions"]} '
            f'{_MINUS}{pr["deletions"]} · opened {ago(pr["created_at"], now)}',
            links.button('Review', 'home:pr:review', pr['url']),
        )
        for pr in sorted(data['review'], key=lambda r: r['created_at'])
    ]
    authored = [
        _item(
            f'{title(pr)}\n{"Draft · " if pr.get("draft") else ""}'
            f'{_review_line(pr)} · {ago(pr["updated_at"], now)}',
            links.button('Open', 'home:pr:open', pr['url']),
        )
        for pr in data['authored']
    ]
    total = data['review_total'] + data['authored_total']
    empty = None
    if data['github_identity_missing']:
        connect = links.button(
            'Connect GitHub', 'home:pr:connect', '/settings'
        )
        empty = [
            b.section(
                'Connect GitHub to see your pull requests.', accessory=connect
            )
        ]
    return Part(
        count=total,
        groups=[
            (f'Review requested ({data["review_total"]})', review),
            (f'Authored by you ({data["authored_total"]})', authored),
        ],
        summary=f'{data["review_total"]} to review · '
        f'{data["authored_total"]} authored',
        more=(total, '/reports/open-pull-requests'),
        empty=empty,
        always=bool(empty),
    )


def _merged_not_deployed(
    data: Row, links: _Links, now: datetime.datetime
) -> Part:
    items = [
        _item(
            f'{links.a(pr["url"], f"{_repo(pr['url'])}#{pr['pr_number']}")} '
            f'{b.escape(pr["title"])}\n{b.escape(pr["project"])} · merged '
            f'{ago(pr["merged_at"], now)} · last deployed '
            f'{ago(pr["last_deployed_at"], now)}',
            links.button(
                'Promote',
                'home:deploy:promote',
                f'/projects/{pr["project_id"]}/deployments',
            ),
        )
        for pr in data['prs']
    ]
    return Part(
        count=len(items),
        groups=[(None, items)],
        subtitle='Your PRs merged in the last 90 days that are not yet in '
        'production',
        summary=_names(sorted({pr['project'] for pr in data['prs']})),
        more=(len(items), None),
    )


def _release_drift(data: Row, links: _Links, now: datetime.datetime) -> Part:
    rows = sorted(data['projects'], key=lambda d: -d['commits'])
    items: list[list[Block]] = []
    for d in rows:
        path = f'/projects/{d["project_id"]}/deployments'
        since = (
            f'since `{b.escape(d["latest_tag"])}`'
            if d.get('latest_tag')
            else 'and no tag yet'
        )
        if d['blockers']:
            detail = f':red_circle: {_plural(d["blockers"], "open blocker")}'
            button = links.button('View blocker', 'home:release:blocker', path)
        else:
            tagged = (
                f'Tagged {ago(d["latest_tag_at"], now)} · '
                if d.get('latest_tag_at')
                else ''
            )
            detail = f'{tagged}suggested `{b.escape(d["suggested_tag"])}`'
            button = links.button('Cut release', 'home:release:cut', path)
        items.append(
            _item(
                f'{links.a(path, d["project"])} · '
                f'{_plural(d["commits"], "commit")} {since}\n{detail}',
                button,
            )
        )
    blocked = sum(1 for d in rows if d['blockers'])
    names = _names([d['project'] for d in rows], 4)
    return Part(
        count=len(items),
        groups=[(None, items)],
        summary=f'{blocked} blocked · {names}' if blocked else names,
        more=(len(items), '/projects'),
    )


def _my_projects(data: Row, links: _Links, _now: datetime.datetime) -> Part:
    def needs_look(r: Row) -> bool:
        delta = r.get('delta')
        return bool(
            r['incidents']
            or r['critical']
            or r['high']
            or (delta is not None and delta <= -3)
        )

    rows = sorted(
        data['projects'],
        key=lambda r: (
            not needs_look(r),
            r['score'] if r.get('score') is not None else 101,
        ),
    )
    fields: list[str] = []
    for r in rows:
        score = (
            'No score' if r.get('score') is None else f'Score {r["score"]:.0f}'
        )
        delta = r.get('delta')
        if delta:
            score += f' {"▲" if delta > 0 else "▼"}{abs(delta):.0f}'
        cves = _plural(r['critical'], 'critical CVE')
        if r['high']:
            cves += f' · {_plural(r["high"], "high CVE")}'
        fields.append(
            f'*{links.a(f"/projects/{r['id']}", r["name"])}*\n{score} · '
            f'{_plural(r["incidents"], "incident")} · {cves}'
        )
    look = sum(needs_look(r) for r in rows)
    need = 'needs' if look == 1 else 'need'
    teams = sorted({r['team'] for r in rows})
    scorecard = links.a('/reports/team-kpi', 'Team scorecard')
    return Part(
        count=len(rows),
        groups=[],
        fields=fields,
        subtitle=f'{_names(teams)} · {_plural(len(rows), "project")} · '
        f'{look} {need} a look · {scorecard}',
        summary=f'{look} {need} a look',
        more=(len(rows), '/projects'),
    )


def _agent_activity(data: Row, links: _Links, now: datetime.datetime) -> Part:
    groups = ('running', 'paused', 'queued')
    rows = sorted(data['tickets'], key=lambda t: groups.index(t['group']))
    items: list[list[Block]] = []
    for t in rows:
        path = links.ticket(t['short_id'])
        agent = f'{b.escape(t["agent"])} · ' if t.get('agent') else ''
        if t['group'] == 'running':
            status = (
                ':large_green_circle: Running · updated '
                f'{ago(t["updated_at"], now)}'
            )
            button = links.button('Pause', 'home:agent:pause', path)
        elif t['group'] == 'paused':
            status = ':large_orange_circle: Paused'
            if t.get('blocked_since'):
                status += ' · waiting on your reply'
            button = links.button('Resume', 'home:agent:resume', path)
        else:
            status = ':white_circle: Queued'
            button = links.button('Open', 'home:agent:open', path)
        cost = _money(t.get('cost_total'))
        items.append(
            _item(
                f'{links.a(path, t["short_id"])} {agent}'
                f'{b.escape(t["title"])}\n{status}'
                f'{f" · {cost} so far" if cost else ""}',
                button,
            )
        )
    return Part(
        count=len(items),
        groups=[(None, items)],
        subtitle='Agent tickets you own',
        summary=_names([t['short_id'] for t in rows]),
        more=(len(items), f'/tickets/{links.org}'),
    )


def _document_comments(
    data: Row, links: _Links, now: datetime.datetime
) -> Part:
    items: list[list[Block]] = []
    for c in data['comments']:
        path = (
            f'/projects/{c["project_id"]}/documents/{c["document_id"]}'
            if c.get('project_id')
            else f'/documents/{c["document_id"]}'
        )
        author = b.escape(c.get('author_name') or c['author_email'])
        if c['reason'] == 'mention':
            what = f'{author} mentioned you'
        elif c.get('anchor_text'):
            what = f'{author} on “{b.escape(b.cut(c["anchor_text"], 80))}”'
        else:
            what = f'{author} commented'
        text = (
            f'*{links.a(path, c["document_title"])}* · {what}\n'
            f'> {b.escape(b.cut(c["body"], 200)).replace(chr(10), " ")}\n'
            f'{ago(c["created_at"], now)} · {links.a(path, "Reply in Imbi")}'
        )
        # Phase 1: Acknowledge is a link to the document in Imbi.
        items.append(
            _item(text, links.button('Acknowledge', 'home:comment:ack', path))
        )
    return Part(
        count=len(items),
        groups=[(None, items)],
        summary=_names(
            sorted({c['document_title'] for c in data['comments']})
        ),
        more=(len(items), '/documents'),
    )


_PARTS: dict[str, typing.Callable[[Row, _Links, datetime.datetime], Part]] = {
    'needs_attention': _needs_attention,
    'my_tickets': _my_tickets,
    'pull_requests': _pull_requests,
    'merged_not_deployed': _merged_not_deployed,
    'release_drift': _release_drift,
    'my_projects': _my_projects,
    'agent_activity': _agent_activity,
    'document_comments': _document_comments,
}


# ----- assembly ----------------------------------------------------


def _escaped(value: typing.Any) -> typing.Any:
    """Return ``value`` with each string in it escaped for ``mrkdwn``.

    All API data goes through here before a section uses it, so no
    value that a person wrote can make a link or a mention. Links and
    link buttons unescape a URL before they check it.

    """
    if isinstance(value, str):
        return b.escape(value)
    if isinstance(value, dict):
        items = typing.cast('dict[str, typing.Any]', value).items()
        return {k: _escaped(v) for k, v in items}
    if isinstance(value, list):
        return [_escaped(v) for v in typing.cast('list[object]', value)]
    return value


def _menu(key: p.SectionKey, visible: list[p.SectionKey]) -> Block:
    options = [('Collapse', 'collapse')]
    if key != p.PINNED:
        options.append(('Hide from Home', 'hide'))
    if visible.index(key) > 0:
        options.append(('Move up', 'up'))
    if visible.index(key) < len(visible) - 1:
        options.append(('Move down', 'down'))
    options.append(('Customize Home', 'customize'))
    return b.overflow(f'home:{key}:menu', options)


def _shown(part: Part, limit: int) -> int:
    if part.fields is not None:
        return min(limit, len(part.fields))
    return sum(min(limit, len(items)) for _, items in part.groups)


def _longest(part: Part) -> int:
    """Return the item count of the longest group (the limit at which
    a cut shows one item less)."""
    if part.fields is not None:
        return len(part.fields)
    return max((len(items) for _, items in part.groups), default=0)


def _section(
    key: p.SectionKey,
    part: Part | sources.Failure,
    display: p.Display,
    visible: list[p.SectionKey],
    limit: int,
    links: _Links,
) -> list[Block]:
    title = p.TITLES[key]
    block_id = f'home:{key}:header'
    if isinstance(part, sources.Failure):
        return [
            b.section(
                f'*{title}*', block_id=block_id, accessory=_menu(key, visible)
            ),
            b.section(
                f'Could not load {title}. Try again.',
                accessory=b.button(
                    'Retry', f'home:{key}:retry', value=links.org
                ),
            ),
            b.divider(),
        ]
    if display == 'collapsed':
        return [
            b.section(
                f'*▸ {title} ({part.count})*  Collapsed'
                + (f' · {part.summary}' if part.summary else ''),
                block_id=block_id,
                accessory=b.button('Expand', f'home:{key}:expand'),
            ),
            b.divider(),
        ]
    out = [
        b.section(
            f'*{title} ({part.count})*',
            block_id=block_id,
            accessory=_menu(key, visible),
        )
    ]
    if part.subtitle:
        out.append(b.context(part.subtitle))
    if not part.count and not any(items for _, items in part.groups):
        out.extend(part.empty or [b.context('Nothing here.')])
    if part.fields is not None:
        if part.fields[:limit]:
            out.append(b.section(None, fields=part.fields[:limit]))
    else:
        for heading, items in part.groups:
            if heading and items:
                out.append(b.section(f'*{heading}*'))
            for item in items[:limit]:
                out.extend(item)
    if part.more:
        total, path = part.more
        hidden = total - _shown(part, limit)
        if hidden > 0:
            out.append(
                b.context(
                    f'+{hidden} more · '
                    f'{links.a(path, f"View all {total} in Imbi")}'
                    if path
                    else f'+{hidden} more'
                )
            )
    out.append(b.divider())
    return out


def _header(
    user: identity.ImbiUser,
    gathered: sources.Gathered,
    attention: int,
    now: datetime.datetime,
    tz: zoneinfo.ZoneInfo,
    links: _Links,
) -> list[Block]:
    out: list[Block] = []
    if gathered.notice:
        out.append(b.context(f':warning: {b.escape(gathered.notice)}'))
    first = (user.display_name or user.email).split()[0]
    org = gathered.org or {}
    accessory = None
    if len(gathered.orgs) > 1:
        accessory = b.static_select(
            'home:header:org',
            [(o['name'], o['slug']) for o in gathered.orgs],
            org.get('slug'),
            'Organization',
        )
    out.append(
        b.section(
            f'*{_greeting(now, tz)}, {b.escape(first)}*',
            block_id='home:header',
            accessory=accessory,
        )
    )
    out.append(
        b.context(
            f'{b.escape(org.get("name", ""))} · *{attention}* '
            f'{"thing needs" if attention == 1 else "things need"} you · '
            f'Updated {_clock(now, tz)}'
        )
    )
    buttons = [
        b.button(
            'New ticket',
            'home:header:new_ticket',
            value=links.org,
            style='primary',
        ),
        # The slack:// link is built from the ids in the Slack payload,
        # not from API data, so it skips the http(s) check.
        b.button('Ask Imbi', 'home:header:ask', url=gathered.ask_url)
        if gathered.ask_url
        else None,
        links.button('Open Imbi', 'home:header:open', '/dashboard'),
        links.button(
            'My profile',
            'home:header:profile',
            f'/users/{urllib.parse.quote(user.email)}',
        ),
        b.button('Customize Home', 'home:header:customize'),
    ]
    out.append(
        b.actions([x for x in buttons if x], block_id='home:header:actions')
    )
    out.append(b.divider())
    return out


def render(
    user: identity.ImbiUser,
    prefs: p.Prefs,
    gathered: sources.Gathered,
    now: datetime.datetime,
    tz: zoneinfo.ZoneInfo,
) -> Row:
    """Return the Home tab view, at most 100 blocks (R9)."""
    if gathered.org is None:
        return b.view(
            'home',
            [b.section('You are not a member of an Imbi organization yet.')],
        )
    links = _Links(gathered.ui_url, gathered.org['slug'])
    parts: dict[p.SectionKey, Part | sources.Failure] = {}
    for key in prefs.order:
        if prefs.display(key) == 'hidden' or key not in gathered.sections:
            continue
        data = gathered.sections[key]
        part = (
            data
            if isinstance(data, sources.Failure)
            else _PARTS[key](_escaped(data), links, now)
        )
        if (
            isinstance(part, Part)
            and not part.count
            and not part.always
            and prefs.hide_empty
        ):
            continue
        parts[key] = part
    visible = list(parts)
    attention = parts.get('needs_attention')
    count = attention.count if isinstance(attention, Part) else 0
    if (
        prefs.count_expanded_only
        and prefs.display('needs_attention') != 'expanded'
    ):
        count = 0
    head = _header(user, gathered, count, now, tz, links)
    hidden = sum(prefs.display(k) == 'hidden' for k in p.DEFAULT_ORDER)
    collapsed = sum(prefs.display(k) == 'collapsed' for k in p.DEFAULT_ORDER)
    footer = b.context(
        f'{_plural(collapsed, "section")} collapsed · {hidden} hidden · '
        'Customize Home · Imbi refreshes this tab when you open it'
    )
    limits = dict.fromkeys(visible, prefs.max_items)

    def assemble() -> list[Block]:
        body = [
            block
            for key in visible
            for block in _section(
                key,
                parts[key],
                prefs.display(key),
                visible,
                limits[key],
                links,
            )
        ]
        return [*head, *body, footer]

    expanded: list[tuple[p.SectionKey, Part]] = [
        (k, v)
        for k, v in parts.items()
        if isinstance(v, Part) and prefs.display(k) == 'expanded'
    ]
    out = assemble()
    # §5.5: cut items from the last section first until the view fits.
    while len(out) > b.MAX_BLOCKS:
        last, part = next(
            item
            for item in reversed(expanded)
            if _shown(item[1], limits[item[0]])
        )
        limits[last] = min(limits[last], _longest(part)) - 1
        out = assemble()
    return b.view('home', out)


def message_view(text: str, retry: bool = False) -> Row:
    """Return a Home tab view with one message, for a user that Imbi
    does not know (§4.12) or when Imbi is not available."""
    accessory = b.button('Retry', 'home:header:retry') if retry else None
    return b.view('home', [b.section(b.escape(text), accessory=accessory)])


def customize_view(prefs: p.Prefs) -> Row:
    """Return the Customize Home modal."""
    out: list[Block] = [
        b.section(
            'Choose how each section shows on your Imbi Home tab. Saved to '
            'your Imbi profile.'
        )
    ]
    for key in prefs.order:
        displays: list[p.Display] = (
            ['expanded', 'collapsed']
            if key == p.PINNED
            else ['expanded', 'collapsed', 'hidden']
        )
        block: Block = {
            'type': 'input',
            'block_id': f'section:{key}',
            'label': b.plain(p.TITLES[key]),
            'element': b.static_select(
                'display',
                [(_DISPLAY_LABELS[d], d) for d in displays],
                prefs.display(key),
            ),
        }
        if key == p.PINNED:
            block['hint'] = b.plain('Can be collapsed, not hidden', 150)
        out.append(block)
    options = [b.option(text, value) for value, text in _OPTIONS.items()]
    checked = {
        'hide_empty': prefs.hide_empty,
        'max_items': prefs.max_items == 5,
        'count_expanded_only': prefs.count_expanded_only,
    }
    checkboxes: Block = {
        'type': 'checkboxes',
        'action_id': 'options',
        'options': options,
    }
    initial = [o for o in options if checked[o['value']]]
    if initial:
        checkboxes['initial_options'] = initial
    out.append(
        {
            'type': 'input',
            'block_id': 'options',
            'optional': True,
            'label': b.plain('Options'),
            'element': checkboxes,
        }
    )
    out.append(
        b.context("To reorder, use Move up and Move down in a section's menu.")
    )
    return b.view(
        'modal',
        out,
        callback_id=CUSTOMIZE,
        title=b.plain('Customize Home', 24),
        submit=b.plain('Save', 24),
        close=b.plain('Cancel', 24),
    )


def customize_message(text: str) -> Row:
    """Return the Customize Home modal with one message, while it loads
    or when it cannot load."""
    return b.view(
        'modal',
        [b.section(b.escape(text))],
        title=b.plain('Customize Home', 24),
        close=b.plain('Close', 24),
    )


def apply_customize(prefs: p.Prefs, values: Row) -> None:
    """Apply the ``state.values`` of a Customize Home submission."""
    for key in p.DEFAULT_ORDER:
        chosen = sources.dig(
            values, f'section:{key}', 'display', 'selected_option', 'value'
        )
        if chosen in _DISPLAY_LABELS:
            p.set_display(prefs, key, chosen)
    selected: list[Row] = (
        sources.dig(values, 'options', 'options', 'selected_options') or []
    )
    checked = {o['value'] for o in selected}
    prefs.hide_empty = 'hide_empty' in checked
    prefs.max_items = 5 if 'max_items' in checked else 10
    prefs.count_expanded_only = 'count_expanded_only' in checked
