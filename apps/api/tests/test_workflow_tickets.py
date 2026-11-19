"""Tests for :mod:`imbi.api.workflows.tickets`."""

import typing
import unittest
from unittest import mock

from imbi.api.workflows import tickets
from imbi.common.workflows.registry import slack


def _task(**changes: typing.Any) -> dict[str, typing.Any]:
    return {
        'short_id': 'T-3',
        'title': 'Fix <!here>',
        'status': 'closed',
        'outcome': 'done_acted',
        'projects': [],
        **changes,
    }


class TicketBlockTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.config = mock.Mock(ui_url='')
        patcher = mock.patch.object(
            tickets.settings, 'get_server_config', return_value=self.config
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_without_a_ui_url_the_title_is_not_a_link(self) -> None:
        self.assertEqual(
            tickets.with_ticket_block('Hi', _task(), 'eng'),
            'Hi\n\n*T-3: Fix &lt;!here&gt;*\n'
            'Status: closed | Outcome: done_acted | Project: none',
        )

    def test_long_text_is_cut_to_max_text(self) -> None:
        self.config.ui_url = 'https://imbi.example.com'
        text = tickets.with_ticket_block('x' * slack.MAX_TEXT, _task(), 'eng')
        self.assertEqual(len(text), slack.MAX_TEXT)
        self.assertTrue(
            text.endswith(
                '\n\n*<https://imbi.example.com/tickets/eng/T-3|'
                'T-3: Fix &lt;!here&gt;>*\n'
                'Status: closed | Outcome: done_acted | Project: none'
            )
        )
