"""Re-export models from imbi_common for convenience.

This module provides a convenient import path for models:
    from imbi_api import models
    models.Organization(...)

Instead of:
    from imbi_common import models
    models.Organization(...)
"""

import imbi_common.models

# Re-export all public names from imbi_common.models
__all__ = imbi_common.models.__all__

# Re-export all models as explicit aliases for type-checker support.
# NOTE: When imbi_common.models adds new exports, add them here too.
APIKey = imbi_common.models.APIKey
Blueprint = imbi_common.models.Blueprint
BlueprintAssignment = imbi_common.models.BlueprintAssignment
BlueprintEdge = imbi_common.models.BlueprintEdge
EmptyRelationship = imbi_common.models.EmptyRelationship
Environment = imbi_common.models.Environment
Group = imbi_common.models.Group
GroupEdge = imbi_common.models.GroupEdge
MODEL_TYPES = imbi_common.models.MODEL_TYPES
Node = imbi_common.models.Node
OAuthIdentity = imbi_common.models.OAuthIdentity
Organization = imbi_common.models.Organization
PasswordChangeRequest = imbi_common.models.PasswordChangeRequest
Permission = imbi_common.models.Permission
Project = imbi_common.models.Project
ProjectType = imbi_common.models.ProjectType
ResourcePermission = imbi_common.models.ResourcePermission
Role = imbi_common.models.Role
RoleEdge = imbi_common.models.RoleEdge
Schema = imbi_common.models.Schema
Session = imbi_common.models.Session
TOTPSecret = imbi_common.models.TOTPSecret
Team = imbi_common.models.Team
TokenMetadata = imbi_common.models.TokenMetadata
User = imbi_common.models.User
UserCreate = imbi_common.models.UserCreate
UserResponse = imbi_common.models.UserResponse
