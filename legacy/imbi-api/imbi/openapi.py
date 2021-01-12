import datetime
import json
import logging
import pathlib
import tempfile

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
        spec=_get_openapi_spec(settings),
        custom_formatters={
            'email': EMailFormatter,
            'iso8601-timestamp': ISO8601Formatter,
            'uri': URIFormatter
        },
        custom_media_type_deserializers={
            'application/json; charset="utf-8"': json.loads,
            'application/msgpack': umsgpack.unpackb,
            'application/problem+json': json.loads,
            'application/yaml': yaml.safe_load})


def response_validator(settings: dict) -> tornado_openapi3.ResponseValidator:
    return tornado_openapi3.ResponseValidator(
        spec=_get_openapi_spec(settings),
        custom_formatters={
            'email': EMailFormatter,
            'iso8601-timestamp': ISO8601Formatter,
            'uri': URIFormatter
        },
        custom_media_type_deserializers={
            'application/json; charset="utf-8"': json.loads,
            'application/msgpack': umsgpack.unpackb,
            'application/problem+json': json.loads,
            'application/yaml': yaml.safe_load})


def _get_openapi_spec(settings: dict) -> models.Spec:
    """Return the OpenAPI spec for the application

    Renders a JSON or YAML based OpenAPI spec and returns the model
    that is passed into the validator.

    raises: RuntimeError

    """
    rendered = pathlib.Path(tempfile.gettempdir()) / 'imbi-openapi.yaml'
    if not rendered.exists() or settings.get('debug'):
        LOGGER.debug('Rendering %s', rendered)
        loader = template.Loader(str(settings['template_path']))
        spec_str = loader.load('openapi.yaml').generate(**{
            'settings': settings
        })
        spec = yaml.safe_load(spec_str)
        if 'servers' in spec:
            del spec['servers']
        with rendered.open('w') as handle:
            yaml.dump(spec, handle)
    with rendered.open('r') as handle:
        spec = yaml.safe_load(handle)
    return create_spec(spec)
