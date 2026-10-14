import typing
import unittest

from imbi.harness import policy

ALLOWED = ['Bash', 'Read', 'mcp__imbi__run_with_secret']


def check(
    name: str,
    arguments: dict[str, typing.Any] | None = None,
    **changes: typing.Any,
) -> policy.Check:
    options: dict[str, typing.Any] = {
        'allowed': ALLOWED,
        'tool_map': {
            'deploy.run': {
                'approval': False,
                'environments': ['staging'],
                'rate_limit': {'count': 2, 'per': 'hour'},
            },
            'tickets.close': {'approval': True},
            'imbi.run_with_secret': {'rate_limit': {'count': 1, 'per': 'day'}},
        },
        'approval_tools': ['Bash', 'tickets.open'],
        'automation': False,
    } | changes
    return policy.check(name, arguments or {}, **options)


class PolicyTestCase(unittest.TestCase):
    def test_tool_key(self) -> None:
        self.assertEqual(policy.tool_key('mcp__deploy__run'), 'deploy.run')
        self.assertIsNone(policy.tool_key('Bash'))

    def test_builtins_follow_the_allowed_tools(self) -> None:
        self.assertEqual(check('Read'), policy.Check())
        self.assertEqual(check('Write').deny, 'tool_not_allowed')
        self.assertEqual(check('Task').deny, 'tool_not_allowed')

    def test_mcp_tools_need_the_tool_map(self) -> None:
        self.assertEqual(check('mcp__other__x').deny, 'tool_not_configured')
        self.assertEqual(check('mcp__imbi__request_input'), policy.Check())
        self.assertEqual(
            check('mcp__imbi__run_with_secret').rate_key,
            'imbi.run_with_secret',
        )

    def test_environment_limit(self) -> None:
        self.assertEqual(
            check('mcp__deploy__run', {'environment': 'production'}).deny,
            'environment_not_allowed',
        )
        allowed = check('mcp__deploy__run', {'environment': 'staging'})
        self.assertIsNone(allowed.deny)
        self.assertEqual(allowed.rate_key, 'deploy.run')
        # No environment argument: the limit does not apply.
        self.assertIsNone(check('mcp__deploy__run').deny)

    def test_approval(self) -> None:
        self.assertTrue(check('mcp__tickets__close').approval)
        # Origin rules apply only when the origin is not a person.
        self.assertFalse(check('Bash').approval)
        self.assertTrue(check('Bash', automation=True).approval)
        self.assertFalse(
            check(
                'mcp__tickets__open',
                automation=True,
                tool_map={'tickets.open': {}},
            ).deny
        )
        self.assertTrue(
            check(
                'mcp__tickets__open',
                automation=True,
                tool_map={'tickets.open': {}},
            ).approval
        )
