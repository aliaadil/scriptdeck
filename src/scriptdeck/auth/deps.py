from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from scriptdeck.auth.users import User, get_by_id


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer")
    token = authorization.split(" ", 1)[1].strip()
    from scriptdeck.auth.jwt import decode_jwt

    try:
        payload = decode_jwt(token, secret=request.app.state.settings.jwt_secret or "")
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    session_factory = request.app.state.session_factory
    async with session_factory() as s:
        user = await get_by_id(s, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user