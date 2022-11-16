import hmac
import random
import string
import unittest

import imbi.keychain


class KeychainCreationTests(unittest.TestCase):
    def test_that_32_byte_key_is_required(self):
        with self.assertRaises(ValueError):
            imbi.keychain.Keychain(b'not 32 bytes')


class PasswordHashingTests(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.key = b'some thirty-two character secret'

    def test_that_hash_uses_secret_as_hmac_key(self):
        encrypter = hmac.new(self.key, digestmod='SHA512')
        encrypter.update(b'my secret')
        keychain = imbi.keychain.Keychain(self.key)
        self.assertEqual(encrypter.digest(), keychain.hash('my secret'))


class EncryptionTests(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.key = b'some thirty-two character secret'

    def test_symmetric_encryption(self):
        # generate some random "words"
        plaintext = ' '.join(''.join(
            random.choice(string.ascii_letters)
            for _ in range(random.randint(5, 10)))
                             for _ in range(random.randint(10, 15))).encode()

        # round trip them through the keychain
        keychain = imbi.keychain.Keychain(self.key)
        ciphertext = keychain.encrypt(plaintext)
        self.assertEqual(plaintext, keychain.decrypt(ciphertext))

    def test_decryption_with_tampered_ciphertext(self):
        keychain = imbi.keychain.Keychain(self.key)
        ciphertext = keychain.encrypt(b'some plain text')
        ciphertext = ciphertext[5:] + ciphertext[:5]
        with self.assertRaises(imbi.keychain.DecryptionFailure):
            keychain.decrypt(ciphertext)

    def test_that_keychains_with_same_key_can_roundtrip(self):
        plaintext = b'my dirty little secret'
        keychain1 = imbi.keychain.Keychain(self.key)
        ciphertext = keychain1.encrypt(plaintext)

        keychain2 = imbi.keychain.Keychain(self.key)
        self.assertEqual(plaintext, keychain2.decrypt(ciphertext))
