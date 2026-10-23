"""``imbi-harness runner``, ``executor``, and ``egress-sync``.

The runner and the executor start as uid 0 with only ``CAP_SETUID`` and
``CAP_SETGID``, and drop to their own user before they do any other
work. ``egress-sync`` runs in its own pod as a service user.
"""

import argparse
import logging

from imbi.harness import egress, executor, runner


def main() -> None:
    parser = argparse.ArgumentParser(prog='imbi-harness')
    parser.add_argument(
        'process', choices=['runner', 'executor', 'egress-sync']
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    if args.process == 'runner':
        runner.main()
    elif args.process == 'executor':
        executor.main()
    else:
        egress.sync_main()
