from __future__ import annotations

import re
import typing

import pydantic

Slug = typing.Annotated[str,
                        pydantic.StringConstraints(
                            pattern=r'^[a-z0-9][-_a-z0-9]*[a-z0-9]?$',
                            min_length=1,
                        )]


def path_element(value: str) -> str:
    """Generate a slug for an arbitrary string"""
    value = re.sub(r'[\s_]+', '-', value)
    value = re.sub(r'[^-a-z0-9]', '', value.lower())
    return Slug(value.strip('-_'))


def decode_path_slug(slug_or_id: str) -> tuple[int | None, str | None]:
    """Decode a path parameter as either an integer or a slug

    :returns: a tuple of (int, str) where only one of the values
        is not `None`

    """
    id_value: int | None = None
    slug_value: str | None = slug_or_id
    try:
        id_value = int(slug_or_id, 10)
        slug_value = None
    except ValueError:
        pass
    return id_value, slug_value
