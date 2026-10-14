import base64
import unittest
import urllib.parse

from imbi.harness import redact

VALUE = b'ghs_0123456789abcdefABCDEF0123456789abcd'


class RedactTestCase(unittest.TestCase):
    def check(self, output: bytes) -> str:
        text = redact.redact(output, [VALUE])
        self.assertIn('[REDACTED]', text)
        self.assertNotIn(VALUE.decode(), text)
        return text

    def test_exact_value(self) -> None:
        text = self.check(b'token=' + VALUE + b'\n')
        self.assertEqual(text, 'token=[REDACTED]\n')

    def test_hex(self) -> None:
        self.check(VALUE.hex().encode())
        self.check(VALUE.hex().upper().encode())

    def test_url_encoding(self) -> None:
        value = b'a b/c+d=e&f?g' * 3
        text = redact.redact(
            urllib.parse.quote(value, safe='').encode(), [value]
        )
        self.assertEqual(text, '[REDACTED]')

    def test_base64_at_each_offset(self) -> None:
        # `echo "$TOKEN" | base64` and a value inside a larger document
        # put the value at each position of the 3-byte groups.
        for prefix in (b'', b'x', b'xy', b'{"token": "'):
            for suffix in (b'', b'\n', b'"}'):
                for encode in (base64.b64encode, base64.urlsafe_b64encode):
                    with self.subTest(prefix=prefix, suffix=suffix):
                        encoded = encode(prefix + VALUE + suffix)
                        text = redact.redact(encoded, [VALUE])
                        self.assertIn('[REDACTED]', text)
                        self.assertNotIn(
                            base64.b64encode(VALUE)[4:-4].decode(), text
                        )

    def test_truncates_after_redaction(self) -> None:
        output = b'x' * (redact.MAX_OUTPUT - 3) + VALUE
        text = redact.redact(output, [VALUE])
        self.assertTrue(text.endswith('[output truncated]'))
        self.assertNotIn(VALUE[:3].decode() + VALUE[3:6].decode(), text)

    def test_no_values(self) -> None:
        self.assertEqual(redact.redact(b'plain', []), 'plain')
        self.assertEqual(redact.redact(b'plain', [b'']), 'plain')
