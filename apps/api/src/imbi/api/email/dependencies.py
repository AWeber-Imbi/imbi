"""FastAPI dependency injection for email subsystem."""

import typing

import fastapi
from imbi_common.lifespan import InjectLifespan

from imbi_api import lifespans

from .client import EmailClient
from .templates import TemplateManager


def _get_email_client(
    context: InjectLifespan,
) -> EmailClient:
    client, _ = context.get_state(lifespans.email_hook)
    return client


def _get_template_manager(
    context: InjectLifespan,
) -> TemplateManager:
    _, templates = context.get_state(lifespans.email_hook)
    return templates


InjectEmailClient = typing.Annotated[
    EmailClient, fastapi.Depends(_get_email_client)
]

InjectTemplateManager = typing.Annotated[
    TemplateManager, fastapi.Depends(_get_template_manager)
]
