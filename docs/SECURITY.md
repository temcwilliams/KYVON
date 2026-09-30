# KYVON security review

KYVON is an AI assistant that can act (change tasks, calendar entries, notes, settings). That
makes two things the centre of the design: **the model is never trusted to authorise anything**, and
**everything the model reads from the outside world is treated as data, not instructions.**

This document is the result of the Phase 15 review. Each claim below is backed by automated tests
(mostly `tests/test_security.py`) or is listed under *Residual risks*.

## Threat model

| Who / what | Trusted? | Notes |
|---|---|---|
| The owner (signed in) | Yes | Single-user. Their content (messages, notes) is theirs to write. |
| The language model | **No** | It can be fooled by text it reads. It can only *ask* for tools; KYVON decides. |
| Web pages, search results, calendar text, Logseq notes, e-mail-like content | **No** | Read through tools; labelled untrusted; never obeyed. |
| Hermes (optional) | **No** | Same as any model: allow-listed read-only tools, everything logged. |
| Anyone on the internet | No | Everything except health checks and the login endpoint needs a device token. |
| Third-party services (Groq, Google, Open-Meteo, Nominatim, push services) | Partly | Called only at fixed addresses (see SSRF). |

## Controls

### Authentication and sessions
- Single owner, created from the command line. **No public registration** (no such route; tested).
- Passwords: scrypt; minimum length 10; login gives the same error for a wrong password and an
  unknown user, and does equal work for both (no user enumeration by message or timing).
- Failed-login throttle (5 in 15 minutes per address+username) and a per-user request limit.
- Per-device 256-bit bearer tokens, **stored only as SHA-256**, expiring (30 days by default),
  individually revocable, all revoked on password change. Token values never appear in any API
  response after login, in logs, or in the database.
- Web sessions use an `HttpOnly`, `SameSite=Strict`, `Secure` (production) cookie. JavaScript never
  sees the session token, and nothing is kept in `localStorage`/`sessionStorage` (tested).
- **Every** route except health, login, the OAuth callback and static files requires authentication;
  this is checked by walking the app's URL map (`test_every_non_public_route_requires_authentication`).

### CSRF and cross-origin
- Cookie-authenticated unsafe requests need a double-submit CSRF token **and** an `Origin` that is
  this site (host, `KYVON_PUBLIC_URL`, or `KYVON_TRUSTED_ORIGINS`). Both are tested on every unsafe
  route automatically. Bearer-token requests are not CSRF-prone and are exempt.
- No CORS headers are ever sent; there is no cross-origin API access.
- Headers: strict CSP (no inline script/style, no eval, `object-src 'none'`, `frame-ancestors
  'none'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`, `Permissions-Policy`,
  HSTS when cookies are `Secure`, `Cache-Control: no-store` on all API responses.

### Input validation and limits
- Every request body is validated by a strict Pydantic schema; IDs are integers in the route; JSON
  bodies are capped at 1 MB (uploads at 10 MB, checked by content, not just declared type).
- Rate limits: chat 30/min, all other API calls 300/min, voice 20/min (per user), with `Retry-After`.
- SQL is only issued through SQLAlchemy; `LIKE` searches escape wildcards.

### Prompt injection and the tool system
- **The model can only act through registered tools**, each with a strict schema (unknown fields are
  rejected), a risk class, a timeout and an audit row. There is no shell, no code execution, no
  file access and no "fetch this URL" tool (tested by scanning the source and the tool schemas).
- **Anything with an external effect or that deletes something waits for the user's approval** in the
  UI/API; the model has no tool to approve. The approval text is written by KYVON's code, not by the
  model. Approvals expire, can only be given once (atomic claim), only by their owner, and stored
  arguments are re-validated at execution.
- Model-initiated memory writes, settings changes and standing automations also need approval, and
  free-text instructions (`assistant_notes`) can only be written by the user, so an injected
  instruction cannot make itself persistent.
- Tool results from outside (web, notes, calendar, other conversations) are labelled
  `untrusted`, size-limited, and the standing prompt says to treat them as data. A regression test
  simulates a poisoned search result that makes the model attempt seven harmful actions at once:
  four are queued for approval (nothing happens until approved), the unknown tool is rejected, and
  the rest are cut off by the per-round call limit.
- Agents get a fixed allow-list of tools; they cannot start agents; they have step, tool-call and
  time limits; approvals they trigger are queued for the user. Hermes is limited the same way.
- The assistant cannot read secrets: keys are never placed in prompts, and secret-looking text is
  refused as a memory or setting.

### Command execution and filesystem
- No `subprocess`, `os.system`, `eval`, `exec`, `pickle` or similar anywhere in the package
  (a test greps for them). Only two modules write files: the error log and the Logseq sandbox.
- Logseq: only `pages/` and `journals/` Markdown files; validated names; symlinks are never followed;
  sizes bounded; atomic writes; **no delete operation**; overwrites keep a backup.

### SSRF and malicious URLs
- Outbound HTTP goes only to fixed hosts (Groq, Google, Open-Meteo, Nominatim) plus two
  owner-configured/validated destinations: the Hermes URL (http(s), no credentials, private hosts
  unless explicitly allowed) and Web Push endpoints (https, allow-listed to Apple/Google/Mozilla/
  Microsoft push hosts; without this the subscribe API would let a client make the server call
  arbitrary URLs).
- Outbound calls never follow redirects, never use proxy/netrc settings, and never keep cookies.
  A test enumerates which modules may make HTTP requests.
- URLs in model or tool text are shown as plain text. The client never builds a link or navigates
  from data, except to Google's sign-in address (checked).

### OAuth (Google Calendar)
- Authorization code flow with PKCE (S256), least-privilege scopes, a random single-use `state`
  (stored hashed, 10-minute lifetime, bound to the user who started it). The refresh/access tokens
  are encrypted at rest (Fernet); the client secret never reaches the browser. Revoked grants
  disconnect cleanly; disconnecting revokes at Google. Redirects go only to `/`.

### Data isolation
- Every table with user data carries `user_id`; every service query filters by it. Each resource
  has tests where a second user gets 404 for read, edit, delete and action endpoints.

### Secrets and logging privacy
- Secrets live only in the environment / `.env` (not in git; `.env.example` has placeholders).
  Settings hide secrets in `repr`; error responses, logs, error records and audit rows are passed
  through a redactor (keys, bearer tokens, passwords).
- Logs contain method, path, status, timing and a request id: never bodies, query strings, message
  text or credentials. Error records store redacted text.
- Dependencies are pinned to ranges and scanned with `pip-audit` (no known vulnerabilities at review
  time) and `bandit` (findings reviewed; see `pyproject.toml`).

## Residual risks and limits (honest list)

1. **Behind the Cloudflare Tunnel every request comes from 127.0.0.1**, so the login throttle is
   effectively per username: five wrong guesses lock that name for 15 minutes for everyone,
   including the owner (a restart or `set-password` clears it). Trade-off: no trust in spoofable
   `X-Forwarded-For` headers.
2. **Rate limits and the login throttle are in process memory**; KYVON runs one worker by design.
   With several workers each would count separately.
3. **A poisoned tool result can still influence what the model *says*** (it may repeat false
   information or mislead you in prose). Defences stop it from *acting*; they cannot stop it lying.
   Read approval prompts carefully: they show exactly what will happen.
4. **`delegate_to_agent` and task creation do not need approval** (they change only KYVON's own,
   reversible data). A fooled model could create junk tasks or run a research agent. Deleting or
   external effects still need approval.
5. **Hermes**: if the configured endpoint is itself an autonomous agent with shell/file tools, those
   are outside KYVON's control. Point it at a model endpoint, never at anything with access to the VM.
6. **Web Push and the iOS client are untested against real services**; APNs sending is not
   implemented. The native app was not compiled.
7. Uploaded audio is sent to Groq for transcription; conversations go to the configured model
   provider. That is inherent in using hosted models.
8. No two-factor authentication or passkeys; the owner's password and device tokens are the trust
   root. Use a long password and revoke devices you no longer use.
9. Message content is stored unencrypted in SQLite (file permissions and full-disk encryption are
   the protection). Only OAuth tokens are encrypted at rest. Back up and protect `data/`.
10. Automatic language-model titles/summaries send conversation text to the model provider too.

## How to re-run the checks

```bash
.venv/bin/pytest tests/test_security.py       # the regression suite
.venv/bin/bandit -c pyproject.toml -r kyvon   # static analysis
.venv/bin/pip-audit -r requirements.txt       # dependency advisories
```
