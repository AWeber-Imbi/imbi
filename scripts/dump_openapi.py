"""Write the imbi-api OpenAPI document to stdout.

Used by ``scripts/regen-api-types.sh`` to regenerate
``ui/src/types/api-generated.ts``. No database is needed: the blueprint
models are built from a graph that holds no blueprints, which is what a
new installation (and the test services) gives. So the output depends
only on the code, and CI can compare it with the checked-in file.
"""

import asyncio
import json
import os
import sys
import typing

from imbi.api import app, openapi


class _NoBlueprints:
    """The one graph call ``refresh_blueprint_models`` makes."""

    async def match(self, *_args: object, **_kwargs: object) -> list[object]:
        return []


def main() -> None:
    # The routes get the /api prefix only when IMBI_API_URL has it.
    os.environ['IMBI_API_URL'] = 'http://localhost:8000/api'
    asyncio.run(
        openapi.refresh_blueprint_models(
            typing.cast('typing.Any', _NoBlueprints())
        )
    )
    json.dump(app.create_app().openapi(), sys.stdout, indent=2)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
