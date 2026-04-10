"""Authentication and authorization for the assistant service."""

import logging
import typing

import fastapi
import jwt
import pydantic
from fastapi import security
from imbi_common import graph, settings
from imbi_common.auth import core

LOGGER = logging.getLogger(__name__)

oauth2_scheme = security.HTTPBearer(auto_error=False)


class User(pydantic.BaseModel):
    """Minimal user model for assistant endpoints."""

    model_config = pydantic.ConfigDict(extra='ignore')

    email: pydantic.EmailStr
    display_name: str
    is_active: bool = True
    is_admin: bool = False


class AuthContext(pydantic.BaseModel):
    """Authentication context for the current request."""

    user: User | None = None
    session_id: str | None = None
    auth_method: typing.Literal['jwt'] = 'jwt'
    permissions: set[str] = pydantic.Field(
        default_factory=set,
    )

    @property
    def is_admin(self) -> bool:
        """Return whether the principal is an admin."""
        return self.user.is_admin if self.user else False

    @property
    def require_user(self) -> User:
        """Return the authenticated user or raise 403."""
        if self.user is None:
            raise fastapi.HTTPException(
                403,
                'This endpoint requires user authentication',
            )
        return self.user


async def load_user_permissions(
    db: graph.Graph,
    email: str,
) -> set[str]:
    """Get permission names granted to a user."""
    query = """
    MATCH (u:User {{email: {email}}})
          -[m:MEMBER_OF]->(o:Organization)
    MATCH (r:Role {{slug: m.role}})
    OPTIONAL MATCH (r)-[:INHERITS_FROM*0..]->(parent:Role)
    WITH DISTINCT parent
    OPTIONAL MATCH (parent)-[:GRANTS]->(perm:Permission)
    RETURN collect(DISTINCT perm.name) AS permissions
    """
    records = await db.execute(
        query,
        {'email': email},
        ['permissions'],
    )
    if not records:
        return set()
    perms = graph.parse_agtype(records[0].get('permissions'))
    if isinstance(perms, list):
        return set(perms)
    return set()


async def get_current_user(
    db: graph.Pool,
    credentials: (
        security.HTTPAuthorizationCredentials | None
    ) = fastapi.Depends(oauth2_scheme),  # noqa: B008
) -> AuthContext:
    """FastAPI dependency to get the current authenticated
    user."""
    if not credentials:
        raise fastapi.HTTPException(
            status_code=401,
            detail='Missing authentication credentials',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    auth_settings = settings.get_auth_settings()
    token = credentials.credentials

    try:
        claims = core.verify_token(token, auth_settings)
    except jwt.ExpiredSignatureError as err:
        raise fastapi.HTTPException(
            status_code=401, detail='Token has expired'
        ) from err
    except jwt.InvalidTokenError as err:
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid token'
        ) from err

    if claims.get('type') != 'access':
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid token type'
        )

    subject = claims.get('sub')
    if not subject:
        raise fastapi.HTTPException(
            status_code=401, detail='Token missing subject'
        )

    user_query = """
    MATCH (u:User {{email: {email}}})
    RETURN u
    """
    records = await db.execute(
        user_query,
        {'email': subject},
        ['u'],
    )
    if not records:
        raise fastapi.HTTPException(status_code=401, detail='User not found')
    user_data = graph.parse_agtype(records[0]['u'])
    user = User(**user_data)

    if not user.is_active:
        raise fastapi.HTTPException(
            status_code=401,
            detail='User account is inactive',
        )

    perms = await load_user_permissions(db, subject)

    return AuthContext(
        user=user,
        session_id=claims.get('jti'),
        permissions=perms,
    )
