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


def create_spec(spec_dict: dict) -> models.Spec:
    """Create and return the OpenAPI v3 Spec Model"""
    spec_resolver = jsonschema_validators.RefResolver(
        '', spec_dict, handlers=openapi_spec_validator.default_handlers)
    spec_factory = factories.SpecFactory(
        spec_resolver, config={'validate_spec': False})
    return spec_factory.create(spec_dict, spec_url='')


def request_validator(settings: dict) -> tornado_openapi3.RequestValidator:
    return tornado_openapi3.RequestValidator(
        spec=create_spec(_render_template(settings)),
        custom_formatters={
            'email': EMailFormatter,
            'iso8601-timestamp': ISO8601Formatter,
            'uri': URIFormatter
        },
        custom_media_type_deserializers={
            'application/json-patch+json': json.loads,
            'application/json-patch+msgpack': umsgpack.unpackb,
            'application/msgpack': umsgpack.unpackb,
            'application/problem+json': json.loads,
            'application/problem+msgpack': umsgpack.unpackb,
            'application/yaml': yaml.safe_load})


def response_validator(settings: dict) -> tornado_openapi3.ResponseValidator:
    return tornado_openapi3.ResponseValidator(
        spec=create_spec(_render_template(settings)),
        custom_formatters={
            'email': EMailFormatter,
            'iso8601-timestamp': ISO8601Formatter,
            'uri': URIFormatter
        },
        custom_media_type_deserializers={
            'application/json-patch+json': json.loads,
            'application/json-patch+msgpack': umsgpack.unpackb,
            'application/msgpack': umsgpack.unpackb,
            'application/problem+json': json.loads,
            'application/problem+msgpack': umsgpack.unpackb,
            'application/yaml': yaml.safe_load})


def _render_template(settings: dict) -> dict:
    """Load the template file and render it, replacing any template markup"""
    spec = yaml.safe_load(
        template.Loader(str(settings['template_path'])).load(
            'openapi.yaml').generate(**{'settings': settings}))
    # Remove servers for validation to prevent hostname validation errors
    if 'servers' in spec:
        del spec['servers']
    return spec
