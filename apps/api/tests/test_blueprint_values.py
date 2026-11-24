"""Tests for the check of blueprint values."""

import typing
import unittest
from unittest import mock

import fastapi

from imbi.api import blueprint_values
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
