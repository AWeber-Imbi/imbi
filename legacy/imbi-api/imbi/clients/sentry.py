from __future__ import annotations

import logging

import pydantic
import sprockets.mixins.http
import yarl

from imbi import errors, version


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


class SentryClient(sprockets.mixins.http.HTTPClientMixin):
    def __init__(self, application) -> None:
        super().__init__()
        self.logger = logging.getLogger(__package__).getChild('SentryClient')

        settings = application.settings['automations']['sentry']
        self.url = yarl.URL(settings['url'])
        self.api_url = self.url / 'api' / '0'
        self.enabled = settings['enabled']
        self.organization = settings.get('organization')
        self.token = settings.get('auth_token')
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.token}',
        }

    async def api(self, url: yarl.URL | str, *,
                  method: str = 'GET', **kwargs):
        if not self.enabled:
            raise errors.InternalServerError('Sentry client is not enabled',
                                             title='Sentry Client Error')

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
        return rsp

    async def create_project(self, team_slug: str,
                             project_name: str) -> ProjectInfo:
        url = yarl.URL('/teams') / self.organization / team_slug / 'projects'
        response = await self.api(url, method='POST',
                                  body={'name': project_name})
        if not response.ok:
            self.logger.error('Sentry API failure: body %r', response.body)
            raise errors.InternalServerError(
                'POST %s failed: %s', url, response.code,
                title='Sentry API Failure')
        else:
            try:
                data = _ProjectCreationResponse.parse_obj(response.body)
            except pydantic.ValidationError as error:
                self.logger.error('failed to parse response body: %r',
                                  response.body)
                raise errors.InternalServerError(
                    'Failed to parse sentry create_project response: %s',
                    error, title='Sentry Client Failure')

        project = ProjectInfo(
            id=data.id,
            name=data.name,
            slug=data.slug,
            link=str(self.url / 'organizations' / self.organization /
                     'projects' / data.slug),
            keys={}
        )

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
                    response.code, title='Sentry API Error')
            try:
                data = _ProjectKeysResponse.parse_obj(response.body[0])
            except pydantic.ValidationError as error:
                self.logger.error('failed to parse response body: %r',
                                  response.body)
                raise errors.InternalServerError(
                    'Failed to parse sentry project keys response: %s',
                    error, title='Sentry Client Failure')
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
        await self.api(
            yarl.URL('/projects') / self.organization / project_slug,
            method='DELETE')
