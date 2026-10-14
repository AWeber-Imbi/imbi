"""``imbi-harness runner`` and ``imbi-harness executor``.

Both start as uid 0 with only ``CAP_SETUID`` and ``CAP_SETGID``, and
drop to their own user before they do any other work.
"""

import argparse
import logging

from imbi.harness import executor, runner


def main() -> None:
    parser = argparse.ArgumentParser(prog='imbi-harness')
    parser.add_argument('process', choices=['runner', 'executor'])
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    if args.process == 'runner':
        runner.main()
    else:
        executor.main()
