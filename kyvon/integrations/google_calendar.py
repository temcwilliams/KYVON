"""Google OAuth 2.0 (authorization code + PKCE) and the Google Calendar REST API.

HTTP goes through an injected object with ``request(method, url, **kwargs)`` (a
``requests.Session`` in production), so tests use a fake and never reach Google. Every URL
is a fixed Google endpoint; nothing here fetches an address chosen by the model or a user.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://www.googleapis.com/calendar/v3"
# Least privilege: manage events, and read the list of calendars. Nothing else.
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
)
TIMEOUT = 15


class GoogleAPIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class GoogleAuthError(GoogleAPIError):
    """The token is invalid or was revoked; the user must connect again."""


@dataclass
class TokenSet:
    access_token: str
    expires_in: int
    refresh_token: str | None = None
    scope: str = ""


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_url(
    client_id: str, redirect_uri: str, state: str, code_challenge: str
) -> str:
    return (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",  # we need a refresh token
                "prompt": "consent",  # ...and Google only sends one after explicit consent
            }
        )
    )


def _error_message(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = body.get("error")
    if isinstance(error, dict):
        return error.get("message") or f"HTTP {response.status_code}"
    return (
        body.get("error_description")
        or (error if isinstance(error, str) else "")
        or (f"HTTP {response.status_code}")
    )


class GoogleOAuth:
    def __init__(self, http: Any, client_id: str, client_secret: str, redirect_uri: str):
        self._http = http
        self._id = client_id
        self._secret = client_secret
        self._redirect = redirect_uri

    def _token_request(self, data: dict) -> TokenSet:
        response = self._http.request(
            "POST",
            TOKEN_URL,
            data={**data, "client_id": self._id, "client_secret": self._secret},
            timeout=TIMEOUT,
            allow_redirects=False,
        )
        if response.status_code >= 400:
            message = _error_message(response)
            try:
                code = str(response.json().get("error", ""))
            except ValueError:
                code = ""
            if code == "invalid_grant":  # revoked, expired or already-used
                raise GoogleAuthError(response.status_code, message)
            raise GoogleAPIError(response.status_code, message)
        body = response.json()
        return TokenSet(
            access_token=body["access_token"],
            expires_in=int(body.get("expires_in", 3600)),
            refresh_token=body.get("refresh_token"),
            scope=body.get("scope", ""),
        )

    def exchange_code(self, code: str, verifier: str) -> TokenSet:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": self._redirect,
            }
        )

    def refresh(self, refresh_token: str) -> TokenSet:
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def revoke(self, token: str) -> None:
        try:
            self._http.request(
                "POST", REVOKE_URL, data={"token": token}, timeout=TIMEOUT, allow_redirects=False
            )
        except Exception:  # best effort: the local copy is deleted regardless
            pass


class GoogleCalendarAPI:
    def __init__(self, http: Any, access_token: str):
        self._http = http
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def _call(self, method: str, path: str, **kwargs) -> Any:
        response = self._http.request(
            method,
            API_BASE + path,
            headers=self._headers,
            timeout=TIMEOUT,
            allow_redirects=False,
            **kwargs,
        )
        if response.status_code == 401:
            raise GoogleAuthError(401, "Google rejected the access token.")
        if response.status_code >= 400:
            raise GoogleAPIError(response.status_code, _error_message(response))
        if response.status_code == 204 or not response.text:
            return None
        return response.json()

    @staticmethod
    def _cal(calendar_id: str) -> str:
        return quote(calendar_id, safe="@")

    def calendar_list(self) -> list[dict]:
        return self._call("GET", "/users/me/calendarList", params={"minAccessRole": "reader"}).get(
            "items", []
        )

    def events_list(
        self,
        calendar_id: str,
        *,
        time_min: str,
        time_max: str,
        query: str | None = None,
        max_results: int = 25,
    ) -> list[dict]:
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        if query:
            params["q"] = query
        return self._call("GET", f"/calendars/{self._cal(calendar_id)}/events", params=params).get(
            "items", []
        )

    def event_get(self, calendar_id: str, event_id: str) -> dict:
        return self._call("GET", f"/calendars/{self._cal(calendar_id)}/events/{quote(event_id)}")

    def event_insert(self, calendar_id: str, body: dict) -> dict:
        return self._call("POST", f"/calendars/{self._cal(calendar_id)}/events", json=body)

    def event_patch(self, calendar_id: str, event_id: str, body: dict) -> dict:
        return self._call(
            "PATCH", f"/calendars/{self._cal(calendar_id)}/events/{quote(event_id)}", json=body
        )

    def event_delete(self, calendar_id: str, event_id: str) -> None:
        self._call("DELETE", f"/calendars/{self._cal(calendar_id)}/events/{quote(event_id)}")
