class AppError(Exception):
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationAppError(AppError):
    code = "VALIDATION_ERROR"


class AuthenticationError(AppError):
    code = "AUTHENTICATION_ERROR"


class AuthorizationError(AppError):
    code = "AUTHORIZATION_ERROR"


class NotFoundError(AppError):
    code = "NOT_FOUND"
