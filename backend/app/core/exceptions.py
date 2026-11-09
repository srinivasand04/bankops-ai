"""Domain exceptions mapped to HTTP responses in app.main."""


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class InvalidTransitionError(DomainError):
    status_code = 409
    code = "invalid_status_transition"


class BusinessRuleError(DomainError):
    status_code = 422
    code = "business_rule_violation"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "permission_denied"


class RateLimitedError(DomainError):
    """A usage limit was reached (e.g. the public demo's daily AI analysis cap)."""

    status_code = 429
    code = "rate_limited"


class AiUnavailableError(DomainError):
    """Claude could not be reached or is not configured (credentials, rate limit, network)."""

    status_code = 503
    code = "ai_unavailable"


class AiResponseError(DomainError):
    """Claude answered, but the answer was unusable (refusal, truncation, invalid structure)."""

    status_code = 502
    code = "ai_response_invalid"


class AuthenticationError(DomainError):
    status_code = 401
    code = "authentication_required"
