"""Tests for ticket custom fields (``Ticket`` blueprints)."""

import typing
import unittest
from unittest import mock

import fastapi

from apps.api.tests.endpoints import test_person_tickets
from imbi.api.tickets import custom_fields
from imbi.common import models


class TicketCustomFieldTests(test_person_tickets.PersonTicketTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # Blueprints are global: a label of this test only keeps them
        # away from the tickets of other tests.
        self.label = f'cf-{self.team_id}'
        self.blueprints: list[str] = []
        self.addAsyncCleanup(self._delete_blueprints)
        await self.blueprint(
            'Incident',
            {
                'severity': {'type': 'string', 'enum': ['sev1', 'sev2']},
                'region': {'type': 'string', 'default': 'us-east-1'},
                'due_by': {'type': 'string', 'format': 'date'},
                'count': {'type': 'integer'},
            },
            required=['severity', 'region'],
            ticket_type=['bug'],
        )
        await self.blueprint(
            'Notes', {'reviewer': {'type': 'string', 'title': 'Reviewer'}}
        )

    async def blueprint(
        self,
        name: str,
        properties: dict[str, typing.Any],
        required: list[str] | None = None,
        ticket_type: list[str] | None = None,
    ) -> None:
        bp = models.Blueprint(
            name=f'{name} {self.label}',
            type='Ticket',
            filter={'ticket_type': ticket_type or [], 'label': [self.label]},
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': properties,
                    'required': required or [],
                }
            ),
        )
        await self.graph.create(bp)
        self.blueprints.append(bp.id)

    async def _delete_blueprints(self) -> None:
        await self.graph.execute(
            'MATCH (b:Blueprint) WHERE b.id IN {ids} DETACH DELETE b'
            ' RETURN 1 AS ok',
            {'ids': self.blueprints},
            ['ok'],
        )

    async def make(self, **body: typing.Any) -> dict[str, typing.Any]:
        response = await self.create_person(labels=[self.label], **body)
        self.assertEqual(response.status_code, 201, response.text)
        return typing.cast(dict[str, typing.Any], response.json())

    async def test_create_needs_required_fields(self) -> None:
        response = await self.create_person(
            labels=[self.label],
            type='bug',
            custom_fields={'count': 'many', 'other': 1},
        )
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'custom_fields_invalid')
        [missing] = detail['missing']
        self.assertEqual(missing['field'], 'severity')
        self.assertEqual(missing['enum'], ['sev1', 'sev2'])
        self.assertEqual(
            sorted(i['field'] for i in detail['invalid']), ['count', 'other']
        )

    async def test_create_fills_defaults_and_cleans_values(self) -> None:
        task = await self.make(
            type='bug',
            custom_fields={'severity': 'SEV1', 'due_by': '2026-12-01'},
        )
        self.assertEqual(
            task['custom_fields'],
            {
                'severity': 'sev1',
                'region': 'us-east-1',
                'due_by': '2026-12-01',
            },
        )
        # The Incident blueprint does not match a task: no field is
        # required, and its fields are unknown.
        task = await self.make(custom_fields={'reviewer': 'ann'})
        self.assertEqual(task['custom_fields'], {'reviewer': 'ann'})
        response = await self.create_person(
            labels=[self.label], custom_fields={'severity': 'sev1'}
        )
        self.assertEqual(response.status_code, 422, response.text)

    async def test_patch_checks_only_sent_fields(self) -> None:
        task = await self.make(
            type='bug', custom_fields={'severity': 'sev2', 'count': 3}
        )
        url = self.url(task['short_id'])
        # A type change hides the Incident fields; the values stay.
        response = await self.client.patch(
            url, json={'type': 'task', 'custom_fields': {'reviewer': 'ann'}}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()['custom_fields'],
            {
                'severity': 'sev2',
                'region': 'us-east-1',
                'count': 3,
                'reviewer': 'ann',
            },
        )
        response = await self.client.patch(
            url, json={'custom_fields': {'count': 4}}
        )
        self.assertEqual(response.status_code, 422, response.text)
        # ``null`` clears one field, also a hidden one.
        response = await self.client.patch(
            url, json={'custom_fields': {'count': None, 'reviewer': None}}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()['custom_fields'],
            {'severity': 'sev2', 'region': 'us-east-1'},
        )
        events = await self.store.events(task['id'], 0, 100)
        self.assertEqual(
            [e['type'] for e in events].count('custom_fields.changed'), 2
        )

    async def test_schema(self) -> None:
        response = await self.client.get(
            self.url('schema'), params={'type': 'bug', 'label': self.label}
        )
        self.assertEqual(response.status_code, 200, response.text)
        sections = response.json()['sections']
        self.assertEqual(
            [s['name'] for s in sections],
            [f'Incident {self.label}', f'Notes {self.label}'],
        )
        self.assertEqual(sections[0]['scope'], 'ticket')
        self.assertEqual(sections[0]['required'], ['severity', 'region'])
        response = await self.client.get(
            self.url('schema'), params={'label': self.label}
        )
        self.assertEqual(
            [s['name'] for s in response.json()['sections']],
            [f'Notes {self.label}'],
        )
        # The fields to filter on do not depend on the ticket.
        filterable = {f['field']: f for f in response.json()['filterable']}
        self.assertEqual(filterable['severity']['enum'], ['sev1', 'sev2'])
        self.assertEqual(filterable['reviewer']['title'], 'Reviewer')

    async def test_list_filter(self) -> None:
        a = await self.make(
            type='bug', custom_fields={'severity': 'sev1', 'count': 3}
        )
        b = await self.make(type='bug', custom_fields={'severity': 'sev2'})
        c = await self.make()

        async def found(*filters: str) -> list[str]:
            response = await self.client.get(
                self.url(), params=[('filter', f) for f in filters]
            )
            self.assertEqual(response.status_code, 200, response.text)
            return sorted(t['short_id'] for t in response.json())

        self.assertEqual(await found('severity:eq:sev1'), [a['short_id']])
        self.assertEqual(
            await found('severity:in:sev1,sev2'),
            sorted([a['short_id'], b['short_id']]),
        )
        self.assertEqual(await found('severity:ne:sev1'), [b['short_id']])
        self.assertEqual(await found('count:eq:3'), [a['short_id']])
        self.assertEqual(await found('severity:not_exists'), [c['short_id']])
        self.assertEqual(
            await found('severity:exists', 'count:not_exists'),
            [b['short_id']],
        )
        response = await self.client.get(
            self.url(), params={'filter': 'nope:eq:1'}
        )
        self.assertEqual(response.status_code, 400, response.text)


class ValidateTests(unittest.TestCase):
    """The check of :func:`custom_fields.validate`, without a database."""

    def setUp(self) -> None:
        self.matches = [
            models.Blueprint(
                name='Estimate',
                type='Ticket',
                json_schema=models.Schema.model_validate(
                    {
                        'type': 'object',
                        'properties': {
                            'estimate': {'type': 'integer', 'minimum': 0},
                            'tags': {
                                'type': 'array',
                                'items': {'type': 'string', 'enum': ['api']},
                            },
                            'payload': {
                                'type': 'object',
                                'properties': {
                                    'change_id': {'type': 'integer'}
                                },
                                'required': ['change_id'],
                            },
                        },
                    }
                ),
            )
        ]

    def test_minimum(self) -> None:
        for partial in (False, True):
            self.assertEqual(
                custom_fields.validate(
                    self.matches, {'estimate': 0}, partial=partial
                ),
                {'estimate': 0},
            )
            with self.assertRaises(fastapi.HTTPException) as ctx:
                custom_fields.validate(
                    self.matches, {'estimate': -1}, partial=partial
                )
            self.assertEqual(ctx.exception.status_code, 422)

    def test_array_item_enum(self) -> None:
        for partial in (False, True):
            self.assertEqual(
                custom_fields.validate(
                    self.matches, {'tags': ['api']}, partial=partial
                ),
                {'tags': ['api']},
            )
            with self.assertRaises(fastapi.HTTPException) as ctx:
                custom_fields.validate(
                    self.matches, {'tags': ['other']}, partial=partial
                )
            self.assertEqual(ctx.exception.status_code, 422)
        # A PATCH with None still clears the key.
        self.assertEqual(
            custom_fields.validate(self.matches, {'tags': None}, partial=True),
            {'tags': None},
        )

    def test_nested_object(self) -> None:
        for partial in (False, True):
            self.assertEqual(
                custom_fields.validate(
                    self.matches,
                    {'payload': {'change_id': 1}},
                    partial=partial,
                ),
                {'payload': {'change_id': 1}},
            )
            for bad in ({}, {'change_id': 'invalid'}):
                with self.assertRaises(fastapi.HTTPException) as ctx:
                    custom_fields.validate(
                        self.matches, {'payload': bad}, partial=partial
                    )
                detail = typing.cast(
                    dict[str, typing.Any], ctx.exception.detail
                )
                self.assertEqual(detail['invalid'][0]['field'], 'payload')

    def test_create_checks_defaults(self) -> None:
        matches = [
            models.Blueprint(
                name='Bad default',
                type='Ticket',
                json_schema=models.Schema.model_validate(
                    {
                        'type': 'object',
                        'properties': {
                            'estimate': {
                                'type': 'integer',
                                'minimum': 0,
                                'default': -1,
                            }
                        },
                    }
                ),
            )
        ]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            custom_fields.validate(matches, {}, partial=False)
        self.assertEqual(ctx.exception.status_code, 422)
        # A PATCH does not fill defaults, so it does not check them.
        self.assertEqual(custom_fields.validate(matches, {}, partial=True), {})

    def test_nested_ref(self) -> None:
        def blueprint(ref: str) -> models.Blueprint:
            return models.Blueprint(
                name='Ref',
                type='Ticket',
                json_schema=models.Schema.model_validate(
                    {
                        'type': 'object',
                        '$defs': {'Change': {'type': 'integer'}},
                        'properties': {
                            'payload': {
                                'type': 'object',
                                'properties': {'change': {'$ref': ref}},
                            }
                        },
                    }
                ),
            )

        local = [blueprint('#/$defs/Change')]
        self.assertEqual(
            custom_fields.validate(
                local, {'payload': {'change': 1}}, partial=False
            ),
            {'payload': {'change': 1}},
        )
        with self.assertRaises(fastapi.HTTPException):
            custom_fields.validate(
                local, {'payload': {'change': 'x'}}, partial=False
            )
        # A remote $ref is an invalid field, never a request.
        remote = [blueprint('https://example.invalid/change.json')]
        with (
            mock.patch('urllib.request.urlopen') as urlopen,
            self.assertRaises(fastapi.HTTPException) as ctx,
        ):
            custom_fields.validate(
                remote, {'payload': {'change': 1}}, partial=False
            )
        urlopen.assert_not_called()
        detail = typing.cast(dict[str, typing.Any], ctx.exception.detail)
        self.assertEqual(detail['invalid'][0]['field'], 'payload')
