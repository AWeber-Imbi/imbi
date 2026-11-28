"""Static catalog of the LLM provider drivers Imbi knows how to talk to.

Drivers are code, not graph nodes: adding one is a release, not a
backfill, and an ``AIProvider`` node exists only when an admin
configures one.  The catalog is what lets the admin UI render an
unconfigured driver as a "Set up" row and hide actions the driver does
not support.
"""

import re
import typing

import pydantic

__all__ = [
    'DRIVERS',
    'DRIVERS_BY_SLUG',
    'DriverInfo',
    'check_location',
    'get_driver',
    'resolve_base_url',
]


class DriverInfo(pydantic.BaseModel):
    """One entry in the static provider-driver catalog."""

    model_config = pydantic.ConfigDict(frozen=True)

    slug: str
    name: str
    description: str
    #: Endpoint used when a provider leaves ``base_url`` unset. ``None``
    #: for drivers that have no sensible default (``openai_compatible``)
    #: or that do not address a single HTTP endpoint (``bedrock``,
    #: ``vertex``).
    default_base_url: str | None = None
    #: The driver can authenticate from ambient cloud credentials, so a
    #: provider with no API key is still usable.
    supports_iam: bool = False
    #: Imbi can call the driver with the cloud credentials of its own
    #: process (Bedrock: SigV4 with the runtime IAM role).
    ambient_auth: bool = False
    #: ``base_url`` must be supplied when configuring this driver.
    requires_base_url: bool = False
    #: A model list can be pulled from the provider (see the
    #: ``/discover`` endpoint).
    supports_discovery: bool = False
    #: The model types (see ``AIModel.model_type``) this driver serves.
    model_types: tuple[typing.Literal['generative', 'decision'], ...] = (
        'generative',
    )
    #: lucide-react icon name for the admin UI.
    icon: str


#: The driver of the Anthropic API, the only driver that the assistant
#: and the Slack bot can call.
ANTHROPIC = 'anthropic'

DRIVERS: tuple[DriverInfo, ...] = (
    DriverInfo(
        slug='anthropic',
        name='Anthropic',
        description='Claude models served by the Anthropic API.',
        default_base_url='https://api.anthropic.com',
        supports_discovery=True,
        icon='Sparkles',
    ),
    DriverInfo(
        slug='openai',
        name='OpenAI',
        description='GPT models served by the OpenAI API.',
        default_base_url='https://api.openai.com/v1',
        supports_discovery=True,
        icon='Bot',
    ),
    DriverInfo(
        slug='openai_compatible',
        name='OpenAI-compatible',
        description=(
            'Any endpoint that implements the OpenAI chat-completions '
            'API, such as vLLM, Ollama, or a gateway.'
        ),
        requires_base_url=True,
        supports_discovery=True,
        icon='Server',
    ),
    DriverInfo(
        slug='bedrock',
        name='AWS Bedrock',
        description=(
            'Models served through AWS Bedrock, authenticated with an '
            'API key or the runtime IAM role.'
        ),
        supports_iam=True,
        ambient_auth=True,
        supports_discovery=True,
        icon='Cloud',
    ),
    DriverInfo(
        slug='vertex',
        name='Google Vertex AI',
        description='Models served through Google Cloud Vertex AI.',
        supports_iam=True,
        supports_discovery=True,
        icon='Cloud',
    ),
    DriverInfo(
        slug='typesafe',
        name='TypeSafe',
        description=(
            'System One decision models, such as Jev, that return typed '
            'judgments and probabilities instead of text.'
        ),
        default_base_url='https://api.typesafe.ai/v1',
        model_types=('decision',),
        icon='Scale',
    ),
)

DRIVERS_BY_SLUG: dict[str, DriverInfo] = {d.slug: d for d in DRIVERS}


def get_driver(slug: str) -> DriverInfo | None:
    """Return the catalog entry for ``slug``, or ``None`` if unknown."""
    return DRIVERS_BY_SLUG.get(slug)


def resolve_base_url(driver: str, base_url: str | None) -> str | None:
    """Return the endpoint a provider should call.

    The provider's own ``base_url`` wins; otherwise the driver default,
    which is ``None`` for drivers that have none.
    """
    if base_url:
        return base_url.rstrip('/')
    info = DRIVERS_BY_SLUG.get(driver)
    return info.default_base_url if info else None


#: ``region`` and ``project_id`` become part of a host name or a path.
#: Only these shapes are allowed, so that a value cannot send the
#: credential to a different host.
_AWS_REGION = re.compile(r'[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-\d+')
_GCP_REGION = re.compile(r'global|[a-z]+-[a-z]+\d+')
_GCP_PROJECT = re.compile(r'[a-z][a-z0-9-]{4,28}[a-z0-9]')


def check_location(
    driver: str, region: str | None, project_id: str | None
) -> None:
    """Make sure that ``region`` and ``project_id`` are safe in a URL.

    Raises:
        ValueError: A value has an incorrect shape for ``driver``.

    """
    if driver == 'bedrock' and region and not _AWS_REGION.fullmatch(region):
        raise ValueError(f'{region!r} is not a valid AWS region')
    if driver != 'vertex':
        return
    if region and not _GCP_REGION.fullmatch(region):
        raise ValueError(f'{region!r} is not a valid Google Cloud region')
    if project_id and not _GCP_PROJECT.fullmatch(project_id):
        raise ValueError(
            f'{project_id!r} is not a valid Google Cloud project ID'
        )
