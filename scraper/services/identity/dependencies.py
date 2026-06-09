"""
FastAPI dependencies for authentication.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from services.identity.security import decode_token
from core.database import get_conn, USE_POSTGRES

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer)
):
    """Extract and validate JWT from Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = payload.get("sub")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, full_name, role, status FROM users WHERE id = %s"
            if USE_POSTGRES else
            "SELECT id, email, full_name, role, status FROM users WHERE id = ?",
            (user_id,)
        )
        user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user = dict(user)
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="Account suspended")

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer)
):
    """Return user if authenticated, None if not."""
    if not credentials:
        return None
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


def require_role(*roles: str):
    """Dependency factory to require specific roles."""
    async def dependency(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(roles)}"
            )
        return user
    return dependency
