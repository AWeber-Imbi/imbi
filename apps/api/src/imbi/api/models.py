"""Re-export all models for convenient access.

Combines shared models from imbi_common and API-specific models
from imbi_api.domain for a single import path:
    from imbi_api import models
    models.Organization(...)
    models.User(...)
"""

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
Environment = _common.Environment
MODEL_TYPES = _common.MODEL_TYPES
Node = _common.Node
Organization = _common.Organization
Project = _common.Project
ProjectType = _common.ProjectType
RelationshipLink = _common.RelationshipLink
Schema = _common.Schema
Team = _common.Team

# API-specific models from imbi_api.domain
ThirdPartyService = _domain.ThirdPartyService
APIKey = _domain.APIKey
ClientCredential = _domain.ClientCredential
ClientCredentialCreate = _domain.ClientCredentialCreate
ClientCredentialCreateResponse = _domain.ClientCredentialCreateResponse
ClientCredentialResponse = _domain.ClientCredentialResponse
EmptyRelationship = _domain.EmptyRelationship
MembershipProperties = _domain.MembershipProperties
OAuth2TokenResponse = _domain.OAuth2TokenResponse
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
ServiceAccountUpdate = _domain.ServiceAccountUpdate
ServiceApplicationCreate = _domain.ServiceApplicationCreate
ServiceApplicationResponse = _domain.ServiceApplicationResponse
ServiceApplicationSecrets = _domain.ServiceApplicationSecrets
ServiceApplicationSecretsUpdate = _domain.ServiceApplicationSecretsUpdate
ServiceApplicationUpdate = _domain.ServiceApplicationUpdate
Session = _domain.Session
TOTPSecret = _domain.TOTPSecret
TokenMetadata = _domain.TokenMetadata
Upload = _domain.Upload
User = _domain.User
UserCreate = _domain.UserCreate
UserResponse = _domain.UserResponse
UserUpdate = _domain.UserUpdate
