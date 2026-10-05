"""Seed the prompts Imbi ships into the prompt CMS.

Run by ``imbi-api setup-prompts`` (and by ``imbi-api setup``). A prompt
that already exists is never changed, so a seed run cannot undo edits.
"""

import typing

from imbi.api.endpoints import prompts as prompt_endpoints
from imbi.common import graph
from imbi.common.prompts import resolve, system

#: Recorded as the author of each seeded version and label.
SEED_AUTHOR = 'imbi-setup'


class SeedResult(typing.NamedTuple):
    ref: str
    created: bool


async def seed_default_prompts(db: graph.Graph) -> list[SeedResult]:
    """Create each default prompt that does not exist yet.

    Each one gets version 1 from the packaged template and a ``stable``
    label. No model is set, so a consumer keeps its configured model
    until an admin picks one.
    """
    results: list[SeedResult] = []
    for default in system.DEFAULT_PROMPTS:
        try:
            await resolve.fetch_prompt(db, default.namespace, default.slug)
        except resolve.PromptNotFound:
            pass
        else:
            results.append(SeedResult(default.ref, created=False))
            continue
        await prompt_endpoints.insert_prompt(
            db,
            prompt_endpoints.PromptCreate(
                namespace=default.namespace,
                slug=default.slug,
                name=default.name,
                description=default.description,
                type=default.type,
                version=prompt_endpoints.PromptVersionCreate(
                    system=default.text(),
                    variable_schema=default.variable_schema(),
                    summary='Packaged default',
                ),
            ),
            SEED_AUTHOR,
            # An operator action, run with system authority.
            label_first_version=True,
        )
        results.append(SeedResult(default.ref, created=True))
    return results
