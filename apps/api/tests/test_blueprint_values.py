"""Tests for the check of blueprint values."""

import typing
import unittest
from unittest import mock

import fastapi

from imbi.api import blueprint_sections, blueprint_values
from imbi.common import models


class ValidateTests(unittest.TestCase):
    """The check of :func:`blueprint_values.validate`, without a database."""

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
                            'counts': {
                                'type': 'array',
                                'items': {'type': 'integer', 'minimum': 0},
                            },
                            'checks': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {'name': {'type': 'string'}},
                                    'required': ['name'],
                                },
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
                blueprint_values.validate(
                    self.matches, {'estimate': 0}, partial=partial
                ),
                {'estimate': 0},
            )
            with self.assertRaises(fastapi.HTTPException) as ctx:
                blueprint_values.validate(
                    self.matches, {'estimate': -1}, partial=partial
                )
            self.assertEqual(ctx.exception.status_code, 422)

    def test_array_item_enum(self) -> None:
        for partial in (False, True):
            self.assertEqual(
                blueprint_values.validate(
                    self.matches, {'tags': ['api']}, partial=partial
                ),
                {'tags': ['api']},
            )
            with self.assertRaises(fastapi.HTTPException) as ctx:
                blueprint_values.validate(
                    self.matches, {'tags': ['other']}, partial=partial
                )
            self.assertEqual(ctx.exception.status_code, 422)
        # A PATCH with None still clears the key.
        self.assertEqual(
            blueprint_values.validate(
                self.matches, {'tags': None}, partial=True
            ),
            {'tags': None},
        )

    def test_array_items(self) -> None:
        for partial in (False, True):
            self.assertEqual(
                blueprint_values.validate(
                    self.matches,
                    {'counts': [0, 3], 'checks': [{'name': 'a'}]},
                    partial=partial,
                ),
                {'counts': [0, 3], 'checks': [{'name': 'a'}]},
            )
            # A string is not converted to an integer item, an item
            # minimum is checked, and so is the schema of an object item.
            for field, bad in (
                ('counts', ['3']),
                ('counts', [-1]),
                ('checks', [{}]),
            ):
                with self.assertRaises(fastapi.HTTPException) as ctx:
                    blueprint_values.validate(
                        self.matches, {field: bad}, partial=partial
                    )
                detail = typing.cast(
                    dict[str, typing.Any], ctx.exception.detail
                )
                self.assertEqual(detail['invalid'][0]['field'], field)

    def test_nested_object(self) -> None:
        for partial in (False, True):
            self.assertEqual(
                blueprint_values.validate(
                    self.matches,
                    {'payload': {'change_id': 1}},
                    partial=partial,
                ),
                {'payload': {'change_id': 1}},
            )
            for bad in ({}, {'change_id': 'invalid'}):
                with self.assertRaises(fastapi.HTTPException) as ctx:
                    blueprint_values.validate(
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
            blueprint_values.validate(matches, {}, partial=False)
        self.assertEqual(ctx.exception.status_code, 422)
        # A PATCH does not fill defaults, so it does not check them.
        self.assertEqual(
            blueprint_values.validate(matches, {}, partial=True), {}
        )

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
            blueprint_values.validate(
                local, {'payload': {'change': 1}}, partial=False
            ),
            {'payload': {'change': 1}},
        )
        with self.assertRaises(fastapi.HTTPException):
            blueprint_values.validate(
                local, {'payload': {'change': 'x'}}, partial=False
            )
        # A remote $ref is an invalid field, never a request.
        remote = [blueprint('https://example.invalid/change.json')]
        with (
            mock.patch('urllib.request.urlopen') as urlopen,
            self.assertRaises(fastapi.HTTPException) as ctx,
        ):
            blueprint_values.validate(
                remote, {'payload': {'change': 1}}, partial=False
            )
        urlopen.assert_not_called()
        detail = typing.cast(dict[str, typing.Any], ctx.exception.detail)
        self.assertEqual(detail['invalid'][0]['field'], 'payload')

    def test_field_id_scope(self) -> None:
        # A $ref in a field with an $id resolves inside that field.
        matches = [
            models.Blueprint(
                name='Scoped',
                type='Ticket',
                json_schema=models.Schema.model_validate(
                    {
                        'type': 'object',
                        'properties': {
                            'payload': {
                                '$id': 'urn:payload',
                                'type': 'object',
                                '$defs': {'N': {'type': 'integer'}},
                                'properties': {'n': {'$ref': '#/$defs/N'}},
                            }
                        },
                    }
                ),
            )
        ]
        self.assertEqual(
            blueprint_values.validate(
                matches, {'payload': {'n': 1}}, partial=False
            ),
            {'payload': {'n': 1}},
        )
        with self.assertRaises(fastapi.HTTPException):
            blueprint_values.validate(
                matches, {'payload': {'n': 'x'}}, partial=False
            )

    def test_field_schema_only(self) -> None:
        matches = [
            models.Blueprint(
                name='Field',
                type='Ticket',
                json_schema=models.Schema.model_validate(
                    {
                        'type': 'object',
                        'minProperties': 2,
                        'properties': {
                            'sample': {'type': 'integer', 'minimum': 0},
                            'a': {
                                'type': ['array', 'null'],
                                'items': {'type': 'integer', 'minimum': 0},
                            },
                            'b': {
                                'type': 'array',
                                'items': {'$ref': '#/properties/sample'},
                            },
                        },
                    }
                ),
            )
        ]
        # The root minProperties does not apply to one field, and a
        # $ref to another property resolves.
        self.assertEqual(
            blueprint_values.validate(
                matches, {'a': [1], 'b': [2]}, partial=False
            ),
            {'a': [1], 'b': [2]},
        )
        # A nullable array also gets the schema check.
        for field, bad in (('a', ['3']), ('a', [-1]), ('b', [-1])):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                blueprint_values.validate(matches, {field: bad}, partial=True)
            detail = typing.cast(dict[str, typing.Any], ctx.exception.detail)
            self.assertEqual(detail['invalid'][0]['field'], field)
        self.assertEqual(
            blueprint_values.validate(matches, {'a': None}, partial=True),
            {'a': None},
        )


class ValueCheckTests(unittest.TestCase):
    """``pattern``, ``multipleOf``, and item formats of ticket fields."""

    matches: typing.ClassVar[list[models.Blueprint]] = [
        models.Blueprint(
            name='Costs',
            type='Ticket',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'budget': {
                            'type': 'string',
                            'pattern': r'^\d+(\.\d{2})?$',
                        },
                        'rate': {'type': 'number', 'multipleOf': 0.01},
                        'owners': {
                            'type': 'array',
                            'items': {'type': 'string', 'format': 'uuid'},
                        },
                    },
                }
            ),
        )
    ]

    def test_valid_values(self) -> None:
        values = {
            'budget': '1250.00',
            'rate': 19.99,
            'owners': ['a8098c1a-f86e-11da-bd1a-00112444be1e'],
        }
        self.assertEqual(
            blueprint_values.validate(self.matches, values, partial=False),
            values,
        )

    def test_invalid_values(self) -> None:
        for field, bad in (
            ('budget', '12.5'),
            ('rate', 1.005),
            ('owners', ['nope']),
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                blueprint_values.validate(
                    self.matches, {field: bad}, partial=True
                )
            detail = typing.cast(dict[str, typing.Any], ctx.exception.detail)
            self.assertEqual(detail['error'], 'custom_fields_invalid')
            self.assertEqual(detail['invalid'][0]['field'], field)


class SectionPropertyTests(unittest.TestCase):
    """The form gets the keywords that it checks before a submit."""

    def test_checks_and_items(self) -> None:
        prop = blueprint_sections.section_property(
            models.Schema.model_validate(
                {
                    'type': 'array',
                    'items': {
                        'type': 'string',
                        'format': 'uuid',
                        'pattern': '^a',
                    },
                }
            )
        )
        self.assertEqual(
            prop.model_dump(exclude_none=True)['items'],
            {'type': 'string', 'format': 'uuid', 'pattern': '^a'},
        )
        prop = blueprint_sections.section_property(
            models.Schema.model_validate(
                {
                    'type': 'string',
                    'pattern': '^x$',
                    'minLength': 1,
                    'maxLength': 9,
                }
            )
        )
        dumped = prop.model_dump(exclude_none=True)
        self.assertEqual(dumped['pattern'], '^x$')
        self.assertEqual(dumped['minLength'], 1)
        self.assertEqual(dumped['maxLength'], 9)
        number = blueprint_sections.section_property(
            models.Schema.model_validate(
                {'type': 'number', 'multipleOf': 0.01}
            )
        )
        self.assertEqual(number.model_dump()['multipleOf'], 0.01)
