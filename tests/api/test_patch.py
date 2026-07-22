"""Tests for JSON Patch (RFC 6902) utilities."""

import unittest

import fastapi

from imbi_api import patch


class ApplyPatchTests(unittest.TestCase):
    """Tests for apply_patch()."""

    def test_replace_operation(self) -> None:
        """Test replacing a field value."""
        doc = {'name': 'Old', 'slug': 'old'}
        ops = [patch.PatchOperation(op='replace', path='/name', value='New')]
        result = patch.apply_patch(doc, ops)
        self.assertEqual(result['name'], 'New')
        self.assertEqual(result['slug'], 'old')

    def test_remove_operation(self) -> None:
        """Test removing an optional field."""
        doc = {'name': 'Test', 'description': 'Desc'}
        ops = [patch.PatchOperation(op='remove', path='/description')]
        result = patch.apply_patch(doc, ops)
        self.assertNotIn('description', result)

    def test_add_operation(self) -> None:
        """Test adding a new field."""
        doc = {'name': 'Test'}
        ops = [
            patch.PatchOperation(op='add', path='/description', value='Desc')
        ]
        result = patch.apply_patch(doc, ops)
        self.assertEqual(result['description'], 'Desc')

    def test_test_operation_passes(self) -> None:
        """Test that a passing test operation is a no-op."""
        doc = {'name': 'Test'}
        ops = [patch.PatchOperation(op='test', path='/name', value='Test')]
        result = patch.apply_patch(doc, ops)
        self.assertEqual(result, doc)

    def test_test_operation_fails_raises_422(self) -> None:
        """Test that a failing test operation raises 422."""
        doc = {'name': 'Test'}
        ops = [patch.PatchOperation(op='test', path='/name', value='Wrong')]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            patch.apply_patch(doc, ops)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_readonly_path_raises_400(self) -> None:
        """Test that patching a read-only path raises 400."""
        doc = {'name': 'Test', 'created_at': '2024-01-01T00:00:00Z'}
        ops = [
            patch.PatchOperation(
                op='replace',
                path='/created_at',
                value='2025-01-01T00:00:00Z',
            )
        ]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            patch.apply_patch(doc, ops)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_readonly_subpath_raises_400(self) -> None:
        """Test that patching a sub-path of a read-only path raises 400."""
        doc = {'relationships': {'teams': {'count': 0, 'href': '/api/...'}}}
        ops = [
            patch.PatchOperation(
                op='replace',
                path='/relationships/teams',
                value={'count': 1, 'href': '/api/...'},
            )
        ]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            patch.apply_patch(doc, ops)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_patch_raises_400(self) -> None:
        """Test that an invalid patch (e.g., remove nonexistent) raises 400."""
        doc = {'name': 'Test'}
        ops = [patch.PatchOperation(op='remove', path='/nonexistent')]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            patch.apply_patch(doc, ops)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_custom_readonly_paths(self) -> None:
        """Test that custom readonly_paths are respected."""
        doc = {'name': 'Test', 'email': 'test@example.com'}
        ops = [
            patch.PatchOperation(
                op='replace', path='/email', value='other@example.com'
            )
        ]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            patch.apply_patch(doc, ops, readonly_paths=frozenset(['/email']))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_from_field_alias(self) -> None:
        """Test PatchOperation accepts 'from' as alias for from_."""
        op = patch.PatchOperation.model_validate(
            {'op': 'move', 'path': '/b', 'from': '/a'}
        )
        self.assertEqual(op.from_, '/a')

    def test_replace_with_null_value(self) -> None:
        """Test that null (None) is a valid patch value."""
        doc = {'name': 'Test', 'description': 'Existing'}
        ops = [
            patch.PatchOperation(op='replace', path='/description', value=None)
        ]
        result = patch.apply_patch(doc, ops)
        self.assertIsNone(result['description'])

    def test_move_from_readonly_path_raises_400(self) -> None:
        """Test that move from a read-only path raises 400."""
        doc = {'name': 'Test', 'created_at': '2024-01-01T00:00:00Z'}
        ops = [
            patch.PatchOperation.model_validate(
                {'op': 'move', 'from': '/created_at', 'path': '/name'}
            )
        ]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            patch.apply_patch(doc, ops)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_root_path_raises_400(self) -> None:
        """Test that patching the root path raises 400."""
        doc = {'name': 'Test'}
        ops = [patch.PatchOperation(op='replace', path='', value={'x': 1})]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            patch.apply_patch(doc, ops)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('Root path', ctx.exception.detail)
