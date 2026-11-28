"""Tests for one JSON answer with a prompt that Imbi ships."""

import unittest
from unittest import mock

from imbi.api.auth import permissions
from imbi.api.llm import prompted
from imbi.common.llm import resolve as llm_resolve
from imbi.common.prompts import system as system_prompts


class CompleteTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_unusable_model_is_degraded_with_no_call(self) -> None:
        # No other model is used in place of the prompt's model.
        anthropic = mock.AsyncMock()
        error = llm_resolve.ModelUnusable('disabled', 'opus', 'no')
        fallback = prompted.Description(description='current')
        with mock.patch.object(
            system_prompts,
            'load_system_prompt',
            mock.AsyncMock(side_effect=error),
        ):
            result = await prompted.complete(
                mock.AsyncMock(),
                anthropic,
                system_prompts.TICKET_SUBJECT,
                'text',
                fallback,
                permissions.AuthContext(
                    user=None, session_id=None, auth_method='jwt'
                ),
            )
        self.assertTrue(result.degraded)
        self.assertEqual(result.data, fallback)
        anthropic.complete_json.assert_not_awaited()
