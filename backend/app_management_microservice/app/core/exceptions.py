from typing import Any, Optional


class AppException(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[Any] = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundError(AppException):
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            code=f"{resource.upper()}_NOT_FOUND",
            message=f"The requested {resource} ('{identifier}') does not exist.",
            status_code=404,
        )


class ValidationError(AppException):
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=422,
            details=details,
        )


class AuthenticationError(AppException):
    def __init__(self, message: str = "Authentication required."):
        super().__init__(
            code="AUTHENTICATION_ERROR",
            message=message,
            status_code=401,
        )


class AuthorizationError(AppException):
    def __init__(self, message: str = "Insufficient permissions."):
        super().__init__(
            code="AUTHORIZATION_ERROR",
            message=message,
            status_code=403,
        )


class ExternalServiceError(AppException):
    def __init__(self, service: str, message: str):
        super().__init__(
            code=f"{service.upper()}_ERROR",
            message=f"External service error ({service}): {message}",
            status_code=502,
        )
