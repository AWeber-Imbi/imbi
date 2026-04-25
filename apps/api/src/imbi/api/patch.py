"""JSON Patch (RFC 6902) utilities."""

import typing

import fastapi
import jsonpatch  # type: ignore[import-untyped]
import pydantic

LOGGER = __import__('logging').getLogger(__name__)

READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/created_at',
        '/updated_at',
        '/relationships',
        '/id',
    ]
)


class PatchOperation(pydantic.BaseModel):
    """A single JSON Patch operation (RFC 6902).

    Attributes:
        op: The operation type.
        path: JSON Pointer (RFC 6901) target path.
        value: New value for add/replace/test operations.
        from_: Source path for move/copy operations.

    """

    model_config = pydantic.ConfigDict(populate_by_name=True)

    op: typing.Literal['add', 'remove', 'replace', 'move', 'copy', 'test']
    path: str
    value: typing.Any = None
    from_: str | None = pydantic.Field(None, alias='from')


def apply_patch(
    document: dict[str, typing.Any],
    operations: list[PatchOperation],
    readonly_paths: frozenset[str] = READONLY_PATHS,
) -> dict[str, typing.Any]:
    """Apply a JSON Patch document to a dict.

    Parameters:
        document: Current resource state as JSON-serializable dict.
        operations: Validated patch operations.
        readonly_paths: Paths that cannot be modified. Defaults to
            ``READONLY_PATHS`` (created_at, updated_at, relationships, id).

    Returns:
        A new dict with the patch applied.

    Raises:
        HTTPException 400: Path is read-only or operation is invalid.
        HTTPException 422: A ``test`` operation failed.

    """
    for op in operations:
        for check_path in [op.path, op.from_]:
            if check_path is None:
                continue
            if check_path == '':
                raise fastapi.HTTPException(
                    status_code=400,
                    detail='Root path cannot be patched',
                )
            if any(
                check_path == ro or check_path.startswith(f'{ro}/')
                for ro in readonly_paths
            ):
                raise fastapi.HTTPException(
                    status_code=400,
                    detail=(
                        f'Path {check_path!r} is read-only'
                        ' and cannot be patched'
                    ),
                )

    ops_list: list[dict[str, typing.Any]] = []
    for op in operations:
        d: dict[str, typing.Any] = {'op': op.op, 'path': op.path}
        if 'value' in op.model_fields_set:
            d['value'] = op.value
        if op.from_ is not None:
            d['from'] = op.from_
        ops_list.append(d)

    try:
        result = jsonpatch.apply_patch(  # type: ignore[no-any-expr]
            document,
            ops_list,
        )
    except jsonpatch.JsonPatchTestFailed as e:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'Patch test operation failed: {e}',
        ) from e
    except (jsonpatch.JsonPatchConflict, jsonpatch.InvalidJsonPatch) as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid patch: {e}',
        ) from e

    if not isinstance(result, dict):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Patch result must be a JSON object',
        )
    return typing.cast(dict[str, typing.Any], result)
