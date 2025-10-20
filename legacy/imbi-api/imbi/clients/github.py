import http.client
import logging
import typing
import urllib.parse

import pydantic
import sprockets.mixins.http
import tornado.web
import yarl

from imbi import errors, oauth2, user, version
if typing.TYPE_CHECKING:
    from imbi import app


class RepositoryOwner(pydantic.BaseModel):
    login: str


class Repository(pydantic.BaseModel):
    id: int
    name: str
    owner: RepositoryOwner
    html_url: str


class GitHubAPIFailure(errors.ApplicationError):

    def __init__(self, response: sprockets.mixins.http.HTTPResponse,
                 log_message: str, *log_args, **kwargs) -> None:
        status_code = response.code
        kwargs.setdefault('title', 'GitHub API Failure')
        kwargs['github_response_body'] = response.body

        # A GitHub "unauthorized" response is not the same as an
        # Imbi "unauthorized". HTTP unauthorized always refers to
        # the user requested resource which is an Imbi resource.
        if status_code == http.HTTPStatus.UNAUTHORIZED:
            status_code = http.HTTPStatus.FORBIDDEN

        super().__init__(status_code, 'github-api-failure', log_message,
                         *log_args, **kwargs)


async def create_client(
    application: 'app.Application',
    integration_name: str,
    current_user: user.User,
) -> 'GitHubClient':
    tokens = await current_user.fetch_integration_tokens(integration_name)
    if not tokens:
        raise errors.ClientUnavailableError(
            integration_name,
            f'no {integration_name!r} token for {current_user.username}',
        )

    return GitHubClient(current_user, tokens[0], application)


class GitHubClient(sprockets.mixins.http.HTTPClientMixin):

    def __init__(
        self,
        user: user.User,
        token: oauth2.IntegrationToken,
        application: tornado.web.Application,
    ):
        super().__init__()
        self.logger = logging.getLogger(__package__).getChild('GitHubClient')
        self.user = user
        self.token = token
        self.headers = {
            'Accept': str(sprockets.mixins.http.CONTENT_TYPE_JSON),
            'Authorization': f'Bearer {self.token.access_token}',
            'X-GitHub-Api-Version': '2022-11-28',
        }

    async def api(self,
                  url: typing.Union[yarl.URL, str],
                  *,
                  method: str = 'GET',
                  **kwargs):
        """Make an authenticated request to the GitHub API."""
        if not isinstance(url, yarl.URL):
            url = yarl.URL(url)
        if not url.is_absolute():
            url = self.token.integration.api_endpoint / url.path.lstrip('/')
        request_headers = kwargs.setdefault('request_headers', {})
        request_headers.update(self.headers)
        if kwargs.get('body', None) is not None:
            request_headers['Content-Type'] = str(
                sprockets.mixins.http.CONTENT_TYPE_JSON)
            kwargs['content_type'] = str(
                sprockets.mixins.http.CONTENT_TYPE_JSON)
        kwargs['user_agent'] = f'imbi/{version} (GitHubClient)'
        self.logger.debug('%s %s', method, url)

        response = await super().http_fetch(str(url), method=method, **kwargs)
        if response.code == http.client.BAD_REQUEST and response.body:
            self.logger.warning(
                '%s %s failed: status=%s response=%r',
                method,
                url,
                response.code,
                response.body,
            )
        if response.code == http.client.UNAUTHORIZED:
            await self._refresh_token()
            request_headers.update(self.headers)
            response = await super().http_fetch(str(url),
                                                method=method,
                                                **kwargs)
        return response

    async def _refresh_token(self) -> None:
        params = urllib.parse.urlencode({
            'grant_type': 'refresh_token',
            'refresh_token': self.token.refresh_token,
            'client_id': self.token.integration.client_id,
            'client_secret': self.token.integration.client_secret,
        })
        url = f'{self.token.integration.token_endpoint}?{params}'
        self.logger.info('refreshing token for %s (%s)', self.user.username,
                         self.token.external_id)
        self.logger.debug('refresh_request: %r', params)
        response = await super().http_fetch(
            url,
            method='POST',
            allow_nonstandard_methods=True,
        )
        if response.ok:
            self.logger.debug('refresh response: %r', response.body)
            await self.token.integration.upsert_user_tokens(
                self.user.username,
                self.token.external_id,
                response.body['access_token'],
                response.body['refresh_token'],
                self.token.id_token,
            )
            self.token.access_token = response.body['access_token']
            self.token.refresh_token = response.body['refresh_token']
            self.headers['Authorization'] = f'Bearer {self.token.access_token}'
        else:
            self.logger.error(
                'failed to refresh token for %s: %r',
                self.user.username,
                response.body,
            )
            raise GitHubAPIFailure(response, 'token refresh failed: %s',
                                   response.code)

    async def create_repository(self, org: str, name: str, project_id: int,
                                namespace_slug: str,
                                **attributes) -> Repository:
        """Create a new repository on GitHub.

        Args:
            org: The organization to create the repository in
            name: The name of the repository
            project_id: The Imbi project ID for custom properties
            namespace_slug: The namespace slug for custom properties
            **attributes**: Additional repository attributes

        Docs: https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#create-an-organization-repository
        """  # noqa: E501
        # Set default values for Imbi repositories
        body = {
            'name': name,
            'has_issues': False,
            'has_projects': False,
            'has_wiki': False,
            'auto_init': False,
            'delete_branch_on_merge': True,
            'custom_properties': {
                'imbi_project_id': str(project_id),
                'team': namespace_slug.lower(),
            },
            **attributes
        }

        response = await self.api(
            f'/orgs/{org}/repos',
            method='POST',
            body=body,
        )
        if response.ok:
            return Repository.model_validate(response.body)
        else:
            if response.code == http.HTTPStatus.UNPROCESSABLE_ENTITY:
                self.logger.error(
                    'failed to create repository %s/%s (422): %s',
                    org,
                    name,
                    response.body,
                )
            raise GitHubAPIFailure(
                response,
                'failed to create repository %s',
                name,
            )

    async def delete_repository(self, org: str, repo: str) -> None:
        """Delete a repository on GitHub.

        Docs: https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#delete-a-repository

        Args:
            org: The organization that contains the repository
            repo: The name of the repository to delete
        """  # noqa: E501
        response = await self.api(
            f'/repos/{org}/{repo}',
            method='DELETE',
        )
        if not response.ok or response.code not in (http.HTTPStatus.NOT_FOUND,
                                                    http.HTTPStatus.GONE):
            raise GitHubAPIFailure(
                response,
                '%s failed to delete repository %s',
                org,
                repo,
            )

    async def add_team_to_repository(
        self,
        org: str,
        repo: str,
        team_slug: str,
        permission: str = 'maintain',
    ) -> None:
        """
        Add a team to a repository with specified permissions.

        Args:
            org: The organization that contains the repository
            repo: The repository name
            team_slug: The team slug
            permission: Permission level ('pull', 'triage', 'push', 'maintain')
        """
        payload = {'permission': permission}

        response = await self.api(
            f'/orgs/{org}/teams/{team_slug}/repos/{org}/{repo}',
            method='PUT',
            body=payload,
        )
        if not response.ok:
            raise GitHubAPIFailure(
                response,
                'Failed to add team to repository',
            )

    async def create_environment(
        self,
        org: str,
        repo: str,
        environment: str,
    ) -> None:
        """
        Create an environment for a repository.

        Args:
            org: The organization that contains the repository
            repo: The repository name
            environment: The environment slug
        """
        response = await self.api(
            f'/repos/{org}/{repo}/environments/{environment}',
            method='POST',
            body={},
        )
        if not response.ok:
            raise GitHubAPIFailure(
                response,
                'Failed to create environment',
            )

    async def delete_environment(
        self,
        org: str,
        repo: str,
        environment: str,
    ) -> None:
        """
        Delete an environment for a repository.

        Args:
            org: The organization that contains the repository
            repo: The repository name
            environment: The environment slug
        """
        response = await self.api(
            f'/repos/{org}/{repo}/environments/{environment}',
            method='DELETE',
        )
        if not response.ok:
            raise GitHubAPIFailure(
                response,
                'Failed to delete environment',
            )

    async def create_deployment(
        self,
        org: str,
        repo: str,
        ref: str,
        environment: str,
    ) -> None:
        """
        Create a deployment for a repository.

        Args:
            org: The organization that contains the repository
            repo: The repository name
            ref: The ref to deploy (branch, SHA, or tag)
            environment: The environment slug to deploy to

        Docs: https://docs.github.com/rest/deployments/deployments#create-a-deployment
        """  # noqa: E501
        payload = {
            'ref': ref,
            'environment': environment,
            'auto_merge': False,
            'required_contexts': [],
        }

        response = await self.api(
            f'/repos/{org}/{repo}/deployments',
            method='POST',
            body=payload,
        )
        if not response.ok:
            raise GitHubAPIFailure(
                response,
                'Failed to create deployment',
            )

    async def get_matching_refs(
        self,
        org: str,
        repo: str,
        ref: str = 'tags',
    ) -> list:
        """
        Get matching refs for a repository.

        Args:
            org: The organization that contains the repository
            repo: The repository name
            ref: The ref pattern to match (default: 'tags')

        Docs: https://docs.github.com/rest/git/refs#list-matching-references
        """
        response = await self.api(
            f'/repos/{org}/{repo}/git/matching-refs/{ref}',
            method='GET',
        )
        if not response.ok:
            raise GitHubAPIFailure(
                response,
                'Failed to get matching refs',
            )
        return response.body
