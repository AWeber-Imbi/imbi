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

    def test_value_split_by_the_read_limit(self) -> None:
        # The reader kept MAX_OUTPUT + OVERLAP bytes and cut a value.
        kept = (b'y' * redact.MAX_OUTPUT + VALUE + b'z' * redact.OVERLAP)[
            : redact.MAX_OUTPUT + redact.OVERLAP
        ]
        kept = kept[: -redact.OVERLAP + 6]  # ends inside a second value
        kept += VALUE[:6]
        text = redact.redact(kept, [VALUE], truncated=True)
        self.assertTrue(text.endswith('[output truncated]'))
        self.assertNotIn(VALUE[:6].decode(), text)


class RedactorTestCase(unittest.TestCase):
    def test_known_formats(self) -> None:
        subject = redact.Redactor()
        cases = [
            'ghp_' + 'a' * 36,
            'ghs_' + 'B' * 40,
            'github_pat_' + 'c' * 30,
            'sk-ant-api03-' + 'd' * 30,
            'AKIA' + 'E' * 16,
            'xoxb-1234567890-abcdef',
            'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZ2VudCJ9.c2lnbmF0dXJlc2ln',
            '-----BEGIN RSA PRIVATE KEY-----\nMIIx\n'
            '-----END RSA PRIVATE KEY-----',
        ]
        for value in cases:
            with self.subTest(value=value[:12]):
                self.assertEqual(
                    subject.text(f'a {value} b'), 'a [REDACTED] b'
                )
        self.assertEqual(
            subject.text('sk-short ghp_short'), 'sk-short ghp_short'
        )

    def test_values_and_their_encodings(self) -> None:
        subject = redact.Redactor()
        subject.add(VALUE.decode(), '')
        encoded = base64.b64encode(VALUE).decode()
        text = subject.text(
            f'{VALUE.decode()} {encoded} {urllib.parse.quote(VALUE)}'
        )
        self.assertNotIn(VALUE.decode(), text)
        self.assertNotIn(encoded[:-4], text)

    def test_payload(self) -> None:
        subject = redact.Redactor()
        subject.add('my-secret-value')
        self.assertEqual(
            subject.payload(
                {
                    'a': [
                        'my-secret-value',
                        1,
                        None,
                        {'my-secret-value': True},
                    ],
                    'b': 2.5,
                }
            ),
            {'a': ['[REDACTED]', 1, None, {'[REDACTED]': True}], 'b': 2.5},
        )
