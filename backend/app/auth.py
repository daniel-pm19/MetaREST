"""JWT authentication with current database role/active checks on every request."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.platform import Role, UserRecord

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if not 12 <= len(raw) <= 72:
        raise ValueError("La contraseña debe tener entre 12 y 72 bytes UTF-8")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode())
    except ValueError:
        return False


def issue_token(user: UserRecord, settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user.id,
            "role": user.role.value,
            "iat": now,
            "exp": now + timedelta(minutes=settings.jwt_expiration_minutes),
            "iss": "metarest",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> UserRecord:
    denied = HTTPException(401, "Sesión inválida o expirada", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise denied
    try:
        payload = jwt.decode(
            credentials.credentials,
            request.app.state.settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer="metarest",
            options={"require": ["sub", "exp", "iat"]},
        )
        user = await UserRecord.get(payload["sub"])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise denied from None
    if user is None or not user.active:
        raise denied
    return user


def require_role(*roles: Role):
    async def authorized(user: Annotated[UserRecord, Depends(current_user)]) -> UserRecord:
        if user.role not in roles:
            raise HTTPException(403, "Tu rol no tiene permiso para esta acción")
        return user

    return authorized


Reader = Annotated[UserRecord, Depends(current_user)]
Writer = Annotated[UserRecord, Depends(require_role(Role.ADMIN, Role.QA))]
Admin = Annotated[UserRecord, Depends(require_role(Role.ADMIN))]
