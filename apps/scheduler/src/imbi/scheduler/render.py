"""Target rendering.

Paths, bodies, query values, header values, and the idempotency key are Jinja2
templates over ``{now, task, run, last_run}``. That matches the templating
model `imbi-automations` exposes, so an operator learns one syntax for the
platform.

The environment is sandboxed: templates come from task definitions, which are
API-writable by anyone holding `scheduled_task:create`, so they are treated as
untrusted input rather than as code.
"""

import datetime
import functools
import typing
from collections import abc

import jinja2
from jinja2 import sandbox

from imbi.scheduler import models


class RenderError(Exception):
    """A template could not be rendered.

    Distinct from an identity failure: a broken template is the task
    definition's fault, so the run is `failed` and no request is made.
    """


#: Task templates are byte-identical on every firing, so one shared
#: environment plus a compile cache turns rendering into a dictionary lookup.
#: `from_string` never consults Jinja2's own cache, so without this every
#: firing recompiles every template (~143 us each, measured).
_ENVIRONMENT = sandbox.SandboxedEnvironment(
    undefined=jinja2.StrictUndefined, autoescape=False
)

#: Markers that make a string worth compiling at all.
_MARKERS = ('{{', '{%')

_CACHE_SIZE = 512


def environment() -> jinja2.Environment:
    """Return the sandboxed environment used for every render."""
    return _ENVIRONMENT


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _compile(template: str) -> jinja2.Template:
    """Return the compiled form of `template`, cached across firings."""
    return _ENVIRONMENT.from_string(template)


def context(
    task: models.Task,
    now: datetime.datetime,
    run_id: str,
) -> dict[str, typing.Any]:
    """Return the template context for a firing."""
    return {
        'now': now,
        'task': task.model_dump(mode='json'),
        'run': {'id': run_id, 'fired_at': now.isoformat()},
        'last_run': (
            task.last_run_at.isoformat() if task.last_run_at else None
        ),
    }


class Renderer:
    """Renders one task's target for one run."""

    def __init__(self, values: dict[str, typing.Any]) -> None:
        self._values = values

    def text(self, template: str) -> str:
        """Render a single template string.

        A string with no template markers is returned as-is: most paths,
        headers, and payload values are literals, and compiling them would
        dominate the cost of the firing.
        """
        if not any(marker in template for marker in _MARKERS):
            return template
        try:
            return _compile(template).render(self._values)
        except jinja2.TemplateError as err:
            raise RenderError(f'{template!r}: {err}') from err

    def mapping(self, values: dict[str, str]) -> dict[str, str]:
        """Render every value in a string mapping."""
        return {key: self.text(value) for key, value in values.items()}

    def document(self, value: typing.Any) -> typing.Any:
        """Render every string inside a nested JSON document.

        Keys are left alone: a templated key would let a render error change
        the shape of a payload rather than just a value.
        """
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            mapping = typing.cast('dict[str, typing.Any]', value)
            return {key: self.document(item) for key, item in mapping.items()}
        if isinstance(value, list):
            items = typing.cast('abc.Sequence[typing.Any]', value)
            return [self.document(item) for item in items]
        return value


class RenderedRequest(typing.NamedTuple):
    """A target resolved into the pieces of an HTTP request."""

    method: str
    url: str
    query: dict[str, str]
    body: dict[str, typing.Any] | None
    headers: dict[str, str]


def _scoped_to(path: str, organization: str) -> bool:
    """Return whether `path` already addresses `organization`.

    The boundary matters: a bare prefix test lets a task scoped to `acme`
    reach `/organizations/acme-corp/...` unrewritten, which is a request
    against a different organization made with the task's credential.
    """
    prefix = f'/organizations/{organization}'
    return path == prefix or path.startswith(f'{prefix}/')


def api_request(
    task: models.Task,
    target: models.ApiTarget,
    renderer: Renderer,
    base_url: str,
) -> RenderedRequest:
    """Render an `imbi-api` target.

    A bare path resolves under the task's organization when one is set, so a
    task scoped to an organization does not have to repeat it in every path.
    """
    path = renderer.text(target.path)
    organization = target.organization or task.organization
    if organization and not _scoped_to(path, organization):
        path = f'/organizations/{organization}{path}'
    return RenderedRequest(
        method=target.method,
        url=base_url.rstrip('/') + path,
        query=renderer.mapping(target.query),
        body=renderer.document(target.body) if target.body else None,
        headers={},
    )


def gateway_request(
    target: models.GatewayTarget,
    renderer: Renderer,
    base_url: str,
) -> RenderedRequest:
    """Render an `imbi-gateway` webhook delivery."""
    return RenderedRequest(
        method='POST',
        url=(
            base_url.rstrip('/')
            + f'/notifications/{renderer.text(target.webhook_id)}'
        ),
        query={},
        body=renderer.document(target.payload),
        headers=renderer.mapping(target.headers),
    )
