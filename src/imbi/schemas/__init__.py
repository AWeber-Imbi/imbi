"""Pydantic schemas for API request/response models."""

from imbi.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    WhoAmIResponse,
)
from imbi.schemas.environment import (
    EnvironmentCreate,
    EnvironmentResponse,
    EnvironmentUpdate,
)
from imbi.schemas.group import (
    GroupCreate,
    GroupMemberAdd,
    GroupMemberResponse,
    GroupResponse,
    GroupUpdate,
)
from imbi.schemas.namespace import (
    NamespaceCreate,
    NamespaceResponse,
    NamespaceUpdate,
)
from imbi.schemas.operations_log import (
    OperationsLogCreate,
    OperationsLogListResponse,
    OperationsLogResponse,
    OperationsLogUpdate,
)
from imbi.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from imbi.schemas.project_relations import (
    FactTypeCreate,
    FactTypeResponse,
    FactTypeUpdate,
    ProjectDependencyCreate,
    ProjectDependencyResponse,
    ProjectFactCreate,
    ProjectFactResponse,
    ProjectFactUpdate,
    ProjectLinkCreate,
    ProjectLinkResponse,
    ProjectLinkTypeCreate,
    ProjectLinkTypeResponse,
    ProjectLinkTypeUpdate,
    ProjectLinkUpdate,
    ProjectNoteCreate,
    ProjectNoteResponse,
    ProjectNoteUpdate,
    ProjectURLCreate,
    ProjectURLResponse,
    ProjectURLUpdate,
)
from imbi.schemas.project_type import (
    ProjectTypeCreate,
    ProjectTypeResponse,
    ProjectTypeUpdate,
)

__all__ = [
    # Auth schemas
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "WhoAmIResponse",
    # Namespace schemas
    "NamespaceCreate",
    "NamespaceResponse",
    "NamespaceUpdate",
    # ProjectType schemas
    "ProjectTypeCreate",
    "ProjectTypeResponse",
    "ProjectTypeUpdate",
    # Environment schemas
    "EnvironmentCreate",
    "EnvironmentResponse",
    "EnvironmentUpdate",
    # Group schemas
    "GroupCreate",
    "GroupResponse",
    "GroupUpdate",
    "GroupMemberAdd",
    "GroupMemberResponse",
    # Project schemas
    "ProjectCreate",
    "ProjectResponse",
    "ProjectUpdate",
    "ProjectListResponse",
    # Operations log schemas
    "OperationsLogCreate",
    "OperationsLogResponse",
    "OperationsLogUpdate",
    "OperationsLogListResponse",
    # Project relation schemas
    "ProjectDependencyCreate",
    "ProjectDependencyResponse",
    "ProjectLinkCreate",
    "ProjectLinkResponse",
    "ProjectLinkUpdate",
    "ProjectLinkTypeCreate",
    "ProjectLinkTypeResponse",
    "ProjectLinkTypeUpdate",
    "ProjectURLCreate",
    "ProjectURLResponse",
    "ProjectURLUpdate",
    "ProjectFactCreate",
    "ProjectFactResponse",
    "ProjectFactUpdate",
    "FactTypeCreate",
    "FactTypeResponse",
    "FactTypeUpdate",
    "ProjectNoteCreate",
    "ProjectNoteResponse",
    "ProjectNoteUpdate",
]
