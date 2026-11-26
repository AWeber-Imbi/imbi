"""Tests for the Home tab (Slack App Home PRD, phase 1)."""

import datetime
import fnmatch
import json
import os
import pathlib
import random
import re
import typing
import zoneinfo
from unittest import mock

import httpx
from slack_sdk import errors

from apps.slackbot.tests import helpers
from imbi.slackbot import blocks, create_ticket, home, identity
from imbi.slackbot.home import prefs, render, sources

NOW = datetime.datetime(2026, 11, 24, 19, 1, tzinfo=datetime.UTC)
TZ = zoneinfo.ZoneInfo('America/New_York')
USER = identity.ImbiUser('ada@example.com', 'Ada Lovelace', tz='UTC')
SNAPSHOTS = pathlib.Path(__file__).parent / 'snapshots'
ORG = {'slug': 'acme', 'name': 'Acme'}


def ts(hours: float) -> str:
    return (NOW - datetime.timedelta(hours=hours)).isoformat()


def pr(n: int, **extra: typing.Any) -> dict[str, typing.Any]:
    return {
        'project_id': f'p{n % 3}',
        'pr_id': f'pr{n}',
        'pr_number': 100 + n,
        'title': f'Change <{n}> & more',
        'url': f'https://github.com/acme/repo{n % 2}/pull/{100 + n}',
        'state': 'open',
        'author': 'grace',
        'draft': n % 2 == 0,
        'merged': False,
        'created_at': ts(n + 1),
        'updated_at': ts(n),
        'additions': 10 * n,
        'deletions': n,
        'reviewers': [
            {'login': 'bob', 'state': 'approved'},
            {'login': 'eve', 'state': 'requested'},
        ],
        **extra,
    }


def full_sections(n: int) -> dict[str, typing.Any]:
    """Return the data of every section, with ``n`` items each."""
    r = range(n)
    return {
        'needs_attention': {
            'incidents': [
                {
                    'id': f'i{i}',
                    'title': 'Elevated 5xx',
                    'status': 'triggered' if i % 2 else 'acknowledged',
                    'urgency': 'high',
                    'created_at': ts(i),
                    'url': f'https://pd.example/i{i}',
                    'project_id': 'p1',
                    'project': 'imbi-api',
                }
                for i in r
            ],
            'requests': [
                {
                    'id': f'r{i}',
                    'kind': 'approval' if i % 2 else 'question',
                    'title': 'Approve the shim?',
                    'opened_at': ts(i + 1),
                    'expires_at': ts(-23),
                    'short_id': f'T-{400 + i}',
                    'ticket_title': 'Upgrade pydantic',
                    'agent_slug': 'reviewbee' if i % 2 else None,
                    'agent_name': 'reviewbee' if i % 2 else None,
                }
                for i in r
            ],
            'held': [
                {
                    'short_id': f'T-{300 + i}',
                    'title': 'Rotate credentials',
                    'status': 'held',
                    'owner': USER.email,
                    'created_at': ts(50),
                    'updated_at': ts(i),
                    'failed': ['T-295'],
                }
                for i in r
            ],
            'advisories': [
                {
                    'cve_id': f'CVE-2026-{i}',
                    'url': f'https://nvd.example/{i}',
                    'package': 'urllib3',
                    'version': '2.4.0',
                    'published_at': ts(i),
                    'projects': ['imbi-api', 'imbi-mcp', 'a', 'b', 'c'],
                }
                for i in r
            ],
            'runs': [
                {
                    'id': f'run{i}',
                    'workflow_slug': 'py314',
                    'workflow_name': 'Python 3.14 migration',
                    'reason': 'failed',
                    'error': 'step_failed',
                    'created_at': ts(i + 2),
                }
                for i in r
            ],
        },
        'my_tickets': {
            'tickets': [
                {
                    'short_id': f'T-{200 + i}',
                    'title': f'Ticket {i}',
                    'status': 'open' if i % 2 else 'in_progress',
                    'priority': ('urgent', 'high', 'normal', 'low')[i % 4],
                    'created_at': ts(i),
                    'due_date': '2026-11-28' if i == 0 else None,
                    'backlog_rank': float(i),
                }
                for i in r
            ]
        },
        'pull_requests': {
            'review': [pr(i) for i in r],
            'review_total': n,
            'authored': [pr(i) for i in r],
            'authored_total': n,
            'github_identity_missing': False,
        },
        'merged_not_deployed': {
            'prs': [
                {
                    **pr(i),
                    'merged_at': ts(48),
                    'last_deployed_at': ts(72),
                    'last_deployed_environment': (
                        'production' if i == 0 else None
                    ),
                    'last_deployed_environment_name': (
                        'Production' if i == 0 else None
                    ),
                    'project': 'imbi-api',
                }
                for i in r
            ]
        },
        'release_drift': {
            'projects': [
                {
                    'project_id': f'p{i}',
                    'project': f'proj-{i}',
                    'commits': i + 1,
                    'latest_tag': '2.0.0',
                    'latest_tag_at': ts(100),
                    'suggested_tag': '2.1.0',
                    'blockers': 1 if i == 0 else 0,
                }
                for i in r
            ]
        },
        'agent_activity': {
            'tickets': [
                {
                    'short_id': f'T-{500 + i}',
                    'title': 'Bump fastapi',
                    'group': ('running', 'paused', 'queued')[i % 3],
                    'agent': 'workerbee',
                    'updated_at': ts(0.5),
                    'cost_total': '6.85',
                    'blocked_since': ts(1) if i % 3 == 1 else None,
                }
                for i in r
            ]
        },
        'document_comments': {
            'comments': [
                {
                    'document_id': f'd{i}',
                    'document_title': 'ADR 0028',
                    'project_id': 'p1' if i % 2 else None,
                    'thread_id': f't{i}',
                    'anchor_text': 'the rollout' if i % 2 else None,
                    'comment_id': f'c{i}',
                    'author_email': 'grace@example.com',
                    'author_name': 'Grace',
                    'body': 'x' * 300,
                    'created_at': ts(i),
                    'reason': 'mention' if i % 3 == 0 else 'owner',
                }
                for i in r
            ]
        },
    }


def gathered(
    sections: dict[str, typing.Any], **extra: typing.Any
) -> sources.Gathered:
    return sources.Gathered(
        org=ORG,
        orgs=[ORG],
        teams=['Platform'],
        sections=sections,
        ui_url='https://imbi.example',
        ask_url='slack://app?team=T1&id=A1&tab=messages',
        **extra,
    )


def outline(view: dict[str, typing.Any]) -> list[str]:
    """Return one readable line per block, for the snapshots."""
    lines: list[str] = []
    for block in view['blocks']:
        text = (block.get('text') or {}).get('text', '')
        if block['type'] == 'context':
            text = ' | '.join(e['text'] for e in block['elements'])
        if block.get('fields'):
            text = ' | '.join(f['text'] for f in block['fields'])
        extra = ''
        accessory = block.get('accessory')
        if accessory:
            extra = f' [{accessory["type"]}:{accessory["action_id"]}]'
        if block['type'] == 'actions':
            text = ', '.join(
                f'{e["text"]["text"]}({e.get("style", "")})'
                for e in block['elements']
            )
        lines.append(f'{block["type"]}: {text}{extra}')
    return lines


class RenderSnapshotTests(helpers.TestCase):
    """Compare the rendered view with ``tests/snapshots/home_*.json``.

    Run with ``UPDATE_SNAPSHOTS=1`` to write the snapshots again.

    """

    def check(self, name: str, view: dict[str, typing.Any]) -> None:
        self.assertLessEqual(len(view['blocks']), blocks.MAX_BLOCKS)
        path = SNAPSHOTS / f'home_{name}.json'
        actual = {'outline': outline(view), 'view': view}
        if os.environ.get('UPDATE_SNAPSHOTS') or not path.exists():
            SNAPSHOTS.mkdir(exist_ok=True)
            path.write_text(
                json.dumps(actual, indent=2, ensure_ascii=False) + '\n'
            )
        self.assertEqual(json.loads(path.read_text()), actual)

    def test_empty_user(self) -> None:
        empty = {
            'needs_attention': {
                'incidents': [],
                'requests': [],
                'held': [],
                'advisories': [],
                'runs': [],
            },
            'my_tickets': {'tickets': []},
            'pull_requests': {
                'review': [],
                'review_total': 0,
                'authored': [],
                'authored_total': 0,
                'github_identity_missing': True,
            },
            'merged_not_deployed': {'prs': []},
            'release_drift': {'projects': []},
            'agent_activity': {'tickets': []},
            'document_comments': {'comments': []},
        }
        view = render.render(USER, prefs.Prefs(), gathered(empty), NOW, TZ)
        self.check('empty', view)
        lines = outline(view)
        self.assertIn('context: Nothing waits on you.', lines)
        self.assertTrue(any('Connect GitHub' in line for line in lines))
        self.assertFalse(any('My tickets' in line for line in lines))

    def test_full_user(self) -> None:
        view = render.render(
            USER,
            prefs.Prefs(),
            gathered(full_sections(3), notice='Could not hide X: boom.'),
            NOW,
            TZ,
        )
        self.check('full', view)
        text = json.dumps(view)
        # Text from Imbi is escaped, so it cannot make a link or mention.
        self.assertIn('Change &lt;1&gt; &amp; more', text)
        self.assertIn('Good afternoon, Ada', text)
        self.assertIn('last deployed to Production 3d ago', text)
        self.assertIn('2d ago \\u00b7 last deployed 3d ago', text)
        self.assertEqual(
            'context: :warning: Could not hide X: boom.', outline(view)[0]
        )

    def test_all_collapsed(self) -> None:
        preferences = prefs.Prefs(
            sections=dict.fromkeys(prefs.DEFAULT_ORDER, 'collapsed')
        )
        view = render.render(
            USER, preferences, gathered(full_sections(2)), NOW, TZ
        )
        self.check('collapsed', view)
        # Header (4) + 2 blocks per section + footer.
        self.assertEqual(4 + 2 * 7 + 1, len(view['blocks']))
        self.assertTrue(
            all(
                b['accessory']['action_id'].endswith(':expand')
                for b in view['blocks'][4:-1]
                if b['type'] == 'section'
            )
        )

    def test_one_source_failed(self) -> None:
        data = full_sections(1)
        data['release_drift'] = sources.Failure('TimeoutError')
        view = render.render(USER, prefs.Prefs(), gathered(data), NOW, TZ)
        self.check('failed', view)
        lines = outline(view)
        self.assertIn(
            'section: Could not load Release drift. Try again. '
            '[button:home:release_drift:retry]',
            lines,
        )
        self.assertTrue(any('Agent activity' in line for line in lines))

    def test_multi_org_user(self) -> None:
        other = {'slug': 'beta', 'name': 'Beta'}
        g = gathered(full_sections(1))
        g.orgs = [ORG, other]
        view = render.render(USER, prefs.Prefs(), g, NOW, TZ)
        self.check('multi_org', view)
        select = view['blocks'][0]['accessory']
        self.assertEqual('home:header:org', select['action_id'])
        self.assertEqual('acme', select['initial_option']['value'])

    def test_no_org(self) -> None:
        g = sources.Gathered(None, [], [], {})
        view = render.render(USER, prefs.Prefs(), g, NOW, TZ)
        self.assertEqual(1, len(view['blocks']))

    def test_hidden_and_moved(self) -> None:
        preferences = prefs.Prefs(sections={'my_tickets': 'hidden'})
        prefs.move(preferences, 'document_comments', -1)
        view = render.render(
            USER, preferences, gathered(full_sections(1)), NOW, TZ
        )
        headers = [
            b['block_id']
            for b in view['blocks']
            if b.get('block_id', '').endswith(':header')
            and b['block_id'] != 'home:header'
        ]
        self.assertNotIn('home:my_tickets:header', headers)
        self.assertEqual('home:document_comments:header', headers[-2])
        self.assertIn('1 hidden', outline(view)[-1])


class BlockBudgetTests(helpers.TestCase):
    def test_no_view_passes_100_blocks(self) -> None:
        rng = random.Random(7)
        displays: list[prefs.Display] = ['expanded', 'collapsed', 'hidden']
        for n in (0, 1, 5, 10, 11, 25):
            for _ in range(15):
                order = list(prefs.DEFAULT_ORDER)
                rng.shuffle(order)
                preferences = prefs.Prefs(
                    order=order,
                    max_items=10,
                    hide_empty=rng.random() < 0.5,
                    sections={
                        k: rng.choice(displays)
                        for k in order
                        if rng.random() < 0.3 and k != prefs.PINNED
                    },
                )
                view = render.render(
                    USER,
                    preferences,
                    gathered(full_sections(n), notice='n'),
                    NOW,
                    TZ,
                )
                self.assertLessEqual(len(view['blocks']), blocks.MAX_BLOCKS)

    def test_cut_starts_at_the_last_section(self) -> None:
        view = render.render(
            USER,
            prefs.Prefs(max_items=10),
            gathered(full_sections(10)),
            NOW,
            TZ,
        )
        self.assertLessEqual(len(view['blocks']), blocks.MAX_BLOCKS)
        lines = outline(view)
        first = lines.index(
            next(line for line in lines if 'Needs attention (50)' in line)
        )
        # Needs attention keeps its 10 items; the last sections lose
        # theirs and say how many more there are.
        self.assertIn('+40 more', ''.join(lines[first : first + 25]))
        # Each section has 10 items and max_items is 10, so any
        # "+N more" in the last section comes from the cut.
        self.assertTrue(
            any(re.search(r'\+\d+ more', line) for line in lines[-6:]),
            lines[-6:],
        )

    def test_merged_not_deployed_links_to_the_report(self) -> None:
        view = render.render(
            USER,
            prefs.Prefs(max_items=2),
            gathered(full_sections(3)),
            NOW,
            TZ,
        )
        self.assertIn(
            '+1 more · <https://imbi.example/reports/merged-not-deployed'
            '?author=@me|View all 3 in Imbi>',
            json.dumps(view, ensure_ascii=False),
        )

    def test_merged_not_deployed_uses_the_api_total(self) -> None:
        sections = full_sections(3)
        sections['merged_not_deployed']['total'] = 250
        view = render.render(
            USER,
            prefs.Prefs(max_items=2),
            gathered(sections),
            NOW,
            TZ,
        )
        text = json.dumps(view, ensure_ascii=False)
        self.assertIn('Merged, not deployed (250)', text)
        self.assertIn(
            '+248 more · <https://imbi.example/reports/merged-not-deployed'
            '?author=@me|View all 250 in Imbi>',
            text,
        )


class BlocksTests(helpers.TestCase):
    def test_limits(self) -> None:
        self.assertEqual(3000, len(blocks.section('x' * 4000)['text']['text']))
        self.assertEqual(
            75, len(blocks.button('y' * 100, 'a')['text']['text'])
        )
        with self.assertRaises(ValueError):
            blocks.button('b', 'a', value='v' * 2001)
        with self.assertRaises(ValueError):
            blocks.overflow('a', [('one', '1')])
        with self.assertRaises(ValueError):
            blocks.view('home', [blocks.divider()] * 101)
        self.assertEqual(
            10, len(blocks.section('s', fields=['f'] * 12)['fields'])
        )


class AgentNameTests(helpers.TestCase):
    def test_request_names_the_agent(self) -> None:
        view = render.render(
            USER, prefs.Prefs(), gathered(full_sections(2)), NOW, TZ
        )
        lines = outline(view)
        self.assertTrue(
            any('*reviewbee is waiting on you* · ' in line for line in lines)
        )
        # A request without an agent name keeps the plain text.
        self.assertTrue(
            any(
                ':large_orange_circle: *Waiting on you* · ' in line
                for line in lines
            )
        )

    def test_running_shows_the_run_duration(self) -> None:
        data = full_sections(4)
        tickets = data['agent_activity']['tickets']
        tickets[0]['run_started_at'] = (
            NOW - datetime.timedelta(minutes=31)
        ).isoformat()
        tickets[3]['run_started_at'] = None
        lines = outline(
            render.render(USER, prefs.Prefs(), gathered(data), NOW, TZ)
        )
        self.assertTrue(
            any(':large_green_circle: Running 31 min ·' in x for x in lines)
        )
        # Without a start time, the text keeps the last update.
        self.assertTrue(
            any(
                ':large_green_circle: Running · updated 30 min ago' in x
                for x in lines
            )
        )

    def test_agent_name_is_escaped(self) -> None:
        data = full_sections(2)
        data['needs_attention']['requests'][1]['agent_name'] = '<!channel>'
        view = render.render(USER, prefs.Prefs(), gathered(data), NOW, TZ)
        text = json.dumps(view, ensure_ascii=False)
        self.assertIn('&lt;!channel&gt; is waiting on you', text)
        self.assertNotIn('<!channel>', text)


class WorkflowRunTests(helpers.TestCase):
    def test_failed_step_replaces_the_error(self) -> None:
        data = full_sections(2)
        attention = data['needs_attention']
        for kind in ('incidents', 'requests', 'held', 'advisories'):
            attention[kind] = []
        attention['runs'][0]['failure'] = {
            'node_key': 'review',
            'title': 'Review <PR>',
        }
        view = render.render(USER, prefs.Prefs(), gathered(data), NOW, TZ)
        text = '\n'.join(outline(view))
        self.assertIn('Step `Review &lt;PR&gt;` failed · started by you', text)
        # A run without a failed step keeps the error code.
        self.assertIn('step_failed · started by you', text)


class InjectionTests(helpers.TestCase):
    EVIL = '<https://evil.example|Click> *x* <!channel> & co'

    def test_link_helper(self) -> None:
        self.assertEqual(
            '<https://ok.example/a?b=1&amp;c=2|x &lt;y&gt; ¦ z>',
            blocks.link('https://ok.example/a?b=1&c=2', 'x <y> | z'),
        )
        for url in (
            'javascript:alert(1)',
            'https://ok.example/a|b',
            'https://ok.example/a>b',
            'https://ok.example/a b',
            'slack://app',
            None,
        ):
            self.assertEqual('a &lt;b&gt;', blocks.link(url, 'a <b>'), url)
        # Escaping twice changes nothing.
        once = blocks.escape(self.EVIL)
        self.assertEqual(once, blocks.escape(once))

    def test_api_values_are_escaped(self) -> None:
        data = full_sections(1)
        data['my_tickets']['tickets'][0].update(
            title=self.EVIL, status=self.EVIL, due_date=self.EVIL
        )
        data['document_comments']['comments'][0].update(
            body=self.EVIL, author_name=self.EVIL, document_title=self.EVIL
        )
        advisory = data['needs_attention']['advisories'][0]
        advisory['url'] = 'javascript:alert(1)'
        incident = data['needs_attention']['incidents'][0]
        incident['url'] = 'https://pd.example/i|<!here>'
        incident['title'] = self.EVIL
        view = render.render(USER, prefs.Prefs(), gathered(data), NOW, TZ)
        text = json.dumps(view, ensure_ascii=False)
        self.assertNotIn('<https://evil', text)
        self.assertNotIn('<!channel>', text)
        self.assertNotIn('<!here>', text)
        self.assertNotIn('javascript:', text)
        self.assertNotIn('pd.example/i|', text)
        self.assertIn('&lt;https://evil.example|Click&gt;', text)
        self.assertIn('&lt;!channel&gt; &amp; co', text)
        # The incident with the bad URL has no Acknowledge button.
        incident_block = next(
            b for b in view['blocks'] if 'Incident' in json.dumps(b)
        )
        self.assertNotIn('accessory', incident_block)


class CustomizeTests(helpers.TestCase):
    def test_removed_section_in_stored_value(self) -> None:
        # The API still stores the removed my_projects section.
        stored = prefs.parse(
            {
                'value': {
                    'order': ['my_projects', 'release_drift'],
                    'sections': {'my_projects': {'display': 'hidden'}},
                },
                'version': 1,
            }
        )
        self.assertNotIn('my_projects', stored.order)
        self.assertEqual('release_drift', stored.order[0])
        self.assertEqual({}, stored.sections)

    def test_modal_and_submission(self) -> None:
        view = render.customize_view(prefs.Prefs())
        pinned = next(
            b
            for b in view['blocks']
            if b.get('block_id') == 'section:needs_attention'
        )
        values = [o['value'] for o in pinned['element']['options']]
        self.assertEqual(['expanded', 'collapsed'], values)
        self.assertEqual(render.CUSTOMIZE, view['callback_id'])

        current = prefs.Prefs()
        render.apply_customize(
            current,
            {
                'section:agent_activity': {
                    'display': {'selected_option': {'value': 'hidden'}}
                },
                'section:needs_attention': {
                    'display': {'selected_option': {'value': 'hidden'}}
                },
                'options': {
                    'options': {'selected_options': [{'value': 'hide_empty'}]}
                },
            },
        )
        self.assertEqual('hidden', current.display('agent_activity'))
        # Needs attention cannot be hidden.
        self.assertEqual('expanded', current.display('needs_attention'))
        self.assertEqual(10, current.max_items)
        self.assertTrue(current.hide_empty)


# ----- a fake API and Valkey ---------------------------------------


class FakeValkey:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def set(
        self, key: str, value: typing.Any, nx: bool = False, ex: int = 0
    ) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = (
            value if isinstance(value, bytes) else str(value).encode()
        )
        return True

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)

    async def getdel(self, key: str) -> bytes | None:
        return self.data.pop(key, None)

    async def scan_iter(self, match: str) -> typing.AsyncIterator[str]:
        for key in list(self.data):
            if fnmatch.fnmatch(key, match):
                yield key


class FakeApi:
    """Answer the calls of the Home tab like imbi-api."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.stored: dict[str, typing.Any] | None = None
        self.version = 0
        self.conflicts = 0
        self.fail: set[str] = set()
        self.unmatched: list[str] = []
        self.drift_tag = '1.0.0'

    def routes(self) -> list[tuple[str, typing.Any]]:
        project = {
            'id': 'p1',
            'name': 'imbi-api',
            'slug': 'imbi-api',
            'team': {'name': 'Platform', 'slug': 'platform'},
            'score': 80,
            'release_summary': {'commits_since_tag': 4, 'latest_tag': '1.0.0'},
            'release_drifted': True,
        }
        released = {
            **project,
            'id': 'p2',
            'name': 'imbi-ui',
            'slug': 'imbi-ui',
            # Commits past the tag, but CI says none needs a release.
            'release_summary': {'commits_since_tag': 2},
            'release_drifted': False,
        }
        return [
            (
                r'/users/me$',
                {
                    'email': USER.email,
                    'is_admin': False,
                    'organizations': [
                        {
                            'organization_slug': 'acme',
                            'organization_name': 'Acme',
                            'permissions': [
                                'project:read',
                                'component:read',
                                'project:deployment:read',
                            ],
                        }
                    ],
                    'teams': [
                        {
                            'team_name': 'Platform',
                            'team_slug': 'platform',
                            'organization_slug': 'acme',
                        }
                    ],
                },
            ),
            (r'/projects/$', [project, released]),
            (
                r'/tickets/waiting$',
                {'count': 0, 'requests': [], 'assigned': [], 'held': []},
            ),
            (
                r'/incidents/$',
                {
                    'incidents': [
                        {
                            'id': 'i1',
                            'title': 'Down',
                            'status': 'triggered',
                            'created_at': ts(1),
                            'url': 'https://pd.example/i1',
                        }
                    ]
                },
            ),
            (
                r'/reports/problem-packages$',
                {
                    'rows': [
                        {
                            'project_id': 'p1',
                            'project_name': 'imbi-api',
                            'team_slug': 'platform',
                            'component_name': 'urllib3',
                            'version': '2.4.0',
                            'advisories': [
                                {'cve_id': 'CVE-1', 'severity': 'CRITICAL'},
                                {'cve_id': 'CVE-2', 'severity': 'high'},
                            ],
                        }
                    ]
                },
            ),
            (
                r'/workflow-runs/attention$',
                [
                    {
                        'id': 'run1',
                        'origin_kind': 'human',
                        'origin_id': USER.email,
                        'workflow_slug': 'w',
                        'workflow_name': 'W',
                        'reason': 'failed',
                        'error': None,
                        'created_at': ts(2),
                    },
                    {
                        'id': 'run2',
                        'origin_kind': 'human',
                        'origin_id': 'other@example.com',
                        'workflow_slug': 'w',
                        'workflow_name': 'W',
                        'reason': 'failed',
                        'created_at': ts(2),
                    },
                ],
            ),
            (r'/pull-requests/pending-deploy$', {'data': []}),
            (r'/pull-requests/$', {'data': [], 'total': 0}),
            (
                r'/release-drift$',
                {'latest_tag': self.drift_tag, 'suggested_tag': '1.1.0'},
            ),
            (r'/blockers$', []),
            (r'/tickets/$', []),
            (r'/agents/$', []),
            (r'/comments/attention$', {'data': []}),
            (r'/tickets/schema$', {'sections': []}),
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith('/preferences/slack_home'):
            return self.preferences(request)
        for pattern, body in self.routes():
            if re.search(pattern, path):
                if pattern in self.fail:
                    return httpx.Response(500)
                return httpx.Response(200, json=body)
        # A path with no route is a wrong path, not "nothing bound".
        # Record it: gather() turns a raised error into a section
        # failure, which a test can miss.
        self.unmatched.append(path)
        return httpx.Response(404)

    def preferences(self, request: httpx.Request) -> httpx.Response:
        if request.method == 'GET':
            if self.stored is None:
                return httpx.Response(404)
            return httpx.Response(
                200, json={'value': self.stored, 'version': self.version}
            )
        body = json.loads(request.content)
        if self.conflicts:
            self.conflicts -= 1
            return httpx.Response(409)
        if body['version'] != self.version:
            return httpx.Response(409)
        self.stored = body['value']
        self.version += 1
        return httpx.Response(
            200, json={'value': self.stored, 'version': self.version}
        )


class FakeSlack:
    def __init__(self) -> None:
        self.published: list[dict[str, typing.Any]] = []
        self.opened: list[dict[str, typing.Any]] = []
        self.updated: list[dict[str, typing.Any]] = []
        self.conflict = False

    async def views_publish(self, **kwargs: typing.Any) -> None:
        if self.conflict and kwargs.get('hash'):
            self.conflict = False
            raise errors.SlackApiError(
                'hash_conflict', {'error': 'hash_conflict'}
            )
        self.published.append(kwargs)

    async def views_open(self, **kwargs: typing.Any) -> dict:
        self.opened.append(kwargs)
        return {'view': {'id': f'V{len(self.opened)}'}}

    async def views_update(self, **kwargs: typing.Any) -> None:
        self.updated.append(kwargs)


class HomeFlowTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.api = FakeApi()
        self.addCleanup(
            lambda: self.assertEqual(
                [], self.api.unmatched, 'No FakeApi route'
            )
        )
        self.valkey = FakeValkey()
        self.slack = FakeSlack()
        transport = httpx.MockTransport(self.api.handler)

        class Client(identity.api.Imbi):
            def __init__(self, **kw: typing.Any) -> None:
                super().__init__(**kw)
                self._transport = transport

        self.user: identity.ImbiUser | None = USER
        patches = [
            mock.patch.object(identity.api, 'Imbi', Client),
            mock.patch.object(
                home.identity,
                'resolve',
                new=mock.AsyncMock(side_effect=lambda *_: self.user),
            ),
            mock.patch.object(
                home.identity,
                'mint_token',
                side_effect=lambda u: f'token-for-{u.email}',
            ),
            mock.patch.object(
                sources.valkey, 'get_client', return_value=self.valkey
            ),
            mock.patch.object(
                home.valkey, 'get_client', return_value=self.valkey
            ),
            mock.patch.object(
                home.settings,
                'get_slackbot_settings',
                return_value=mock.Mock(
                    ui_url='https://imbi.example',
                    api_base_url='http://imbi-api/api',
                ),
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def view(self) -> dict[str, typing.Any]:
        return self.slack.published[-1]['view']

    def text(self) -> str:
        return json.dumps(self.view(), ensure_ascii=False)

    async def test_every_call_carries_the_users_token(self) -> None:
        await home.refresh(self.slack, 'U1')
        self.assertGreater(len(self.api.requests), 10)
        for request in self.api.requests:
            self.assertEqual(
                f'Bearer token-for-{USER.email}',
                request.headers['authorization'],
                request.url,
            )
        paths = {r.url.path for r in self.api.requests}
        self.assertIn('/api/organizations/acme/workflow-runs/attention', paths)
        drift = '/api/organizations/acme/projects/{}/deployments/release-drift'
        self.assertIn(drift.format('p1'), paths)
        # A project the list does not mark drifted costs no drift call,
        # even with commits since its tag.
        self.assertNotIn(drift.format('p2'), paths)
        # A new latest tag misses the cached drift of the previous tag.
        self.assertIn('home:acme:drift:p1:1.0.0', self.valkey.data)
        text = self.text()
        # Only the run that the user started is in Needs attention.
        self.assertIn('run=run1', text)
        self.assertNotIn('run=run2', text)
        self.assertIn('Critical advisory', text)
        self.assertIn('CVE-1', text)
        self.assertNotIn('CVE-2', text)
        # A second render in 30 s reads the per-user cache.
        count = len(self.api.requests)
        await home.refresh(self.slack, 'U1')
        self.assertEqual(count + 2, len(self.api.requests))

    async def test_drift_from_another_tag_is_not_shown(self) -> None:
        await home.refresh(self.slack, 'U1')
        self.assertIn('1.1.0', self.text())
        # The drift call saw a newer tag than the project row.
        self.valkey.data.clear()
        self.api.drift_tag = '1.2.0'
        await home.refresh(self.slack, 'U1')
        self.assertNotIn('1.1.0', self.text())

    async def test_failed_source_fails_only_its_section(self) -> None:
        self.api.fail.add(r'/comments/attention$')
        await home.refresh(self.slack, 'U1')
        text = self.text()
        self.assertIn('Could not load Document comments', text)
        self.assertIn('Needs attention', text)
        # A view with a failure is not cached.
        self.assertNotIn(sources.gathered_key(USER.email), self.valkey.data)

    async def test_source_timeout(self) -> None:
        async def slow() -> None:
            await __import__('asyncio').sleep(1)

        with (
            mock.patch.object(sources, 'TIMEOUT', 0.01),
            mock.patch.object(
                sources.Sources, '_comments', lambda self: slow()
            ),
        ):
            await home.refresh(self.slack, 'U1')
        self.assertIn('Could not load Document comments', self.text())

    async def test_timeout_excludes_the_source_read_first(self) -> None:
        # Production: the projects list took 3 s of the 4 s, so the
        # incidents and drift fan-outs timed out (2.63.0).
        asyncio = __import__('asyncio')

        async def projects(_self: sources.Sources) -> list[str]:
            await asyncio.sleep(0.15)
            return []

        async def drift(self: sources.Sources) -> str:
            await self.get('team_projects')
            await asyncio.sleep(0.15)
            return 'ok'

        src = sources.Sources(mock.Mock(), 'acme', 'a@x', [], set())
        with (
            mock.patch.object(sources, 'TIMEOUT', 0.2),
            mock.patch.object(sources, '_TIMEOUTS', {}),
            mock.patch.object(sources.Sources, '_projects', projects),
            mock.patch.object(sources.Sources, '_drift', drift),
        ):
            self.assertEqual('ok', await src.get('drift'))

    async def test_cancelled_waiter_keeps_shared_source(self) -> None:
        asyncio = __import__('asyncio')

        async def slow() -> list[str]:
            await asyncio.sleep(0.05)
            return ['p1']

        src = sources.Sources(mock.Mock(), 'acme', 'a@x', [], set())
        with mock.patch.object(
            sources.Sources, '_projects', lambda self: slow()
        ):
            waiter = asyncio.ensure_future(src.get('projects'))
            await asyncio.sleep(0)
            waiter.cancel()
            self.assertEqual(['p1'], await src.get('projects'))

    async def test_failed_fan_out_cancels_the_others(self) -> None:
        asyncio = __import__('asyncio')
        slow = asyncio.ensure_future(asyncio.sleep(10))

        async def fail() -> None:
            raise RuntimeError('boom')

        with self.assertRaises(RuntimeError):
            await sources._fan_out([fail(), slow])
        self.assertTrue(slow.cancelled())

    async def test_unknown_user(self) -> None:
        self.user = None
        await home.refresh(self.slack, 'U1')
        view = self.view()
        self.assertEqual(1, len(view['blocks']))
        self.assertIn('match your Slack account', self.text())
        self.assertEqual([], self.api.requests)

    async def test_resolve_error_publishes_nothing(self) -> None:
        with mock.patch.object(
            home.identity,
            'resolve',
            new=mock.AsyncMock(side_effect=RuntimeError('graph')),
        ):
            await home.refresh(self.slack, 'U1')
        self.assertEqual([], self.slack.published)

    async def test_hash_conflict_renders_again(self) -> None:
        self.slack.conflict = True
        await home.refresh(self.slack, 'U1', view_hash='h1')
        self.assertEqual(1, len(self.slack.published))
        self.assertNotIn('hash', self.slack.published[0])

    async def test_hash_conflict_reads_stored_preferences(self) -> None:
        self.slack.conflict = True
        await home.refresh(
            self.slack, 'U1', view_hash='h1', preferences=prefs.Prefs()
        )
        reads = [
            r
            for r in self.api.requests
            if r.method == 'GET' and r.url.path.endswith('/slack_home')
        ]
        self.assertEqual(1, len(reads))

    def action(self, action_id: str, **extra: typing.Any) -> dict:
        return {
            'user': {'id': 'U1'},
            'trigger_id': 'trig',
            'team': {'id': 'T1'},
            'api_app_id': 'A1',
            'view': {'hash': 'h1'},
            'actions': [{'action_id': action_id, **extra}],
        }

    def puts(self) -> list[dict]:
        return [
            json.loads(r.content)
            for r in self.api.requests
            if r.method == 'PUT'
        ]

    async def test_menu_collapse(self) -> None:
        await home.handle_action(
            self.slack,
            self.action(
                'home:release_drift:menu',
                selected_option={'value': 'collapse'},
            ),
        )
        self.assertEqual(
            {'display': 'collapsed'},
            self.puts()[0]['value']['sections']['release_drift'],
        )
        self.assertEqual(0, self.puts()[0]['version'])
        self.assertIn(
            '▸ Release drift (1)*  Collapsed · imbi-api', self.text()
        )
        self.assertEqual('h1', self.slack.published[-1]['hash'])
        self.assertIn('slack://app?team=T1', self.text())

    async def test_menu_hide_move_and_expand(self) -> None:
        for action in (
            self.action(
                'home:my_tickets:menu', selected_option={'value': 'hide'}
            ),
            self.action(
                'home:agent_activity:menu', selected_option={'value': 'up'}
            ),
            self.action('home:release_drift:expand'),
        ):
            await home.handle_action(self.slack, action)
        stored = self.api.stored or {}
        self.assertEqual('hidden', stored['sections']['my_tickets']['display'])
        self.assertEqual(
            'expanded', stored['sections']['release_drift']['display']
        )
        order = stored['order']
        self.assertLess(
            order.index('agent_activity'), order.index('release_drift')
        )
        self.assertEqual(3, self.api.version)

    async def test_conflict_reads_and_applies_again(self) -> None:
        self.api.conflicts = 1
        await home.handle_action(
            self.slack,
            self.action(
                'home:my_tickets:menu', selected_option={'value': 'hide'}
            ),
        )
        self.assertEqual(2, len(self.puts()))
        self.assertEqual(1, self.api.version)

    async def test_failed_write_shows_a_notice(self) -> None:
        self.api.conflicts = 2
        await home.handle_action(
            self.slack,
            self.action(
                'home:my_tickets:menu', selected_option={'value': 'hide'}
            ),
        )
        self.assertIn(
            ':warning: Could not hide My tickets: Imbi answered 409.',
            self.text(),
        )
        # The notice shows one time.
        await home.refresh(self.slack, 'U1')
        self.assertNotIn(':warning:', self.text())

    async def test_retry_drops_caches(self) -> None:
        await home.refresh(self.slack, 'U1')
        self.assertTrue(
            any(':drift:' in k for k in self.valkey.data), self.valkey.data
        )
        other = 'home:beta:drift:p1'
        self.valkey.data[other] = b'{}'
        await home.handle_action(
            self.slack, self.action('home:release_drift:retry', value='acme')
        )
        self.assertEqual([], self.puts())
        # Only the drift keys of acme go; the render fills one again.
        self.assertIn(other, self.valkey.data)
        self.assertEqual(
            1, sum(k.startswith('home:acme:drift:') for k in self.valkey.data)
        )

    async def test_org_select(self) -> None:
        await home.handle_action(
            self.slack,
            self.action('home:header:org', selected_option={'value': 'beta'}),
        )
        self.assertEqual('beta', self.puts()[0]['value']['org_slug'])
        # Not a member of beta: the bot shows acme.
        self.assertIn('Acme', self.text())

    async def test_customize_opens_the_modal(self) -> None:
        await home.handle_action(
            self.slack, self.action('home:header:customize')
        )
        self.assertEqual('trig', self.slack.opened[0]['trigger_id'])
        self.assertIn('Loading', json.dumps(self.slack.opened[0]['view']))
        self.assertEqual('V1', self.slack.updated[0]['view_id'])
        self.assertEqual(
            render.CUSTOMIZE, self.slack.updated[0]['view']['callback_id']
        )
        await home.handle_action(
            self.slack,
            self.action(
                'home:my_tickets:menu', selected_option={'value': 'customize'}
            ),
        )
        self.assertEqual(2, len(self.slack.opened))
        self.assertEqual([], self.slack.published)

    async def test_customize_opens_before_the_remote_reads(self) -> None:
        opened_first: list[int] = []

        async def resolve(*_: typing.Any) -> None:
            opened_first.append(len(self.slack.opened))

        with mock.patch.object(home.identity, 'resolve', new=resolve):
            await home.handle_action(
                self.slack, self.action('home:header:customize')
            )
        self.assertEqual([1], opened_first)
        self.assertIn(
            'match your Slack account',
            json.dumps(self.slack.updated[0]['view']),
        )

    async def test_new_ticket_opens_the_create_ticket_modal(self) -> None:
        create_ticket._cache.clear()
        await home.handle_action(
            self.slack, self.action('home:header:new_ticket', value='acme')
        )
        self.assertEqual('trig', self.slack.opened[0]['trigger_id'])
        view = self.slack.updated[-1]['view']
        self.assertEqual(create_ticket.CALLBACK_ID, view['callback_id'])
        self.assertEqual('acme', json.loads(view['private_metadata'])['org'])
        self.assertEqual('V1', self.slack.updated[-1]['view_id'])
        self.assertEqual([], self.slack.published)
        for request in self.api.requests:
            self.assertEqual(
                f'Bearer token-for-{USER.email}',
                request.headers['authorization'],
            )

    async def test_link_buttons_only_ack(self) -> None:
        await home.handle_action(self.slack, self.action('home:header:open'))
        await home.handle_action(self.slack, self.action('home:pr:review'))
        self.assertEqual([], self.slack.published)
        self.assertEqual([], self.api.requests)

    async def test_customize_submission(self) -> None:
        await home.handle_submission(
            self.slack,
            {
                'user': {'id': 'U1'},
                'view': {
                    'state': {
                        'values': {
                            'section:agent_activity': {
                                'display': {
                                    'selected_option': {'value': 'collapsed'}
                                }
                            },
                            'options': {
                                'options': {
                                    'selected_options': [
                                        {'value': 'max_items'}
                                    ]
                                }
                            },
                        }
                    }
                },
            },
        )
        value = self.puts()[0]['value']
        self.assertEqual(
            'collapsed', value['sections']['agent_activity']['display']
        )
        self.assertFalse(value['hide_empty'])
        self.assertEqual(5, value['max_items'])
        self.assertIn('▸ Agent activity', self.text())


class RegisterTests(helpers.TestCase):
    async def test_handlers(self) -> None:
        handlers: dict[typing.Any, typing.Any] = {}

        class App:
            def event(self, name: typing.Any):
                def deco(fn: typing.Any) -> typing.Any:
                    handlers[name] = fn
                    return fn

                return deco

            action = view = event

        home.register(App())
        ack = mock.AsyncMock()
        with (
            mock.patch.object(home, 'refresh', new=mock.AsyncMock()) as ref,
            mock.patch.object(
                home, 'handle_action', new=mock.AsyncMock()
            ) as act,
            mock.patch.object(
                home, 'handle_submission', new=mock.AsyncMock()
            ) as sub,
        ):
            opened = handlers['app_home_opened']
            await opened({'tab': 'messages', 'user': 'U1'}, {}, None)
            ref.assert_not_awaited()
            await opened(
                {'tab': 'home', 'user': 'U1', 'view': {'hash': 'h'}},
                {'team_id': 'T1', 'api_app_id': 'A1'},
                None,
            )
            ref.assert_awaited_once_with(
                None,
                'U1',
                view_hash='h',
                ask_url='slack://app?team=T1&id=A1&tab=messages',
            )
            await handlers[home.ACTION](ack, {}, None)
            act.assert_awaited_once()
            await handlers[render.CUSTOMIZE](ack, {}, None)
            sub.assert_awaited_once()
        self.assertEqual(2, ack.await_count)
