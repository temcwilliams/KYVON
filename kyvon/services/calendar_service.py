"""Google Calendar for one user: OAuth connection plus event operations.

Tokens are encrypted at rest (Fernet, key from KYVON_ENCRYPTION_KEY). The OAuth ``state``
is single-use, expires after ten minutes and is bound to the user who started the flow,
and the code exchange uses PKCE.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kyvon.config import Settings
from kyvon.db import utcnow
from kyvon.integrations import google_calendar as g
from kyvon.models import CalendarAccount, OAuthState
from kyvon.services.environment_context import safe_zone
from kyvon.services.errors import IntegrationError, NotConnectedError, ValidationFailure
from kyvon.services.settings_service import timezone_for
from kyvon.services.tasks_time import parse_due
from kyvon.utils.crypto import CryptoError, SecretBox

STATE_TTL = timedelta(minutes=10)
TOKEN_SKEW = timedelta(seconds=60)
_ID = re.compile(r"^[A-Za-z0-9_.@%+-]{1,256}$")
_EVENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
NOT_CONFIGURED = (
    "Google Calendar is not set up on this server (needs GOOGLE_CLIENT_ID, "
    "GOOGLE_CLIENT_SECRET and KYVON_ENCRYPTION_KEY)."
)
NOT_CONNECTED = "Google Calendar is not connected. Connect it from the Calendar tab first."


def redirect_uri(settings: Settings) -> str:
    return settings.public_url.rstrip("/") + "/api/v1/calendar/callback"


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def check_calendar_id(calendar_id: str | None) -> str:
    value = calendar_id or "primary"
    if not _ID.match(value):
        raise ValidationFailure("That calendar id is not valid.")
    return value


def check_event_id(event_id: str) -> str:
    if not _EVENT_ID.match(event_id or ""):
        raise ValidationFailure("That event id is not valid.")
    return event_id


def normalize_event(raw: dict, calendar_id: str = "primary") -> dict:
    start, end = raw.get("start", {}), raw.get("end", {})
    all_day = "date" in start
    return {
        "id": raw.get("id"),
        "calendar_id": calendar_id,
        "title": raw.get("summary") or "(no title)",
        "start": start.get("date") or start.get("dateTime"),
        "end": end.get("date") or end.get("dateTime"),
        "all_day": all_day,
        "location": raw.get("location") or "",
        "description": (raw.get("description") or "")[:500],
        "status": raw.get("status", "confirmed"),
    }


class CalendarService:
    def __init__(
        self,
        session: Session,
        user_id: int,
        *,
        settings: Settings,
        http: Any,
        now: Callable[[], datetime] = utcnow,
    ):
        self._s = session
        self._user_id = user_id
        self._settings = settings
        self._http = http
        self._now = now
        self._box: SecretBox | None = None

    # ------------------------------------------------------------ configuration / status

    @property
    def configured(self) -> bool:
        return self._settings.calendar_configured

    def _secret_box(self) -> SecretBox:
        if not self.configured:
            raise NotConnectedError(NOT_CONFIGURED)
        if self._box is None:
            try:
                self._box = SecretBox(self._settings.encryption_key)
            except CryptoError as error:
                raise IntegrationError(str(error)) from error
        return self._box

    def _oauth(self) -> g.GoogleOAuth:
        return g.GoogleOAuth(
            self._http,
            self._settings.google_client_id,
            self._settings.google_client_secret,
            redirect_uri(self._settings),
        )

    def account(self) -> CalendarAccount | None:
        return self._s.scalar(
            select(CalendarAccount).where(
                CalendarAccount.user_id == self._user_id, CalendarAccount.provider == "google"
            )
        )

    def status(self) -> dict:
        account = self.account()
        return {
            "configured": self.configured,
            "connected": account is not None,
            "account_email": account.account_email if account else None,
            "scopes": account.scopes.split() if account else [],
            "connected_at": account.created_at.isoformat() if account else None,
        }

    # ------------------------------------------------------------ OAuth

    def begin_authorization(self) -> str:
        box = self._secret_box()
        state = secrets.token_urlsafe(32)
        verifier, challenge = g.pkce_pair()
        now = self._now()
        # Abandoned attempts are cleaned up as new ones start.
        self._s.execute(delete(OAuthState).where(OAuthState.expires_at < now))
        self._s.add(
            OAuthState(
                user_id=self._user_id,
                state_hash=_hash_state(state),
                verifier_enc=box.encrypt(verifier),
                created_at=now,
                expires_at=now + STATE_TTL,
            )
        )
        self._s.commit()
        return g.build_authorization_url(
            self._settings.google_client_id, redirect_uri(self._settings), state, challenge
        )

    def disconnect(self) -> bool:
        account = self.account()
        if account is None:
            return False
        try:
            self._oauth().revoke(self._secret_box().decrypt(account.refresh_token_enc))
        except (CryptoError, NotConnectedError, IntegrationError):
            pass
        self._s.delete(account)
        self._s.commit()
        return True

    # ------------------------------------------------------------ tokens

    def _access_token(self) -> str:
        account = self.account()
        if account is None:
            raise NotConnectedError(NOT_CONNECTED if self.configured else NOT_CONFIGURED)
        box = self._secret_box()
        now = self._now()
        if (
            account.access_token_enc
            and account.access_expires_at
            and account.access_expires_at - TOKEN_SKEW > now
        ):
            return box.decrypt(account.access_token_enc)
        try:
            tokens = self._oauth().refresh(box.decrypt(account.refresh_token_enc))
        except g.GoogleAuthError as error:
            self._s.delete(account)  # the grant is gone; forget it so the UI shows "connect"
            self._s.commit()
            raise NotConnectedError(
                "Google Calendar access was revoked or expired. Please connect it again."
            ) from error
        except g.GoogleAPIError as error:
            raise IntegrationError(f"Google sign-in failed: {error.message}") from error
        account.access_token_enc = box.encrypt(tokens.access_token)
        account.access_expires_at = now + timedelta(seconds=tokens.expires_in)
        self._s.commit()
        return tokens.access_token

    def _api(self) -> g.GoogleCalendarAPI:
        return g.GoogleCalendarAPI(self._http, self._access_token())

    def _call(self, action: Callable[[g.GoogleCalendarAPI], Any]) -> Any:
        try:
            return action(self._api())
        except g.GoogleAuthError as error:
            account = self.account()
            if account is not None:  # the access token was rejected: force a refresh next time
                account.access_expires_at = None
                self._s.commit()
            raise NotConnectedError(
                "Google rejected the saved sign-in. Please try again."
            ) from error
        except g.GoogleAPIError as error:
            if error.status == 404:
                raise ValidationFailure("Google Calendar has no such event or calendar.") from error
            raise IntegrationError(f"Google Calendar error: {error.message}") from error

    # ------------------------------------------------------------ time helpers

    def _tz(self):
        return safe_zone(timezone_for(self._s, self._user_id))

    def _range(self, start: str | None, end: str | None) -> tuple[str, str]:
        tz = self._tz()
        now = self._now().astimezone(tz)
        if start:
            start_dt, _ = parse_due(start, tz)
        else:
            start_dt = datetime.combine(now.date(), datetime.min.time(), tzinfo=tz).astimezone(UTC)
        if end:
            end_dt, has_time = parse_due(end, tz)
            if not has_time:
                end_dt += timedelta(days=1)  # a date means "through the end of that day"
        else:
            end_dt = start_dt + timedelta(days=7)
        if end_dt <= start_dt:
            raise ValidationFailure("The end must be after the start.")
        return start_dt.isoformat().replace("+00:00", "Z"), end_dt.isoformat().replace(
            "+00:00", "Z"
        )

    def _times(self, start: str, end: str | None, all_day: bool | None) -> tuple[dict, dict]:
        """Google ``start`` / ``end`` objects from ISO input (in the user's time zone)."""
        tz = self._tz()
        start_dt, has_time = parse_due(start, tz)
        if all_day is None:
            all_day = not has_time
        if all_day:
            first = start_dt.astimezone(tz).date()
            if end:
                last_dt, _ = parse_due(end, tz)
                last = last_dt.astimezone(tz).date()
            else:
                last = first
            if last < first:
                raise ValidationFailure("The end must not be before the start.")
            return (
                {"date": first.isoformat()},
                {"date": (last + timedelta(days=1)).isoformat()},  # Google's end is exclusive
            )
        end_dt = parse_due(end, tz)[0] if end else start_dt + timedelta(hours=1)
        if end_dt <= start_dt:
            raise ValidationFailure("The end must be after the start.")
        zone = str(tz)
        return (
            {"dateTime": start_dt.astimezone(tz).isoformat(), "timeZone": zone},
            {"dateTime": end_dt.astimezone(tz).isoformat(), "timeZone": zone},
        )

    def describe_when(self, event: dict) -> str:
        """Human text like "Fri, Oct 3, 2:00 PM–3:00 PM" for confirmations."""
        tz = self._tz()
        try:
            if event.get("all_day"):
                return date.fromisoformat(event["start"]).strftime("%a, %b %d") + " (all day)"
            start = datetime.fromisoformat(event["start"]).astimezone(tz)
            end = datetime.fromisoformat(event["end"]).astimezone(tz)
            return f"{start.strftime('%a, %b %d, %I:%M %p')}–{end.strftime('%I:%M %p')}"
        except (KeyError, TypeError, ValueError):
            return str(event.get("start") or "")

    # ------------------------------------------------------------ operations

    def list_calendars(self) -> list[dict]:
        items = self._call(lambda api: api.calendar_list())
        return [
            {
                "id": c.get("id"),
                "name": c.get("summaryOverride") or c.get("summary") or c.get("id"),
                "primary": bool(c.get("primary")),
                "timezone": c.get("timeZone"),
                "access_role": c.get("accessRole"),
            }
            for c in items
        ]

    def list_events(
        self,
        start: str | None = None,
        end: str | None = None,
        *,
        calendar_id: str | None = None,
        query: str | None = None,
        max_results: int = 25,
    ) -> list[dict]:
        calendar_id = check_calendar_id(calendar_id)
        time_min, time_max = self._range(start, end)
        items = self._call(
            lambda api: api.events_list(
                calendar_id,
                time_min=time_min,
                time_max=time_max,
                query=query,
                max_results=max(1, min(max_results, 100)),
            )
        )
        return [normalize_event(e, calendar_id) for e in items if e.get("status") != "cancelled"]

    def get_event(self, event_id: str, calendar_id: str | None = None) -> dict:
        calendar_id = check_calendar_id(calendar_id)
        check_event_id(event_id)
        return normalize_event(
            self._call(lambda api: api.event_get(calendar_id, event_id)), calendar_id
        )

    def create_event(
        self,
        title: str,
        start: str,
        end: str | None = None,
        *,
        all_day: bool | None = None,
        location: str = "",
        description: str = "",
        calendar_id: str | None = None,
    ) -> dict:
        calendar_id = check_calendar_id(calendar_id)
        if not (title or "").strip():
            raise ValidationFailure("An event needs a title.")
        start_obj, end_obj = self._times(start, end, all_day)
        body = {"summary": title.strip()[:1024], "start": start_obj, "end": end_obj}
        if location:
            body["location"] = location[:1024]
        if description:
            body["description"] = description[:8000]
        return normalize_event(
            self._call(lambda api: api.event_insert(calendar_id, body)), calendar_id
        )

    def update_event(
        self,
        event_id: str,
        *,
        title: str | None = None,
        start: str | None = None,
        end: str | None = None,
        location: str | None = None,
        description: str | None = None,
        calendar_id: str | None = None,
    ) -> dict:
        calendar_id = check_calendar_id(calendar_id)
        check_event_id(event_id)
        body: dict = {}
        if title is not None:
            if not title.strip():
                raise ValidationFailure("An event needs a title.")
            body["summary"] = title.strip()[:1024]
        if location is not None:
            body["location"] = location[:1024]
        if description is not None:
            body["description"] = description[:8000]
        if start is not None or end is not None:
            existing = self.get_event(event_id, calendar_id)
            if start is None:
                start = existing["start"]
            if end is None and not existing["all_day"]:
                # Moving an event keeps its length.
                tz = self._tz()
                old_start = datetime.fromisoformat(existing["start"])
                old_end = datetime.fromisoformat(existing["end"])
                new_start, _ = parse_due(start, tz)
                end = (new_start + (old_end - old_start)).astimezone(tz).isoformat()
            body["start"], body["end"] = self._times(
                start, end, None if existing["all_day"] else False
            )
        if not body:
            raise ValidationFailure("Nothing to change.")
        return normalize_event(
            self._call(lambda api: api.event_patch(calendar_id, event_id, body)), calendar_id
        )

    def delete_event(self, event_id: str, calendar_id: str | None = None) -> None:
        calendar_id = check_calendar_id(calendar_id)
        check_event_id(event_id)
        self._call(lambda api: api.event_delete(calendar_id, event_id))


def complete_authorization(
    session: Session,
    settings: Settings,
    http: Any,
    state: str,
    code: str,
    *,
    now: Callable[[], datetime] = utcnow,
) -> CalendarAccount:
    """Finish the OAuth flow from Google's redirect. The user is identified by ``state``."""
    if not settings.calendar_configured:
        raise NotConnectedError(NOT_CONFIGURED)
    row = session.scalar(
        select(OAuthState).where(OAuthState.state_hash == _hash_state(state or ""))
    )
    current = now()
    if row is None or row.used_at is not None or row.expires_at < current:
        raise ValidationFailure("This sign-in link is invalid or has expired. Please start again.")
    row.used_at = current  # single use, even if the exchange below fails
    session.commit()

    box = SecretBox(settings.encryption_key)
    oauth = g.GoogleOAuth(
        http, settings.google_client_id, settings.google_client_secret, redirect_uri(settings)
    )
    try:
        tokens = oauth.exchange_code(code, box.decrypt(row.verifier_enc))
    except g.GoogleAPIError as error:
        raise IntegrationError(f"Google refused the sign-in: {error.message}") from error
    if not tokens.refresh_token:
        raise IntegrationError(
            "Google did not grant offline access. Remove KYVON from your Google account's "
            "connected apps and try again."
        )

    email = ""
    try:
        for entry in g.GoogleCalendarAPI(http, tokens.access_token).calendar_list():
            if entry.get("primary"):
                email = entry.get("id", "")
    except g.GoogleAPIError:
        pass  # the email is only for display

    account = session.scalar(
        select(CalendarAccount).where(
            CalendarAccount.user_id == row.user_id, CalendarAccount.provider == "google"
        )
    )
    if account is None:
        account = CalendarAccount(user_id=row.user_id, provider="google", refresh_token_enc="")
        session.add(account)
    account.account_email = email
    account.refresh_token_enc = box.encrypt(tokens.refresh_token)
    account.access_token_enc = box.encrypt(tokens.access_token)
    account.access_expires_at = current + timedelta(seconds=tokens.expires_in)
    account.scopes = tokens.scope
    session.commit()
    return account
