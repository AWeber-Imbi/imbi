"""Pin the IamIc error inheritance contract.

The host's poll loop catches ``IdentityAuthorizationPending`` and
``IdentityAuthorizationExpired`` from ``imbi_common.plugins.errors`` to
decide whether to keep polling or surface an expiry. The AWS IAM IC
plugin must raise its concrete errors as subclasses of those bases so
the host can route them without importing plugin-specific types. These
tests guard that contract.
"""

import unittest

from imbi_common.plugins.errors import (
    IdentityAuthorizationExpired,
    IdentityAuthorizationPending,
)

from imbi_plugin_aws.errors import (
    IamIcAuthorizationPending,
    IamIcDeviceFlowExpired,
)


class ErrorInheritanceTestCase(unittest.TestCase):
    def test_pending_is_subclass_of_identity_pending(self) -> None:
        self.assertTrue(
            issubclass(IamIcAuthorizationPending, IdentityAuthorizationPending)
        )

    def test_expired_is_subclass_of_identity_expired(self) -> None:
        self.assertTrue(
            issubclass(IamIcDeviceFlowExpired, IdentityAuthorizationExpired)
        )

    def test_pending_caught_as_identity_pending(self) -> None:
        with self.assertRaises(IdentityAuthorizationPending):
            raise IamIcAuthorizationPending

    def test_expired_caught_as_identity_expired(self) -> None:
        with self.assertRaises(IdentityAuthorizationExpired):
            raise IamIcDeviceFlowExpired
