"""Exceptions shared by services (the API layer maps them to HTTP errors)."""


class NotFoundError(LookupError):
    """The record does not exist or belongs to another user."""


class ValidationFailure(ValueError):
    """The input is well-formed but not acceptable."""


class ConflictError(RuntimeError):
    """The action is not allowed in the record's current state."""


class IntegrationError(RuntimeError):
    """An external service (Google, Hermes, Logseq...) failed or refused."""


class NotConnectedError(IntegrationError):
    """The integration needs to be set up or re-authorised by the user."""
