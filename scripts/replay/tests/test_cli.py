"""Tests for the command line checks that need no database."""

import pathlib
import tempfile
import unittest

from scripts.replay import __main__ as cli


class OutsideRepositoryTestCase(unittest.TestCase):
    def test_refuses_a_path_in_a_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            (root / '.git').write_text('gitdir: elsewhere\n')
            with self.assertRaises(SystemExit):
                cli.outside_repository(root / 'recordings' / 'old')

    def test_accepts_a_path_outside(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            path = pathlib.Path(name) / 'old'
            self.assertEqual(cli.outside_repository(path), path)

    def test_main_checks_out_before_it_runs(self) -> None:
        here = pathlib.Path(__file__).parent / 'recording'
        with self.assertRaises(SystemExit) as raised:
            cli.main(['diff', '--old', 'a', '--new', 'b', '--json', str(here)])
        self.assertIn('inside the git worktree', str(raised.exception))
