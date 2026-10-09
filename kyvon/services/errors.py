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


class EmailNotVerified(PermissionError):
    """Hosted accounts must confirm their email before anything that costs money."""


class QuotaExceeded(RuntimeError):
    """The account used up its allowance for this period."""

    def __init__(self, kind: str, *, limit: int, used: int, plan: str, resets_at: str):
        self.kind, self.limit, self.used, self.plan, self.resets_at = (
            kind,
            limit,
            used,
            plan,
            resets_at,
        )
        labels = {
            "messages": "message",
            "tokens": "usage",
            "voice": "voice",
            "searches": "web search",
        }
        super().__init__(
            f"You have used your {labels.get(kind, kind)} allowance for this month"
            f"{' on the free plan' if plan == 'free' else ''}. It resets on {resets_at[:10]}."
        )

    def details(self) -> dict:
        return {
            "kind": self.kind,
            "limit": self.limit,
            "used": self.used,
            "plan": self.plan,
            "resets_at": self.resets_at,
        }
