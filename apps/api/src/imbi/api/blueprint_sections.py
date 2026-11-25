"""The blueprint schema sections that the UI renders as fields.

A section is one blueprint's properties, with the JSON Schema keywords
and the ``x-ui`` metadata that the UI needs. Projects and tickets use
them.
"""

import typing

import pydantic

from imbi.common import models


class BlueprintSectionItems(pydantic.BaseModel):
    """The ``items`` schema of an array property."""

    model_config = pydantic.ConfigDict(
        populate_by_name=True, serialize_by_alias=True
    )

    type: str | None = None
    format: str | None = None
    enum: list[typing.Any] | None = None
    pattern: str | None = None
    min_length: int | None = pydantic.Field(default=None, alias='minLength')
    max_length: int | None = pydantic.Field(default=None, alias='maxLength')
    multiple_of: float | None = pydantic.Field(
        default=None, alias='multipleOf'
    )


class BlueprintSectionProperty(pydantic.BaseModel):
    """A single property from a blueprint's JSON Schema."""

    model_config = pydantic.ConfigDict(
        populate_by_name=True, serialize_by_alias=True
    )

    type: str | None = None
    format: str | None = None
    title: str | None = None
    description: str | None = None
    enum: list[str] | None = None
    default: typing.Any = None
    minimum: float | None = None
    maximum: float | None = None
    multiple_of: float | None = pydantic.Field(
        default=None, alias='multipleOf'
    )
    pattern: str | None = None
    min_length: int | None = pydantic.Field(default=None, alias='minLength')
    max_length: int | None = pydantic.Field(default=None, alias='maxLength')
    items: BlueprintSectionItems | None = None
    x_ui: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        alias='x-ui',
        serialization_alias='x-ui',
    )
    #: Optional value-display transforms (e.g. ``{'format': 'humanize'}``)
    #: applied to the rendered value, independent of ``x-ui`` color/icon
    #: resolution (which keys off the raw value).
    x_display: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        alias='x-display',
        serialization_alias='x-display',
    )


class BlueprintSection(pydantic.BaseModel):
    """One blueprint's contribution to the project schema."""

    name: str
    slug: str
    description: str | None = None
    #: ``project`` for node blueprints (project-level attributes);
    #: ``environment`` for relationship blueprints on the
    #: ``Project -[:DEPLOYED_IN]-> Environment`` edge (per-environment
    #: edge attributes rendered in the Environments card); ``ticket``
    #: for ``Ticket`` blueprints (custom fields).
    scope: typing.Literal['project', 'environment', 'ticket'] = 'project'
    properties: dict[str, BlueprintSectionProperty]
    #: Property names the blueprint marks as required.
    required: list[str] = []


def section_property(prop_schema: models.Schema) -> BlueprintSectionProperty:
    """Return the section property of one blueprint property schema."""
    extra = prop_schema.model_extra or {}
    x_ui = dict(extra.get('x-ui') or {})
    if x_ui.get('editable') is None:
        x_ui['editable'] = True
    raw_x_display = extra.get('x-display')
    items = getattr(prop_schema, 'items', None)
    # By alias: the type checker knows only the alias of a field.
    aliased: dict[str, typing.Any] = {
        'multipleOf': getattr(prop_schema, 'multiple_of', None),
        'minLength': getattr(prop_schema, 'min_length', None),
        'maxLength': getattr(prop_schema, 'max_length', None),
        'x-ui': x_ui,
        'x-display': dict(raw_x_display or {}),
    }
    return BlueprintSectionProperty(
        type=getattr(prop_schema, 'type', None),
        format=getattr(prop_schema, 'format', None),
        title=getattr(prop_schema, 'title', None),
        description=getattr(prop_schema, 'description', None),
        enum=getattr(prop_schema, 'enum', None),
        default=getattr(prop_schema, 'default', None),
        minimum=getattr(prop_schema, 'minimum', None),
        maximum=getattr(prop_schema, 'maximum', None),
        pattern=getattr(prop_schema, 'pattern', None),
        items=(
            BlueprintSectionItems.model_validate(items, from_attributes=True)
            if isinstance(items, models.Schema)
            else None
        ),
        **aliased,
    )


def build_section(
    bp: models.Blueprint,
    scope: typing.Literal['project', 'environment', 'ticket'],
) -> BlueprintSection | None:
    """Build a schema section from a blueprint, or ``None`` when it
    declares no properties."""
    schema = bp.json_schema
    if not schema.properties:
        return None
    return BlueprintSection(
        name=bp.name,
        slug=bp.slug or '',
        description=bp.description,
        scope=scope,
        properties={
            name: section_property(prop)
            for name, prop in schema.properties.items()
        },
        required=list(schema.required or []),
    )
