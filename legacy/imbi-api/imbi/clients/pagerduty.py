from __future__ import annotations

import logging
import typing

import pydantic
import sprockets.mixins.http
import yarl

from imbi import errors, models, version
if typing.TYPE_CHECKING:  # pragma: nocover
    from imbi import app


class ServiceInfo(pydantic.BaseModel):
    html_url: pydantic.HttpUrl  # aweber.pagerduty.com/...
    id: str
    self: pydantic.HttpUrl  # api.pagerduty.com/...


class _CreateServiceResponse(pydantic.BaseModel):
    service: ServiceInfo


class IntegrationInfo(pydantic.BaseModel):
    id: str
    name: str
    type: str
    self: pydantic.HttpUrl
    html_url: pydantic.HttpUrl
    integration_key: str


class _CreateIntegrationResponse(pydantic.BaseModel):
    integration: IntegrationInfo


class _PagerDutyClient(sprockets.mixins.http.HTTPClientMixin):
    def __init__(self, info: models.Integration, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__package__).getChild(
            'PagerDutyClient')
        self.api_url = yarl.URL(str(info.api_endpoint))
        self.api_secret = info.api_secret
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Token token={info.api_secret}',
        }

    async def api(self,
                  url: yarl.URL | str,
                  *,
                  method: str = 'GET',
                  **kwargs) -> sprockets.mixins.http.HTTPResponse:
        if not isinstance(url, yarl.URL):
            url = yarl.URL(url)
        url = self.api_url / url.path.removeprefix('/')

        request_headers = kwargs.pop('request_headers', {})
        request_headers.update(self.headers)
        kwargs['request_headers'] = request_headers

        if kwargs.get('body') is not None:
            request_headers['Content-Type'] = 'application/json'
            kwargs['content_type'] = 'application/json'
        kwargs['user_agent'] = f'imbi/{version} (PagerDutyClient)'
        rsp = await self.http_fetch(str(url), method=method, **kwargs)
        if not rsp.ok:
            self.logger.error('%s %s failed: %s', method, url, rsp.code)
            self.logger.debug('pagerduty key: %s...%s', self.api_secret[:4],
                              self.api_secret[-4:])
            self.logger.debug('response body: %r', rsp.body)
        return rsp

    async def create_service(self, project: models.Project) -> ServiceInfo:
        """Create a PagerDuty service for `project`

        The new service is named `project.slug` and assigned to the
        escalation policy from `project.namespace.pagerduty_policy`.
        If the namespaces pagerduty policy is NULL, then an
        ``InternalServiceError`` is raised.
        """
        if project.namespace.pagerduty_policy is None:
            raise errors.InternalServerError(
                'PagerDuty is not enabled for namespace %s',
                project.namespace.slug)
        body = {
            'name': project.slug,
            'escalation_policy': {
                'id': project.namespace.pagerduty_policy,
                'type': 'escalation_policy_reference'
            }
        }
        if project.description:
            body['description'] = project.description
        self.logger.debug('creating PagerDuty service with: %r', body)
        response = await self.api('/services', method='POST', body=body)
        if not response.ok:
            self.logger.error('PagerDuty API failure: body %r', response.body)
            raise errors.InternalServerError(
                'POST %s failed for name=%r policy=%r: %s',
                response.history[-1].effective_url,
                project.slug,
                project.namespace.pagerduty_policy,
                response.code,
                title='PagerDuty API Failure',
                detail=f'Failed to create service {body["name"]!r}')

        try:
            parsed_rsp = _CreateServiceResponse.model_validate(response.body)
        except pydantic.ValidationError as error:
            raise errors.InternalServerError(
                'Failed to parse the PagerDuty response: %s',
                error,
                title='PagerDuty API Failure',
                detail='Failed to parse service creation response') from None
        else:
            return parsed_rsp.service

    async def create_inbound_api_integration(
            self, name: str, service: ServiceInfo) -> IntegrationInfo:
        response = await self.api(
            yarl.URL('/services') / service.id / 'integrations',
            method='POST',
            body={
                'integration': {
                    'name': name,
                    'type': 'generic_events_api_inbound_integration'
                }
            },
        )
        if not response.ok:
            self.logger.error('PagerDuty API failure: body %r', response.body)
            raise errors.InternalServerError(
                'POST %s failed: %s',
                response.history[-1].effective_url,
                response.code,
                title='PagerDuty API Failure',
                detail=f'Failed to create inbound API integration {name}')

        try:
            parsed_rsp = _CreateIntegrationResponse.model_validate(
                response.body)
        except pydantic.ValidationError as error:
            raise errors.InternalServerError(
                'Failed to parse the PagerDuty response: %s',
                error,
                title='PagerDuty API Failure',
                detail='Failed to parse integration creation response'
            ) from None
        else:
            return parsed_rsp.integration

    async def remove_service(self, service_id: str) -> None:
        """Delete `service_id` from PagerDuty"""
        await self.api(yarl.URL('/services') / service_id, method='DELETE')


async def create_client(application: app.Application,
                        integration_name: str) -> _PagerDutyClient:
    """Create a PagerDuty API client

    The settings need to create a client are stored in the database.
    However, you can disable the PagerDuty client by setting the
    `/automations/pagerduty/enabled` property to false in the
    configuration file.

    If the automation is disabled in the configuration file, the
    integration is missing from the database, or the integration
    does not have an API secret set, then a ``ClientUnavailableError``
    is raised with an appropriate diagnostic message.
    """
    logger = logging.getLogger(__package__).getChild('create_client')
    try:
        settings = application.settings['automations']['pagerduty']
        enabled = settings['enabled']
    except KeyError:
        raise errors.ClientUnavailableError(integration_name, 'not configured')
    else:
        if not enabled:
            raise errors.ClientUnavailableError(integration_name, 'disabled')

    pagerduty_info = await models.integration(integration_name, application)
    if not pagerduty_info:
        logger.warning('%r integration is enabled by not configured',
                       integration_name)
        raise errors.ClientUnavailableError(integration_name, 'not configured')
    if not pagerduty_info.api_secret:
        logger.warning('API secret is missing for %r', integration_name)
        raise errors.ClientUnavailableError(integration_name, 'misconfigured')

    return _PagerDutyClient(pagerduty_info)
