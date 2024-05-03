from __future__ import annotations

import logging
import typing

import pydantic
import sprockets.mixins.http
import yarl

from imbi import errors, models, version
if typing.TYPE_CHECKING:
    from imbi import app


class _ProjectCreationResponse(pydantic.BaseModel):
    name: str
    slug: str
    id: str


class _ProjectKeysDsn(pydantic.BaseModel):
    public: pydantic.HttpUrl
    secret: pydantic.HttpUrl


class _ProjectKeysResponse(pydantic.BaseModel):
    dsn: _ProjectKeysDsn
    id: str
    isActive: bool
    projectId: int


class ProjectInfo(pydantic.BaseModel):
    name: str
    slug: str
    id: str
    link: pydantic.HttpUrl
    keys: dict[str, str]


async def create_client(
    application: app.Application,
    integration_name: str,
) -> '_SentryClient':
    """Create a sentry API client

    The settings needed to create a client are in the application
    settings and the database currently. This function finds them
    and creates a client.  If the configuration is invalid or the
    integration is disabled, a ``ClientUnavailableError`` is raised
    with an appropriate message.
    """
    logger = logging.getLogger(__package__).getChild('create_client')
    settings = application.settings['automations']['sentry']
    if not settings['enabled']:
        raise errors.ClientUnavailableError(integration_name, 'disabled')
    if not settings.get('organization'):
        raise errors.ClientUnavailableError(integration_name,
                                            'organization is not configured')

    sentry_info = await models.integration(integration_name, application)
    if not sentry_info:
        logger.warning('%r integration is enabled by not configured',
                       integration_name)
        raise errors.ClientUnavailableError(integration_name, 'not configured')

    return _SentryClient(yarl.URL(str(sentry_info.api_endpoint)),
                         sentry_info.api_secret, settings['organization'])


class _SentryClient(sprockets.mixins.http.HTTPClientMixin):
    def __init__(self, api_endpoint: yarl.URL, api_secret: str,
                 organization: str) -> None:
        super().__init__()
        self.logger = logging.getLogger(__package__).getChild('SentryClient')

        self.api_url = api_endpoint
        self.url = api_endpoint.with_path('/')
        self.organization = organization
        self.api_secret = api_secret
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.api_secret}',
        }

    async def api(self, url: yarl.URL | str, *, method: str = 'GET', **kwargs):
        if not isinstance(url, yarl.URL):
            url = yarl.URL(url)
        if not url.is_absolute():
            url = self.api_url / url.path.lstrip('/')

        # the sentry API wants a trailing slash
        url = str(url).rstrip('/') + '/'

        request_headers = kwargs.pop('request_headers', {})
        request_headers.update(self.headers)
        if kwargs.get('body') is not None:
            request_headers['Content-Type'] = 'application/json'
            kwargs['content_type'] = 'application/json'
        kwargs['request_headers'] = request_headers
        kwargs['user_agent'] = f'imbi/{version} (SentryClient)'
        rsp = await super().http_fetch(str(url), method=method, **kwargs)
        if not rsp.ok:
            self.logger.error('%s %s failed: %s', method, url, rsp.code)
            self.logger.debug('auth token: %s...%s', self.api_secret[:4],
                              self.api_secret[-4:])
            self.logger.debug('response body: %r', rsp.body)
        return rsp

    async def create_project(self, team_slug: str,
                             project_name: str) -> ProjectInfo:
        url = yarl.URL('/teams') / self.organization / team_slug / 'projects'
        response = await self.api(url,
                                  method='POST',
                                  body={'name': project_name})
        if not response.ok:
            self.logger.error('Sentry API failure: body %r', response.body)
            raise errors.InternalServerError(
                'POST %s failed: %s',
                response.history[-1].effective_url,
                response.code,
                title='Sentry API Failure')
        else:
            try:
                data = _ProjectCreationResponse.parse_obj(response.body)
            except pydantic.ValidationError as error:
                self.logger.error('failed to parse response body: %r',
                                  response.body)
                raise errors.InternalServerError(
                    'Failed to parse sentry create_project response: %s',
                    error,
                    title='Sentry Client Failure')

        project = ProjectInfo(
            id=data.id,
            name=data.name,
            slug=data.slug,
            link=str(self.url / 'organizations' / self.organization /
                     'projects' / data.slug),
            keys={})

        # TODO update the project platform based on the project details
        #      so that python projects use "platform=python" and
        #      JS projects use "platform=javascript"
        # Not sure if this is actually necessary so I'm omitting it.
        # https://github.com/AWeber-Imbi/imbi/issues/73
        # ref: https://docs.sentry.io/api/projects/update-a-project/
        # ref: https://docs.sentry.io/platforms/

        url = yarl.URL('/projects') / self.organization / project.slug

        try:
            response = await self.api(url / 'keys')
            if not response.ok:
                raise errors.InternalServerError(
                    'Failed to retrieve sentry project keys: %s',
                    response.code,
                    title='Sentry API Error')
            try:
                data = _ProjectKeysResponse.parse_obj(response.body[0])
            except pydantic.ValidationError as error:
                self.logger.error('failed to parse response body: %r',
                                  response.body)
                raise errors.InternalServerError(
                    'Failed to parse sentry project keys response: %s',
                    error,
                    title='Sentry Client Failure')
            else:
                project.keys.update({
                    'public': data.dsn.public,
                    'secret': data.dsn.secret,
                })

        # If we fail to fetch or extract the keys that the client
        # needs, then remove the project since we cannot use it.
        except errors.ApplicationError as error:
            self.logger.error('removing Sentry project %s due to error: %s',
                              project.slug, error)
            await self.remove_project(project.slug)
            raise

        return project

    async def remove_project(self, project_slug: str) -> None:
        await self.api(yarl.URL('/projects') / self.organization /
                       project_slug,
                       method='DELETE')
