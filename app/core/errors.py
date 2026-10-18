class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class BusinessRuleError(AppError):
    status_code = 422
    code = "business_rule_violation"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class IntegrationError(AppError):
    status_code = 502
    code = "integration_error"
