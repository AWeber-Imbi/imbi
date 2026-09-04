"""Static catalog of the LLM provider drivers Imbi knows how to talk to.

Drivers are code, not graph nodes: adding one is a release, not a
backfill, and an organization gets an ``AIProvider`` node only when an
admin configures one.  The catalog is what lets the admin UI render an
unconfigured driver as a "Set up" row and hide actions the driver does
not support.
"""

import pydantic

__all__ = [
    'DRIVERS',
    'DRIVERS_BY_SLUG',
    'DriverInfo',
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
    #: ``base_url`` must be supplied when configuring this driver.
    requires_base_url: bool = False
    #: A model list can be pulled from the provider (see the
    #: ``/discover`` endpoint).
    supports_discovery: bool = False
    #: lucide-react icon name for the admin UI.
    icon: str


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
        icon='Cloud',
    ),
    DriverInfo(
        slug='vertex',
        name='Google Vertex AI',
        description='Models served through Google Cloud Vertex AI.',
        supports_iam=True,
        icon='Cloud',
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
