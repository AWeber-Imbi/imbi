"""Tests for GET /organizations/{org_slug}/comments/attention (real graph)."""

import datetime
import typing
import unittest
import uuid

from imbi.api import models
from imbi.api.auth import permissions
from imbi.api.endpoints import comments
from imbi.common import graph

ME = 'alice@example.com'
BOB = 'bob@example.com'


class AttentionCommentsTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        self.suffix = suffix
        self.org = f'att-{suffix}'
        self.other_org = f'att-other-{suffix}'
        self.ids: list[str] = []
        await graph.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.addAsyncCleanup(self.graph.close)
        self.addAsyncCleanup(self._cleanup)
        for org in (self.org, self.other_org):
            await self._run(
                """
                CREATE (o:Organization {{id: {org}, slug: {org}}}),
                       (t:Team {{id: {team}, slug: {team}}}),
                       (p:Project {{id: {project}}}),
                       (p)-[:OWNED_BY]->(t),
                       (t)-[:BELONGS_TO]->(o)
                RETURN 1 AS ok
                """,
                org=org,
                team=f'team-{org}',
                project=f'proj-{org}',
            )
            self.ids += [org, f'team-{org}', f'proj-{org}']
        self.auth = permissions.AuthContext(
            user=models.User(
                email=ME,
                display_name='Alice',
                password_hash='$argon2id$hashed',
                is_active=True,
                is_admin=False,
                is_service_account=False,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='test-session',
            auth_method='jwt',
            permissions={'document:read'},
        )

    async def _run(self, query: str, **params: typing.Any) -> None:
        await self.graph.execute(query, params, ['ok'])

    async def _cleanup(self) -> None:
        await self._run(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            ids=self.ids,
        )

    async def _thread(
        self,
        name: str,
        *,
        owner: str = BOB,
        org: str | None = None,
        resolved: bool = False,
        anchor: str = '',
        comments_: list[dict[str, typing.Any]],
    ) -> str:
        """Create a project document with one thread and its comments."""
        org = org or self.org
        doc_id = f'doc-{name}-{self.suffix}'
        thread_id = f'thread-{name}-{self.suffix}'
        self.ids += [doc_id, thread_id]
        await self._run(
            """
            MATCH (p:Project {{id: {project}}})
            CREATE (d:Document {{id: {doc}, title: {title},
                                 created_by: {owner}}}),
                   (d)-[:ATTACHED_TO]->(p),
                   (t:CommentThread {{id: {thread}, kind: 'inline',
                                      resolved: {resolved},
                                      anchor_quote: {anchor}}}),
                   (t)-[:ON_DOCUMENT]->(d)
            RETURN 1 AS ok
            """,
            project=f'proj-{org}',
            doc=doc_id,
            title=f'Doc {name}',
            owner=owner,
            thread=thread_id,
            resolved=resolved,
            anchor=anchor,
        )
        for i, c in enumerate(comments_):
            comment_id = f'c-{name}-{i}-{self.suffix}'
            self.ids.append(comment_id)
            await self._run(
                """
                MATCH (t:CommentThread {{id: {thread}}})
                CREATE (c:Comment {{id: {id}, thread_id: {thread},
                                    author: {author}, body: {body},
                                    mentions: {mentions},
                                    acknowledged_by: {acked},
                                    created_at: {created_at}}}),
                       (c)-[:IN_THREAD]->(t)
                RETURN 1 AS ok
                """,
                thread=thread_id,
                id=comment_id,
                author=c.get('author', BOB),
                body=c.get('body', f'body {name} {i}'),
                mentions=c.get('mentions', []),
                acked=c.get('acked', []),
                created_at=f'2026-11-{10 + i:02d}T12:00:00+00:00',
            )
        return thread_id

    async def _list(self, limit: int = 20) -> list[dict[str, typing.Any]]:
        result = await comments.list_attention_comments(
            self.org, self.graph, self.auth, limit
        )
        return result['data']

    async def test_owner_thread_shows_newest_other_comment(self) -> None:
        thread = await self._thread(
            'own',
            owner=ME,
            anchor='quoted',
            comments_=[{'body': 'old'}, {'body': 'new'}],
        )
        rows = await self._list()
        self.assertEqual([thread], [r['thread_id'] for r in rows])
        row = rows[0]
        self.assertEqual('owner', row['reason'])
        self.assertEqual('new', row['body'])
        self.assertEqual(BOB, row['author_email'])
        self.assertEqual('quoted', row['anchor_text'])
        self.assertEqual('Doc own', row['document_title'])
        self.assertEqual(f'proj-{self.org}', row['project_id'])

    async def test_mention_shows(self) -> None:
        thread = await self._thread(
            'mention', comments_=[{'mentions': [ME]}, {}]
        )
        await self._thread('unrelated', comments_=[{}])
        rows = await self._list()
        self.assertEqual([thread], [r['thread_id'] for r in rows])
        self.assertEqual('mention', rows[0]['reason'])
        self.assertIsNone(rows[0]['anchor_text'])

    async def test_resolved_thread_hidden(self) -> None:
        await self._thread('resolved', owner=ME, resolved=True, comments_=[{}])
        self.assertEqual([], await self._list())

    async def test_acknowledged_newest_hidden(self) -> None:
        await self._thread('acked', owner=ME, comments_=[{}, {'acked': [ME]}])
        self.assertEqual([], await self._list())

    async def test_own_comment_never_returned(self) -> None:
        await self._thread('mine', owner=ME, comments_=[{'author': ME}])
        thread = await self._thread(
            'before',
            owner=ME,
            comments_=[{'author': ME}, {'body': 'from bob'}],
        )
        rows = await self._list()
        self.assertEqual([thread], [r['thread_id'] for r in rows])
        self.assertEqual('from bob', rows[0]['body'])

    async def test_reply_hides_until_next_comment(self) -> None:
        await self._thread('replied', owner=ME, comments_=[{}, {'author': ME}])
        self.assertEqual([], await self._list())
        thread = await self._thread(
            'again',
            owner=ME,
            comments_=[{}, {'author': ME}, {'body': 'bob again'}],
        )
        rows = await self._list()
        self.assertEqual([thread], [r['thread_id'] for r in rows])
        self.assertEqual('bob again', rows[0]['body'])

    async def test_limit_and_newest_first(self) -> None:
        older = await self._thread('a', owner=ME, comments_=[{}])
        newer = await self._thread('b', owner=ME, comments_=[{}, {}])
        rows = await self._list()
        self.assertEqual([newer, older], [r['thread_id'] for r in rows])
        rows = await self._list(limit=1)
        self.assertEqual([newer], [r['thread_id'] for r in rows])

    async def test_other_org_hidden(self) -> None:
        await self._thread(
            'other', owner=ME, org=self.other_org, comments_=[{}]
        )
        self.assertEqual([], await self._list())
