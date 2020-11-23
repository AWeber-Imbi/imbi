"""
Common methods and constants

"""
import logging
import os
import pkgutil
import re
from os import path

import jsonschema
import yaml
from tornado import web

LOGGER = logging.getLogger(__name__)

DEFAULT_COOKIE_SECRET = 'imbi'
SIGNED_VALUE_PATTERN = re.compile(r'^(?:[1-9][0-9]*)\|(?:.*)$')
UUID_PATTERN = r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'

_schema_cache = {}


def ldap_enabled():
    """Returns a boolean indicating if LDAP is enabled.

    :rtype: bool

    """
    return os.environ.get('LDAP_ENABLED', 'FALSE').lower() == 'true'


def jsonschema_validate(schema_file, value, from_openapi_spec=True):
    """Validate the given value against the specified jsonschema file

    :param str schema_file:
    :param mixed value:
    :param bool from_openapi_spec: Indicates schema is in an openapi spec
    :raises: ValueError

    """
    global _schema_cache

    if schema_file not in _schema_cache:
        _schema_cache[schema_file] = yaml.safe_load(pkgutil.get_data(
            __name__.split('.')[0],
            path.join('schema', schema_file))
        )
        if from_openapi_spec:
            _schema_cache[schema_file] = \
                _schema_cache[schema_file]['components']['schemas']['record']

    message = None
    try:
        jsonschema.validate(value, _schema_cache[schema_file])
    except jsonschema.ValidationError as error:
        LOGGER.error('ValidationError: %s (%r, %r)',
                     error, error.validator, error.validator_value)
        message = error.message
    if message:
        raise ValueError(message)


def is_encrypted_value(value):
    """Checks to see if the value matches the format for a signed value using
    Tornado's signing methods.

    :param str value: The value to check
    :rtype: bool

    """
    if value is None or not isinstance(value, str):
        return False
    return SIGNED_VALUE_PATTERN.match(value) is not None


def encrypt_value(key, value):
    """Encrypt a value using the code used to create Tornado's secure cookies,
    using the common cookie secret.

    :param str or bytes key: The name of the field containing the value
    :param str or bytes value: The value to encrypt
    :rtype: str

    """
    return web.create_signed_value(
        os.environ.get('COOKIE_SECRET', DEFAULT_COOKIE_SECRET),
        key, value).decode('utf-8')


def decrypt_value(key, value):
    """Decrypt a value that is encrypted using Tornado's secure cookie
    signing methods.

    :param str or bytes key: The name of the field containing the value
    :param str or bytes value: The value to decrypt
    :rtype: str

    """
    return web.decode_signed_value(
        os.environ.get('COOKIE_SECRET', DEFAULT_COOKIE_SECRET), key, value)
