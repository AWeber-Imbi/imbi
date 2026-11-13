import hashlib
import os
import unittest
from unittest import mock

import anthropic
from posthog.ai import anthropic as ph_anthropic

from imbi.common.llm import observability


class ObservabilityTestCase(unittest.TestCase):
    @mock.patch.dict(os.environ, {'POSTHOG_API_KEY': 'phc_x'}, clear=True)
    def test_plain_client_when_switch_off(self) -> None:
        self.assertIs(observability.client_class(), anthropic.AsyncAnthropic)

    @mock.patch('imbi.common.posthog.init', return_value=True)
    @mock.patch.dict(
        os.environ,
        {'POSTHOG_API_KEY': 'phc_x', 'POSTHOG_AI_OBSERVABILITY': 'true'},
        clear=True,
    )
    def test_wrapper_when_switch_on(self, _init: mock.MagicMock) -> None:
        self.assertIs(
            observability.client_class(), ph_anthropic.AsyncAnthropic
        )

    def test_tracking(self) -> None:
        self.assertEqual(
            observability.tracking('A@B.c', 'trace'),
            {
                'posthog_distinct_id': hashlib.sha256(b'a@b.c').hexdigest(),
                'posthog_trace_id': 'trace',
            },
        )
