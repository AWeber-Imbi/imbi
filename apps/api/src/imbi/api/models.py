"""Re-export all models for convenient access.

Combines shared models from imbi_common and API-specific models
from imbi_api.domain for a single import path:
    from imbi_api import models
    models.Organization(...)
    models.User(...)
"""

import json
import typing
import warnings

from imbi_common import models as _common

from imbi_api.domain import models as _domain

__all__ = [  # pyright: ignore[reportUnsupportedDunderAll]
    *_common.__all__,
    *_domain.__all__,
]

# Shared domain models from imbi-common
Blueprint = _common.Blueprint
BlueprintAssignment = _common.BlueprintAssignment
BlueprintEdge = _common.BlueprintEdge
DeploymentEvent = _common.DeploymentEvent
Environment = _common.Environment
LinkDefinition = _common.LinkDefinition
MCPServer = _common.MCPServer
Node = _common.Node
Organization = _common.Organization
Project = _common.Project
ProjectType = _common.ProjectType
RelationshipLink = _common.RelationshipLink
Release = _common.Release
ReleaseDeploymentEdge = _common.ReleaseDeploymentEdge
ReleaseLink = _common.ReleaseLink
Schema = _common.Schema
Team = _common.Team

# Blueprint-eligible model types for OpenAPI schema generation
MODEL_TYPES: dict[str, type[_common.Node]] = {
    'Environment': _common.Environment,
    'LinkDefinition': _common.LinkDefinition,
    'Organization': _common.Organization,
    'Project': _common.Project,
    'ProjectType': _common.ProjectType,
    'Team': _common.Team,
}

# API-specific models from imbi_api.domain
ThirdPartyService = _domain.ThirdPartyService
APIKey = _domain.APIKey
ClientCredential = _domain.ClientCredential
ClientCredentialCreate = _domain.ClientCredentialCreate
ClientCredentialCreateResponse = _domain.ClientCredentialCreateResponse
ClientCredentialResponse = _domain.ClientCredentialResponse
CurrentUserResponse = _domain.CurrentUserResponse
EmptyRelationship = _domain.EmptyRelationship
MembershipProperties = _domain.MembershipProperties
OAuth2TokenResponse = _domain.OAuth2TokenResponse
OAuthClient = _domain.OAuthClient
OAuthClientRegistrationRequest = _domain.OAuthClientRegistrationRequest
OAuthClientRegistrationResponse = _domain.OAuthClientRegistrationResponse
OAuthIdentity = _domain.OAuthIdentity
OrgMembership = _domain.OrgMembership
OrganizationEdge = _domain.OrganizationEdge
PasswordChangeRequest = _domain.PasswordChangeRequest
Permission = _domain.Permission
ResourcePermission = _domain.ResourcePermission
Role = _domain.Role
ServiceAccount = _domain.ServiceAccount
ServiceAccountCreate = _domain.ServiceAccountCreate
ServiceAccountResponse = _domain.ServiceAccountResponse
ServiceApplicationCreate = _domain.ServiceApplicationCreate
ServiceApplicationResponse = _domain.ServiceApplicationResponse
ServiceApplicationSecrets = _domain.ServiceApplicationSecrets
Session = _domain.Session
TOTPSecret = _domain.TOTPSecret
TokenMetadata = _domain.TokenMetadata
Upload = _domain.Upload
User = _domain.User
UserCreate = _domain.UserCreate
UserResponse = _domain.UserResponse


@warnings.deprecated(
    'parse_scopes is a compatibility shim for legacy AGE rows that '
    "stored list properties as PostgreSQL-array strings (e.g. '{a,b}')."
    ' Cypher writes have stored lists as JSON since the list-'
    'serialization fix; callers should switch to ``graph.parse_agtype``'
    ' once every legacy scope row has been rewritten. Plan to remove '
    'this helper alongside that backfill -- see CODE_REVIEW_PUNCHLIST '
    'L4 for the open migration deadline.'
)
def parse_scopes(value: typing.Any) -> list[str]:
    """Convert AGE scope values to a Python list.

    AGE may store list properties as PostgreSQL array strings
    (e.g. ``'{}'`` or ``'{read,write}'``), or as JSON-serialized
    strings (e.g. ``'["read","write"]'``) when they were written
    before the Cypher list-serialization fix.

    """
    if isinstance(value, list):
        return [str(v) for v in typing.cast(list[object], value)]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith('['):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(v) for v in typing.cast(list[object], parsed)]
            except (json.JSONDecodeError, ValueError):
                pass
        inner = stripped.strip('{}')
        return inner.split(',') if inner else []
    return []
