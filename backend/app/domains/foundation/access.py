from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import AuthIdentity, get_auth_identity
from app.domains.foundation.models import AppUser, Role


@dataclass(frozen=True)
class UserContext:
    user: AppUser
    permission_keys: frozenset[str]

    def has(self, permission_key: str) -> bool:
        return permission_key in self.permission_keys


def get_current_user_context(
    identity: AuthIdentity = Depends(get_auth_identity),
    db: Session = Depends(get_db),
) -> UserContext:
    stmt = (
        select(AppUser)
        .options(selectinload(AppUser.roles).selectinload(Role.permissions))
        .where(AppUser.auth_user_id == identity.subject)
    )
    user = db.scalar(stmt)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário autenticado ainda não está habilitado neste ERP",
        )
    if not user.is_active or user.blocked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário bloqueado")

    permissions = frozenset(permission.key for role in user.roles if role.is_active for permission in role.permissions)
    return UserContext(user=user, permission_keys=permissions)


def require_permission(permission_key: str):
    def dependency(context: UserContext = Depends(get_current_user_context)) -> UserContext:
        if not context.has(permission_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permissão necessária: {permission_key}",
            )
        return context

    return dependency
