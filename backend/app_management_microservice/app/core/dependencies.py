import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry import trace

from app.core.exceptions import AuthenticationError
from app.services.auth_service import AuthService
from app.utils.tracing import hash_user_id

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    if not credentials:
        raise AuthenticationError("Missing authorization header.")

    payload = AuthService.verify_access_token(credentials.credentials)

    jti = payload.get("jti")
    if jti and await AuthService.is_token_blocklisted(jti):
        raise AuthenticationError("Token has been revoked.")

    user_id = payload.get("sub", "")
    hashed_user_uuid = hash_user_id(user_id) if user_id else ""
    if hashed_user_uuid:
        request.state.hashed_user_uuid = hashed_user_uuid
        structlog.contextvars.bind_contextvars(hashed_user_uuid=hashed_user_uuid)
        span = trace.get_current_span()
        if span is not None and span.is_recording():
            span.set_attribute("auth.hashed_user_uuid", hashed_user_uuid)

    return payload
