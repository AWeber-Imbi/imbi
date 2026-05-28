import http
import logging
import re
import typing

import celpy
import httpx
import jsonpointer
import pydantic
import pydantic_settings
from imbi_common import json_pointer

from imbi_gateway import helpers, version

if typing.TYPE_CHECKING:
    from collections import abc

    from imbi_common.plugins import base as plugin_base


class ActionSettings(pydantic_settings.BaseSettings):
    model_config = {'env_prefix': 'ACTIONS_'}
    imbi_url: pydantic.HttpUrl = pydantic.HttpUrl('http://imbi-api:8000')
    imbi_token: str


LOGGER = logging.getLogger(__name__)

_COMMITTISH_PATTERN = re.compile(r'^[0-9a-f]{7}$')


class UpdateProjectRule(pydantic.BaseModel):
    path: typing.Annotated[
        json_pointer.JsonPointer,
        pydantic.Field(
            description='JSON Pointer on the Imbi project to patch.'
        ),
    ]
    from_: typing.Annotated[
        json_pointer.JsonPointer,
        pydantic.Field(
            alias='from',
            description='JSON Pointer on the webhook payload to read.',
        ),
    ]


class UpdateProjectConfig(pydantic.RootModel[list[UpdateProjectRule]]):
    """``WebhookRule.handler_config`` for :func:`update_project`.

    A list of ``{path, from}`` mappings. Each entry resolves
    ``from`` against the webhook body and patches the value into
    ``path`` on the matched Imbi project.
    """

    root: list[UpdateProjectRule] = pydantic.Field(
        default_factory=list,
        description='Ordered list of source/target JSON Pointer mappings.',
    )


class ImbiClient(httpx.AsyncClient):
    def __init__(self) -> None:
        settings = helpers.settings_from_environment(ActionSettings)
        super().__init__(
            base_url=str(settings.imbi_url),
            headers={
                'authorization': f'Bearer {settings.imbi_token}',
                'user-agent': f'imbi-gateway/{version}',
            },
        )

    async def patch_project(
        self,
        org_slug: str,
        project_id: str,
        patch: abc.Iterable[abc.Mapping[str, object]],
    ) -> httpx.Response:
        url = f'/organizations/{org_slug}/projects/{project_id}'
        LOGGER.debug('Patching project %s', url)
        response = await self.patch(url, json=patch)
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.content
            LOGGER.warning('Failed to patch project %r: %r', url, detail)
        return response

    async def find_user_by_identity(
        self, plugin_slug: str, subject: str
    ) -> str | None:
        """Look up an Imbi user by external identity subject.

        Returns the user's email (the principal identity used by the
        Release ``created_by`` field) or ``None`` when no active
        ``IdentityConnection`` matches.
        """
        response = await self.get(
            '/users/by-identity',
            params={'plugin_slug': plugin_slug, 'subject': subject},
        )
        if response.status_code == http.HTTPStatus.NOT_FOUND:
            return None
        if response.is_error:
            LOGGER.warning(
                'Failed to look up user for plugin=%r subject=%r: %s',
                plugin_slug,
                subject,
                response.text,
            )
            return None
        data = response.json()
        email = data.get('email')
        return str(email) if email else None

    async def create_release(
        self, org_slug: str, project_id: str, body: abc.Mapping[str, object]
    ) -> httpx.Response:
        url = f'/organizations/{org_slug}/projects/{project_id}/releases/'
        LOGGER.debug('Creating release %s', url)
        response = await self.post(url, json=body)
        if response.is_error and (
            response.status_code != http.HTTPStatus.CONFLICT
        ):
            LOGGER.warning(
                'Failed to create release %r: %s', url, response.text
            )
        return response

    async def record_deployment(
        self,
        org_slug: str,
        project_id: str,
        release_id: str,
        env_slug: str,
        body: abc.Mapping[str, object],
    ) -> httpx.Response:
        url = (
            f'/organizations/{org_slug}/projects/{project_id}'
            f'/releases/{release_id}/environments/{env_slug}'
        )
        LOGGER.debug('Recording deployment %s', url)
        response = await self.post(url, json=body)
        if response.is_error and (
            response.status_code != http.HTTPStatus.NOT_FOUND
        ):
            LOGGER.warning(
                'Failed to record deployment %r: %s', url, response.text
            )
        return response

    async def list_releases(
        self,
        org_slug: str,
        project_id: str,
        *,
        committish: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, object]]:
        """List releases for a project, optionally filtered.

        Returns the raw JSON list of releases (each a dict) so callers
        can pick the ``id`` they need without coupling to the full
        response shape.
        """
        url = f'/organizations/{org_slug}/projects/{project_id}/releases/'
        params: dict[str, str] = {}
        if committish is not None:
            params['committish'] = committish
        if tag is not None:
            params['tag'] = tag
        response = await self.get(url, params=params)
        if response.is_error:
            LOGGER.warning(
                'Failed to list releases %r: %s', url, response.text
            )
            return []
        return typing.cast('list[dict[str, object]]', response.json())

    async def put_sbom(
        self,
        org_slug: str,
        project_id: str,
        release_id: str,
        sbom: 'abc.Mapping[str, object]',
    ) -> httpx.Response:
        """Submit a CycloneDX 1.7 SBoM for a release.

        ``sbom`` is the verbatim CycloneDX document — the gateway does
        not own normalization; the Imbi API parses and stores. Non-2xx
        responses are logged and returned verbatim so the caller can
        decide whether to retry, surface the error, or drop the event.
        """
        url = (
            f'/organizations/{org_slug}/projects/{project_id}'
            f'/releases/{release_id}/sbom'
        )
        LOGGER.debug('Putting SBoM %s', url)
        response = await self.put(url, json=sbom)
        if response.is_error:
            LOGGER.warning('Failed to put SBoM %r: %s', url, response.text)
        return response


class CreateReleaseConfig(pydantic.BaseModel):
    """Validates ``handler_config`` for :func:`create_release`.

    ``committish_expression`` is required because the Imbi API
    ``ReleaseCreate`` model requires the short SHA. ``tag`` (and thus
    ``version_expression``) is optional; when absent or evaluated to
    null, the release is still created and identified by its
    committish.
    """

    title_selector: json_pointer.JsonPointer
    committish_expression: str
    version_expression: str | None = None


class AddDeploymentEventConfig(pydantic.BaseModel):
    """Validates ``handler_config`` for :func:`add_deployment_event`.

    ``committish_expression`` is required and is the load-bearing
    lookup key for the release the event attaches to.
    ``version_expression`` is optional; when present it narrows the
    lookup so that a single committish that ships under multiple tags
    is disambiguated.
    """

    environment_selector: json_pointer.JsonPointer
    committish_expression: str
    status_selector: json_pointer.JsonPointer
    version_expression: str | None = None
    note_selector: json_pointer.JsonPointer | None = None
    external_run_id_selector: json_pointer.JsonPointer | None = None


class IngestSbomConfig(pydantic.BaseModel):
    """Validates ``handler_config`` for :func:`ingest_sbom`.

    ``version_expression`` is a CEL expression that resolves the
    release-identity string the SBoM applies to (typically the
    project's tag, or a SHA-derived alias for branch builds — e.g.
    ``ref_name == "main" ? substring(sha, 0, 7) : ref_name``). It is
    an expression rather than a JSON pointer because the producer
    typically emits raw ``github.ref_name`` / ``github.sha`` style
    fields and the choice of which to use as the release identity
    is workflow-conditional. Symmetric with
    :class:`CreateReleaseConfig` and
    :class:`AddDeploymentEventConfig`.

    ``sbom_selector`` points at the CycloneDX document itself;
    defaults to the top of the payload so a build job that posts
    the SBoM verbatim without an envelope still works.

    ``committish_expression`` opts the handler into auto-creating
    the release on the first SBoM. When set, the resolved value is
    lowercased and truncated to the first 7 hex characters before
    being sent to the API. Producers commonly post a full
    ``github.sha`` and let the CEL pass it through unchanged
    (``"sha"`` is a valid expression). When unset, missing releases
    are logged and skipped.

    ``title_selector`` is an optional JSON pointer at the release
    title used when auto-creating; defaults to ``"Release <version>"``
    when omitted or the pointer does not resolve. Stays a pointer
    (not an expression) for symmetry with :class:`CreateReleaseConfig`,
    where the title is always a static field on the payload.
    """

    version_expression: str
    sbom_selector: json_pointer.JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer(''),
        description=(
            'JSON Pointer at the CycloneDX document inside the webhook '
            'payload. Defaults to "" (the entire payload).'
        ),
    )
    committish_expression: str | None = pydantic.Field(
        default=None,
        description=(
            'CEL expression resolving to the short commit SHA used '
            'to auto-create a release when none matches the resolved '
            'version. The resolved value is lowercased and truncated '
            'to the first 7 hex characters before being sent to the '
            'API. When omitted, missing releases are logged and '
            'skipped.'
        ),
    )
    title_selector: json_pointer.JsonPointer | None = pydantic.Field(
        default=None,
        description=(
            'Optional JSON Pointer at the release title used when '
            'auto-creating. Defaults to "Release <version>" when '
            'omitted or the pointer does not resolve.'
        ),
    )


# Raw deployment-status state -> Imbi _DEPLOYMENT_STATUS literal.
# The selector decides where the state is read from; this map is the
# static translation from GitHub-style vocabulary to Imbi's enum.
# Unknown states are logged and skipped (no event recorded).
_STATUS_MAP: dict[str, str] = {
    'queued': 'pending',
    'pending': 'pending',
    'in_progress': 'in_progress',
    'success': 'success',
    'failure': 'failed',
    'error': 'failed',
    'inactive': 'rolled_back',
}


def _cel_substring(
    string: celpy.celtypes.StringType,
    start: celpy.celtypes.IntType,
    end: celpy.celtypes.IntType | None = None,
) -> celpy.celtypes.StringType:
    if end is None:
        return celpy.celtypes.StringType(string[int(start) :])
    return celpy.celtypes.StringType(string[int(start) : int(end)])


_CEL_FUNCTIONS: dict[str, celpy.CELFunction] = {'substring': _cel_substring}


def _evaluate_cel(expression: str, body: object) -> str | None:
    env = celpy.Environment()
    program = env.program(env.compile(expression), functions=_CEL_FUNCTIONS)
    result = program.evaluate(celpy.json_to_cel(body))
    if result is None:
        return None
    return str(result)


async def update_project(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: UpdateProjectConfig,
    payload: object,
) -> None:
    """Patch the matched Imbi project with values pulled from the payload.

    Patch attribution is the gateway's service token, so
    ``ctx.actor_user_id`` and ``credentials`` are unused here.
    ``action_config`` arrives pre-validated as
    :class:`UpdateProjectConfig`.
    """
    del credentials, external_identifier
    LOGGER.info('Updating project /%s/%s', ctx.org_slug, ctx.project_id)
    LOGGER.info('%r', action_config.root)
    patch = [
        {
            'op': 'add',
            'path': str(update.path),
            'value': update.from_.resolve(payload),
        }
        for update in action_config.root
    ]
    async with ImbiClient() as client:
        await client.patch_project(ctx.org_slug, ctx.project_id, patch)


async def create_release(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: CreateReleaseConfig,
    payload: object,
) -> None:
    """Processes a deployment notification and ensures the release exists.

    The committish is the result of evaluating the CEL
    ``committish_expression`` (typically ``substring(deployment.sha,
    0, 7)``) and is required; when it evaluates to null the action is
    skipped because the Imbi API requires the short SHA. The tag is the
    result of evaluating the CEL ``version_expression`` (optional);
    when omitted or evaluated to null the tag is left off the release.
    The title is taken from the JSONPointer ``title_selector``.
    ``ctx.actor_user_id`` (the resolved Imbi user's email) is passed
    as ``created_by`` when present; otherwise the API defaults to the
    gateway's service principal. ``action_config`` arrives pre-validated.
    """
    del credentials, external_identifier
    committish_value = _evaluate_cel(
        action_config.committish_expression, payload
    )
    if committish_value is None:
        LOGGER.warning(
            'Skipping release for project %s: committish expression'
            ' evaluated to null',
            ctx.project_id,
        )
        return
    create_body: dict[str, object] = {
        'committish': committish_value,
        'title': str(action_config.title_selector.resolve(payload)),
    }
    version_value: str | None = None
    if action_config.version_expression is not None:
        version_value = _evaluate_cel(
            action_config.version_expression, payload
        )
        if version_value is not None:
            create_body['tag'] = version_value
    if ctx.actor_user_id is not None:
        create_body['created_by'] = ctx.actor_user_id
    async with ImbiClient() as client:
        response = await client.create_release(
            ctx.org_slug, ctx.project_id, create_body
        )
    if response.status_code == http.HTTPStatus.CONFLICT:
        LOGGER.debug(
            'Release %r already exists for project %s',
            version_value or committish_value,
            ctx.project_id,
        )


async def add_deployment_event(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: AddDeploymentEventConfig,
    payload: object,
) -> None:
    """Processes a deployment_status notification.

    Appends a deployment event to the release's DEPLOYED_TO edge for
    the matching environment. The release is located via the Imbi API's
    ``list_releases`` endpoint filtered by ``committish`` (required) and
    optionally ``tag``; the first matching release's nano-id is used to
    target the deployment endpoint. ``record_deployment`` has no
    ``created_by`` field so ``ctx.actor_user_id`` is unused here.
    """
    del credentials, external_identifier
    raw_state = str(action_config.status_selector.resolve(payload))
    status = _STATUS_MAP.get(raw_state)
    if status is None:
        LOGGER.warning('Unmapped deployment status %r — skipping', raw_state)
        return
    committish_value = _evaluate_cel(
        action_config.committish_expression, payload
    )
    if committish_value is None:
        LOGGER.warning(
            'Skipping deployment event for project %s: committish'
            ' expression evaluated to null',
            ctx.project_id,
        )
        return
    tag_value: str | None = None
    if action_config.version_expression is not None:
        tag_value = _evaluate_cel(action_config.version_expression, payload)
    environment = str(action_config.environment_selector.resolve(payload))
    event_body: dict[str, object] = {'status': status}
    if action_config.note_selector is not None:
        event_body['note'] = str(action_config.note_selector.resolve(payload))
    if action_config.external_run_id_selector is not None:
        event_body['external_run_id'] = str(
            action_config.external_run_id_selector.resolve(payload)
        )
    async with ImbiClient() as client:
        releases = await client.list_releases(
            ctx.org_slug,
            ctx.project_id,
            committish=committish_value,
            tag=tag_value,
        )
        if not releases:
            LOGGER.warning(
                'No release matches committish=%r tag=%r for project %s;'
                ' status %r dropped',
                committish_value,
                tag_value,
                ctx.project_id,
                status,
            )
            return
        release_id = str(releases[0]['id'])
        response = await client.record_deployment(
            ctx.org_slug, ctx.project_id, release_id, environment, event_body
        )
    if response.status_code == http.HTTPStatus.NOT_FOUND:
        LOGGER.warning(
            'Release %r missing for project %s; status %r dropped',
            release_id,
            ctx.project_id,
            status,
        )


async def ingest_sbom(
    *,
    ctx: 'plugin_base.PluginContext',
    credentials: dict[str, str],
    external_identifier: str,
    action_config: IngestSbomConfig,
    payload: object,
) -> None:
    """Forward a CycloneDX 1.7 SBoM to the Imbi API for the matched release.

    Resolves the release-identity string from the payload via
    ``version_expression`` (CEL — typically conditional on
    ``ref_name``/``sha``) and looks the release up by tag. The Imbi
    API is the source of truth for release identity. When no
    release matches *and* ``committish_expression`` is configured,
    the release is auto-created from the resolved committish + tag
    (+ optional title) before the SBoM is PUT. When
    ``committish_expression`` is unset, missing releases drop the
    SBoM with a warning, mirroring :func:`add_deployment_event`'s
    404 handling.
    """
    del credentials, external_identifier
    try:
        tag_value = _evaluate_cel(action_config.version_expression, payload)
    except celpy.CELEvalError as exc:
        LOGGER.warning(
            'version_expression %r raised %s for project %s; SBoM dropped',
            action_config.version_expression,
            exc,
            ctx.project_id,
        )
        return
    if tag_value is None:
        LOGGER.warning(
            'version_expression %r evaluated to null for project %s;'
            ' SBoM dropped',
            action_config.version_expression,
            ctx.project_id,
        )
        return
    try:
        sbom_document = action_config.sbom_selector.resolve(payload)
    except jsonpointer.JsonPointerException:
        LOGGER.warning(
            'SBoM selector %r did not resolve for project %s; SBoM dropped',
            str(action_config.sbom_selector),
            ctx.project_id,
        )
        return
    if not isinstance(sbom_document, dict):
        LOGGER.warning(
            'SBoM at %r is not a JSON object — skipping ingest for project %s',
            str(action_config.sbom_selector),
            ctx.project_id,
        )
        return
    async with ImbiClient() as client:
        release_id = await _resolve_release_for_sbom(
            client, ctx, action_config, payload, tag_value
        )
        if release_id is None:
            return
        await client.put_sbom(
            ctx.org_slug,
            ctx.project_id,
            release_id,
            typing.cast('abc.Mapping[str, object]', sbom_document),
        )


async def _resolve_release_for_sbom(
    client: ImbiClient,
    ctx: 'plugin_base.PluginContext',
    action_config: IngestSbomConfig,
    payload: object,
    tag_value: str,
) -> str | None:
    """Return the release id for the SBoM, creating one if configured.

    Returns ``None`` (and logs) when neither a lookup nor a create
    can produce a release id — callers must treat that as a drop.
    """
    releases = await client.list_releases(
        ctx.org_slug, ctx.project_id, tag=tag_value
    )
    if releases:
        return str(releases[0]['id'])

    create_body = _build_release_create_body(
        action_config, payload, ctx, tag_value
    )
    if create_body is None:
        return None
    return await _create_release_for_sbom(client, ctx, tag_value, create_body)


def _build_release_create_body(
    action_config: IngestSbomConfig,
    payload: object,
    ctx: 'plugin_base.PluginContext',
    tag_value: str,
) -> dict[str, object] | None:
    """Assemble the ``Release`` create body, or ``None`` to drop.

    ``None`` is returned (and a warning logged) when
    ``committish_expression`` is unset or evaluates to null —
    those are the two cases where auto-create is not viable.
    """
    if action_config.committish_expression is None:
        LOGGER.warning(
            'No release matches tag=%r for project %s and no '
            'committish_expression configured; SBoM dropped',
            tag_value,
            ctx.project_id,
        )
        return None

    committish = _resolve_committish(
        action_config.committish_expression, payload
    )
    if committish is None:
        LOGGER.warning(
            'committish_expression %r did not resolve for project %s;'
            ' SBoM dropped',
            action_config.committish_expression,
            ctx.project_id,
        )
        return None

    title = _resolve_title(action_config.title_selector, payload, tag_value)
    body: dict[str, object] = {
        'committish': committish,
        'title': title,
        'tag': tag_value,
    }
    if ctx.actor_user_id is not None:
        body['created_by'] = ctx.actor_user_id
    return body


async def _create_release_for_sbom(
    client: ImbiClient,
    ctx: 'plugin_base.PluginContext',
    tag_value: str,
    create_body: dict[str, object],
) -> str | None:
    """POST a new ``Release`` and return its id, handling 409 races."""
    response = await client.create_release(
        ctx.org_slug, ctx.project_id, create_body
    )

    if response.status_code == http.HTTPStatus.CONFLICT:
        # Another worker (or a stale list_releases cache) won the
        # race. The release exists now, so re-fetch by tag and take
        # whatever id the API gives us.
        races = await client.list_releases(
            ctx.org_slug, ctx.project_id, tag=tag_value
        )
        if races:
            return str(races[0]['id'])
        LOGGER.warning(
            'create_release returned 409 for project %s tag=%r but the '
            'subsequent list returned empty; SBoM dropped',
            ctx.project_id,
            tag_value,
        )
        return None

    if response.is_error:
        return None
    return str(response.json()['id'])


def _resolve_committish(expression: str, payload: object) -> str | None:
    """Evaluate the committish CEL expression, normalize, validate.

    Trims to the first 7 lowercase hex chars to match the API's
    ``Release.committish`` regex (``^[0-9a-f]{7}$``). Returns
    ``None`` when the expression evaluates to null, raises a
    ``CELEvalError`` (e.g. a referenced field is missing from the
    payload), or yields an empty string. The auto-create branch
    is intentionally forgiving — a config-vs-payload mismatch on
    the optional ``committish_expression`` drops the SBoM with a
    warning rather than 500ing the webhook.

    The expression is typically the bare field reference ``"sha"``
    (producers post the full ``github.sha`` and let the 7-char
    truncation here handle the API contract), but it can be
    conditional CEL just like ``version_expression``.
    """
    try:
        resolved = _evaluate_cel(expression, payload)
    except celpy.CELEvalError:
        return None
    if resolved is None:
        return None
    committish = resolved.strip().lower()[:7]
    if not _COMMITTISH_PATTERN.match(committish):
        return None
    return committish


def _resolve_title(
    selector: json_pointer.JsonPointer | None, payload: object, tag_value: str
) -> str:
    """Resolve the optional title selector with a sensible default."""
    if selector is not None:
        try:
            resolved = selector.resolve(payload)
        except jsonpointer.JsonPointerException:
            resolved = None
        if resolved is not None:
            return str(resolved)
    return f'Release {tag_value}'
