import datetime
import json
import logging

import iso8601
import openapi_spec_validator
import tornado_openapi3
import umsgpack
import validators
import yaml
from jsonschema import validators as jsonschema_validators
from openapi_core.schema.specs import factories, models
from tornado import template

from imbi import transcoders

LOGGER = logging.getLogger(__name__)


class EMailFormatter:

    @staticmethod
    def validate(value) -> bool:
        return validators.email(value)

    @staticmethod
    def unmarshal(value: str) -> str:
        return value


class ISO8601Formatter:

    @staticmethod
    def validate(value) -> bool:
        try:
            iso8601.parse_date(value)
        except iso8601.ParseError:
            return False
        return True

    @staticmethod
    def unmarshal(value: str) -> datetime.datetime:
        return iso8601.parse_date(value)


class URIFormatter:

    @staticmethod
    def validate(value) -> bool:
        return validators.url(value)

    @staticmethod
    def unmarshal(value: str) -> str:
        return value


_openapi_formatters = {
    'email': EMailFormatter,
    'iso8601-timestamp': ISO8601Formatter,
    'uri': URIFormatter,
}
_openapi_deserializers = {
    'application/json-patch+json': json.loads,
    'application/json-patch+msgpack': umsgpack.unpackb,
    'application/msgpack': umsgpack.unpackb,
    'application/problem+json': json.loads,
    'application/problem+msgpack': umsgpack.unpackb,
    'application/x-www-form-urlencoded': transcoders.parse_form_body,
    'application/yaml': yaml.safe_load,
}

# This is updated in `create_spec` the first time that it is called.
# "uncaching" this causes a 10x performance hit in testing
_openapi_spec_dict = {}


def create_spec(settings: dict) -> models.Spec:
    """Create and return the OpenAPI v3 Spec Model"""
    if not _openapi_spec_dict:
        loader = template.Loader(str(settings['template_path']))
        _openapi_spec_dict.update(yaml.safe_load(
            loader.load('openapi.yaml').generate(settings=settings)))
        # Remove servers for validation to prevent hostname validation errors
        _openapi_spec_dict.pop('servers', None)

    spec_resolver = jsonschema_validators.RefResolver(
        '', _openapi_spec_dict,
        handlers=openapi_spec_validator.default_handlers)
    spec_factory = factories.SpecFactory(
        spec_resolver, config={'validate_spec': False})
    return spec_factory.create(_openapi_spec_dict, spec_url='')


def request_validator(settings: dict) -> tornado_openapi3.RequestValidator:
    return tornado_openapi3.RequestValidator(
        spec=create_spec(settings),
        custom_formatters=_openapi_formatters,
        custom_media_type_deserializers=_openapi_deserializers)
