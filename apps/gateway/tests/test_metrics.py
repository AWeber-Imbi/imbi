"""Tests for the gateway's webhook-disposition counters."""

import unittest
from unittest import mock

from imbi.gateway import metrics


class DeploymentEventTests(unittest.TestCase):
    def setUp(self) -> None:
        metrics._counter = None
        self.addCleanup(setattr, metrics, '_counter', None)

    def test_counts_with_the_disposition_and_project(self) -> None:
        counter = mock.Mock()
        meter = mock.Mock(create_counter=mock.Mock(return_value=counter))
        with mock.patch.object(
            metrics, '_otel_metrics', mock.Mock(get_meter=lambda _n: meter)
        ):
            metrics.deployment_event('orphaned', 'p1')
            metrics.deployment_event('recorded', 'p1')
        self.assertEqual(
            [
                mock.call(1, {'disposition': 'orphaned', 'project_id': 'p1'}),
                mock.call(1, {'disposition': 'recorded', 'project_id': 'p1'}),
            ],
            counter.add.call_args_list,
        )
        # One counter, created once, reused after that.
        meter.create_counter.assert_called_once()

    def test_no_op_without_opentelemetry(self) -> None:
        with mock.patch.object(metrics, '_otel_metrics', None):
            metrics.deployment_event('recorded', 'p1')
        self.assertIsNone(metrics._counter)
