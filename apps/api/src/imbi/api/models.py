"""Re-export all models for convenient access.

Combines shared models from imbi.common and API-specific models
from imbi.api.domain for a single import path:
    from imbi.api import models
    models.Organization(...)
    models.User(...)
"""

from imbi.api.domain import models as _domain
from imbi.common import models as _common

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
Integration = _common.Integration
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
    'Integration': _common.Integration,
    'Organization': _common.Organization,
    'Project': _common.Project,
    'ProjectType': _common.ProjectType,
    'Team': _common.Team,
}

# API-specific models from imbi.api.domain
CapabilityAssignment = _domain.CapabilityAssignment
CapabilityAssignmentsUpdate = _domain.CapabilityAssignmentsUpdate
CapabilityToggle = _domain.CapabilityToggle
InstalledPluginResponse = _domain.InstalledPluginResponse
IntegrationCreate = _domain.IntegrationCreate
IntegrationCredentialsUpdate = _domain.IntegrationCredentialsUpdate
IntegrationResponse = _domain.IntegrationResponse
IntegrationUpdate = _domain.IntegrationUpdate
PluginRegistrationUpdate = _domain.PluginRegistrationUpdate
ProjectIntegrationAssignment = _domain.ProjectIntegrationAssignment
ProjectIntegrationsUpdate = _domain.ProjectIntegrationsUpdate
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
Session = _domain.Session
TOTPSecret = _domain.TOTPSecret
TeamMembership = _domain.TeamMembership
TokenMetadata = _domain.TokenMetadata
Upload = _domain.Upload
User = _domain.User
UserCreate = _domain.UserCreate
UserResponse = _domain.UserResponse

# Moved to imbi-common alongside the principal models the shared auth
# path needs; still reachable as ``models.parse_scopes`` here.
parse_scopes = _common.parse_scopes
