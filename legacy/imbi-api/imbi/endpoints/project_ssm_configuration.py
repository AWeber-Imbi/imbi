import collections
import re
import typing
import urllib.parse

import aioboto3
import aioredis
import botocore.exceptions
import sprockets.mixins.http
from tornado import web

from imbi import errors, oauth2, user
from imbi.clients import aws
from imbi.endpoints import base


class CollectionRequestHandler(sprockets.mixins.http.HTTPClientMixin,
                               base.ValidatingRequestHandler):
    GET_PROJECT_INFO_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT n.id AS namespace_id,
               n.aws_ssm_slug AS namespace_slug,
               p.slug AS project_slug,
               t.slug AS project_type_slug,
               p.configuration_type,
               p.environments
          FROM v1.namespaces AS n
          JOIN v1.projects AS p
            ON p.namespace_id = n.id
          JOIN v1.project_types AS t
            ON p.project_type_id = t.id
         WHERE p.id = %(project_id)s""")

    GET_ROLE_ARN_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT role_arn
          FROM v1.aws_roles
         WHERE environment = %(environment)s
           AND namespace_id = %(namespace_id)s""")

    @staticmethod
    def path_prefix(template: str, project_slug: str, project_type_slug: str,
                    namespace_slug: str) -> str:
        return template.replace('{project_slug}', project_slug).replace(
            '{project_type_slug}',
            project_type_slug).replace('{namespace_slug}', namespace_slug)

    @property
    def _redis(self) -> aioredis.Redis:
        return self.application.session_redis

    async def get(self, *args, **kwargs) -> None:
        project_info = await self._get_project_info(kwargs['project_id'])
        if not project_info['environments']:
            self.send_response([])
            return

        google_tokens = await self._get_google_tokens()

        ssm_path_prefix = self.path_prefix(
            self.application.settings['project_configuration']
            ['ssm_prefix_template'], project_info['project_slug'],
            project_info['project_type_slug'], project_info['namespace_slug'])

        role_arn_exists = False
        params_by_path = collections.defaultdict(dict)
        aws_session = aioboto3.Session()
        for environment in project_info['environments']:
            role_arn = await self.get_role_arn(environment,
                                               project_info['namespace_id'])
            if not role_arn:
                continue
            else:
                role_arn_exists = True

            creds = await self.get_aws_credentials(aws_session, role_arn,
                                                   self.current_user,
                                                   google_tokens.id_token,
                                                   google_tokens.refresh_token)
            params = await aws.get_parameters_by_path(
                aws_session, ssm_path_prefix, creds['access_key_id'],
                creds['secret_access_key'], creds['session_token'])
            for param in params:
                params_by_path[param['Name']][environment] = {
                    'value': param['Value'],
                    'type': param['Type']
                }
        if not role_arn_exists:
            self.logger.info(
                'Fetching SSM params for project %s, no role '
                'ARNs found for namespace %d in any '
                'environment: %s', project_info['project_slug'],
                project_info['namespace_id'], project_info['environments'])
            self.send_response([])
            return

        output = [{
            'name': name,
            'values': [{
                'environment': environment,
                'value': data['value'],
                'type': data['type']
            } for environment, data in d.items()]
        } for name, d in params_by_path.items()]
        self.send_response(output)

    async def post(self, *args, **kwargs) -> None:
        project_info = await self._get_project_info(kwargs['project_id'])
        google_tokens = await self._get_google_tokens()
        aws_session = aioboto3.Session()
        body = self.get_request_body()

        project_config = self.application.settings['project_configuration']
        ssm_path_prefix = self.path_prefix(
            project_config['ssm_prefix_template'],
            project_info['project_slug'], project_info['project_type_slug'],
            project_info['namespace_slug'])
        name = ssm_path_prefix + body['name']

        for environment, value in body['values'].items():
            role_arn = await self.get_role_arn(environment,
                                               project_info['namespace_id'])
            if not role_arn:
                raise errors.Forbidden(
                    'No role ARN found for namespace %d in %s',
                    project_info['namespace_id'], environment)

            creds = await self.get_aws_credentials(aws_session, role_arn,
                                                   self.current_user,
                                                   google_tokens.id_token,
                                                   google_tokens.refresh_token)
            try:
                await aws.put_parameter(aws_session, creds['access_key_id'],
                                        creds['secret_access_key'],
                                        creds['session_token'], name,
                                        body['type'], value)
            except botocore.exceptions.ClientError as error:
                code = error.response['Error']['Code']
                if code == 'UnsupportedParameterType':
                    raise errors.BadRequest('UnsupportedParameterType')
                elif code == 'ParameterAlreadyExists':
                    raise errors.BadRequest('ParameterAlreadyExists')
                elif code == 'ParameterLimitExceeded':
                    raise errors.BadRequest('ParameterLimitExceeded')
                else:
                    raise errors.InternalServerError(code)

    async def delete(self, *args, **kwargs):
        project_info = await self._get_project_info(kwargs['project_id'])
        google_tokens = await self._get_google_tokens()
        aws_session = aioboto3.Session()
        body = self.get_request_body()

        project_config = self.application.settings['project_configuration']
        ssm_path_prefix = self.path_prefix(
            project_config['ssm_prefix_template'],
            project_info['project_slug'], project_info['project_type_slug'],
            project_info['namespace_slug'])
        name = ssm_path_prefix + body['name']

        for environment in set(body['environments']):
            role_arn = await self.get_role_arn(environment,
                                               project_info['namespace_id'])
            if not role_arn:
                raise errors.Forbidden(
                    'No role ARN found for namespace %d in %s',
                    project_info['namespace_id'], environment)
            creds = await self.get_aws_credentials(aws_session, role_arn,
                                                   self.current_user,
                                                   google_tokens.id_token,
                                                   google_tokens.refresh_token)

            try:
                await aws.delete_parameter(aws_session, creds['access_key_id'],
                                           creds['secret_access_key'],
                                           creds['session_token'], name)
            except botocore.exceptions.ClientError as error:
                code = error.response['Error']['Code']
                if code == 'ParameterNotFound':
                    continue
                else:
                    raise errors.InternalServerError(code)

        self.set_status(204)

    async def get_role_arn(self, environment,
                           namespace_id) -> typing.Optional[str]:
        result = await self.postgres_execute(self.GET_ROLE_ARN_SQL, {
            'environment': environment,
            'namespace_id': namespace_id
        }, 'get-role-arn')
        if not result.row:
            return None
        return result.row['role_arn']

    async def get_aws_credentials(self,
                                  aws_session: aioboto3.Session,
                                  role_arn,
                                  imbi_user: user.User,
                                  id_token,
                                  refresh_token,
                                  is_retry=False) -> dict:
        """Return (potentially cached or refreshed) AWS credentials."""
        key = f'{imbi_user.username}:{role_arn}'
        cached_creds = await self._redis.hgetall(key)
        if cached_creds:
            return {
                key.decode('utf-8'): value.decode('utf-8')
                for key, value in cached_creds.items()
            }
        try:
            response = await aws.get_credentials(aws_session, role_arn,
                                                 imbi_user.username, id_token)
        except botocore.exceptions.ClientError as error:
            if not is_retry and error.response['Error'][
                    'Code'] == 'ExpiredTokenException':
                id_token = await self.refresh_oauth2_tokens(
                    imbi_user.username, imbi_user.external_id, refresh_token)
                return await self.get_aws_credentials(aws_session, role_arn,
                                                      imbi_user, id_token,
                                                      refresh_token, True)
            elif error.response['Error']['Code'] == 'AccessDenied':
                raise errors.Unauthorized(
                    '%s unauthorized to assume AWS role %s',
                    imbi_user.username,
                    role_arn,
                    reason='Not authorized to access SSM in this '
                    'namespace & environment')
            else:
                raise errors.InternalServerError(
                    'Unexpected AWS credential failure for'
                    '%s assuming AWS role %s: %s',
                    imbi_user.username,
                    role_arn,
                    error.response['Error']['Code'],
                    reason='Unexpected failure fetching AWS credentials')
        creds = {
            'access_key_id': response['Credentials']['AccessKeyId'],
            'secret_access_key': response['Credentials']['SecretAccessKey'],
            'session_token': response['Credentials']['SessionToken']
        }
        await self._redis.hmset_dict(key, creds)
        await self._redis.expireat(
            key, response['Credentials']['Expiration'].timestamp())
        return creds

    async def refresh_oauth2_tokens(self, username, external_id,
                                    refresh_token) -> str:
        google_integration = await oauth2.OAuth2Integration.by_name(
            self.application, self.settings['google']['integration_name'])
        body = urllib.parse.urlencode({
            'grant_type': 'refresh_token',
            'redirect_uri': google_integration.callback_url,
            'refresh_token': refresh_token,
        })
        response = await self.http_fetch(
            str(google_integration.token_endpoint),
            method='POST',
            body=body,
            content_type='application/x-www-form-urlencoded',
            auth_username=google_integration.client_id,
            auth_password=google_integration.client_secret)
        if response.code in (401, 403):
            await self.session.clear()
            self.set_status(403)
            raise web.Finish()
        elif not response.ok:
            self.logger.error(
                'failed to exchange refresh token for new tokens: %s %s',
                response.body['error'], response.body['error_description'])
            raise errors.InternalServerError(
                'failed exchange refresh token for new token: %s',
                response.code,
                title='Google authorization failure',
                instance={
                    'error': response.body['error'],
                    'error_description': response.body['error_description'],
                })
        await google_integration.upsert_user_tokens(
            username,
            external_id,
            response.body['access_token'],
            refresh_token=response.body.get('refresh_token', None),
            id_token=response.body['id_token'])
        return response.body['id_token']

    async def _get_project_info(self, project_id) -> dict:
        result = await self.postgres_execute(self.GET_PROJECT_INFO_SQL,
                                             {'project_id': project_id},
                                             'get-ssm-project-info')
        project_info = result.row

        if project_info['configuration_type'] != 'ssm':
            raise errors.ItemNotFound(
                'Project %s does not use SSM configuration',
                project_info['project_slug'],
                title='Wrong configuration type for project')

        return project_info

    async def _get_google_tokens(self) -> oauth2.IntegrationToken:
        if not self.settings['google']['enabled']:
            raise errors.Forbidden('Google integration is disabled',
                                   title='Google integration is disabled')

        if not self.settings['google']['integration_name']:
            raise errors.Forbidden(
                'No Google integration specified in configuration',
                title='No Google integration specified in configuration')

        tokens = await self.current_user.fetch_integration_tokens(
            self.settings['google']['integration_name'])
        if len(tokens) == 0:
            raise errors.Forbidden(
                'No OAuth 2.0 tokens for %s',
                self.current_user.username,
                title=('Not authorized to access SSM in this namespace &'
                       ' environment'))
        return tokens[0]
