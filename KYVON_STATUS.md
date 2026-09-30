# KYVON — Project Status Report

Generated 2026-09-29 from a read-only inspection. No code was modified and the app was not run. Statements marked *(inferred)* come from reading the code, not from running it.

## TL;DR

KYVON is a small (~1,700 lines, 3 commits) single-file Flask app with a browser front end. It does chat via Groq, keyword-triggered "remember" memory, keyword-triggered web search, and GPS-based location and weather. **Tasks, calendar, authentication, an iPhone/iPad client, and deployment do not exist.** The README describes tasks and calendar as goals only. The code is a prototype, and there is not yet a foundation to build those features on.

---

## Repository

```
app.py               657 lines  Flask backend (all logic)
templates/index.html 150 lines  Single page UI
static/app.js        568 lines  Front-end logic
static/style.css     312 lines  Styling (HUD look)
requirements.txt       flask, groq, python-dotenv, requests
tasks.json             stray file: ["My favorite color is blue"]
README.md              2 lines
.vscode/settings.json  editor config
```

No `.gitignore`, tests, CI, Dockerfile, Procfile, `.env` or `.env.example`. Remote: GitHub `temcwilliams/jarvis-assistant` (branch `main` only).

**Git history**

| Commit | Date | Summary |
|---|---|---|
| 8c73865 | 2026-09-03 | Initial commit (README) |
| 93cee14 | 2026-09-15 | "Update JARVIS web version": all app code added in one commit |
| 8763d0a | 2026-09-20 | Rename JARVIS to KYVON (incomplete, see below) |

---

## Current architecture

```
Browser (iPad Safari / any browser)
   │  fetch JSON
   ▼
Flask app.py  (0.0.0.0:8080, debug off, dev server)
   ├─ GET  /                 → templates/index.html
   ├─ GET  /api/status       → diagnostics (makes a live Groq call each time)
   ├─ GET  /api/memory       → list memories
   ├─ POST /api/environment  → lat/lon → Nominatim (reverse geocode) + Open-Meteo (weather)
   └─ POST /api/chat         → routes by message prefix:
         "remember …" / "remember that …" / "don't forget that …" / "keep in mind that …"
                                → save to data/kyvon_memory.json (no LLM)
         "web …"                → Groq model groq/compound (built-in web search)
         anything else          → Groq openai/gpt-oss-120b with system prompt
                                  (last 20 memories + environment text injected)
Storage: data/kyvon_memory.json (last 100 entries), data/kyvon_errors.log
```

Notes:
- The environment (location and weather) text is built in the browser and sent with each chat request. The server trusts it and puts it into the prompt.
- Routing is by string prefix, not by LLM intent detection or tool calling.
- Every chat is **stateless**. Only the current message is sent to the model, with no conversation history, so it cannot handle follow-up questions.
- Module-level global `memory` is shared across requests, with no locking.

## Current functionality

| Area | Status |
|---|---|
| Chat with LLM (Groq, `openai/gpt-oss-120b`) | Implemented |
| Persona/system prompt | Implemented |
| Memory: save by "remember …" and view via MEMORY button | Implemented (keyword-only) |
| Memory: use in replies (last 20 injected in the prompt) | Implemented |
| Web research (`web <query>` → `groq/compound`) | Implemented |
| Location: browser geolocation, Nominatim reverse geocode | Implemented |
| Weather: Open-Meteo (°F/mph) | Implemented |
| Local time | Partial: uses the time string Open-Meteo returns, with no server clock |
| Voice input (webkitSpeechRecognition) | Implemented (browser-dependent) |
| Diagnostics button | Implemented |
| Error logging to file | Implemented |
| **Tasks** | **Not implemented** (`tasks.json` is an unused stray file) |
| **Calendar** | **Not implemented** (no Google/Apple/CalDAV code) |
| **Authentication** | **Not implemented** |
| **Text-to-speech / spoken replies** | Not implemented |
| **iPhone/iPad native client / Shortcuts bridge** | Not implemented |
| Repair log (`REPAIR_LOG`, `"diagnosed": True`) | Vestigial: defined but never used |

## What works *(inferred from code; not executed)*

- The app should start when `GROQ_API_KEY` is set and the dependencies are installed. It creates `data/`.
- Chat, memory, web search, and location/weather flows are coherent end to end between `app.js` and `app.py`.
- Failures in the location and weather calls are caught and logged, and the UI degrades to "LOCATION ERROR/DENIED".
- Front-end output goes through `escapeHtml`, so chat rendering is not an XSS vector.
- The memory file loads defensively (a corrupt file yields an empty list).

## What is broken or wrong

1. **Incomplete rename.** The page `<title>`, the header brand, and the server console banner still say "J.A.R.V.I.S.". The directory, repo name, and `tasks.json`/`data` naming are still "jarvis". The API key error message references "GitHub Codespaces".
2. **Geolocation on iPad requires HTTPS.** iOS Safari blocks `navigator.geolocation` on plain `http://` non-localhost origins. Unless the app is served through HTTPS (for example the Codespaces forwarded URL), location will always fail. Voice input has the same secure-context limitation.
3. **`/api/status` calls the paid/rate-limited Groq API on every page load and every SYSTEM click.** It also reports `online: false` if the Groq call fails, though the UI ignores that flag.
4. **"Remember" handling has a bug.** `"remember "` matches first, so `"remember that X"` is stored as `"that X"`, and the later `remember that` / `keep in mind that` phrase list is only partially reachable. An empty payload falls through to the LLM.
5. **No conversation history.** Each message is independent, so follow-ups like "what about tomorrow?" have no context.
6. **`python-dotenv` is listed but never imported.** There is no `.env` loading, so `GROQ_API_KEY` must be exported in the shell environment or a Codespaces secret.
7. **Unhandled input paths.** `data["message"].strip()` crashes with a 500 if `message` is not a string. `/api/environment` returns raw exception text to the client.
8. **The `data/` folder is created relative to the current working directory**, so running the app from another directory creates a second memory store.
9. **Prompt injection surface.** The client-supplied `environment` string is inserted into the system prompt unvalidated, and web results are returned unfiltered.
10. **The system prompt promises "Access real local time information"**, but no dedicated clock or timezone source exists beyond the weather response.

## What is incomplete

- Task creation and management (the core README promise)
- Calendar events/dates (the core README promise)
- Any authentication or per-user data
- Real intent understanding (tool/function calling instead of prefix keywords)
- Persistent conversation history
- A mobile/iPhone client, PWA manifest and icons, or an Apple Shortcuts integration
- Deployment, process management, HTTPS
- Tests
- Real README (setup, run, configuration)

## Technical debt

- All backend logic is in one 657-line file, with no blueprints or modules.
- Heavy vertical whitespace and duplicated boilerplate (JSON responses, memory-saved responses).
- Unpinned dependencies; `requirements.txt` has no versions and no trailing newline.
- Flask dev server bound to `0.0.0.0` with no auth. Anyone who can reach the port can use your Groq quota and read your memories.
- `debug=False` is correct, but there is no production server (gunicorn/waitress).
- Global mutable state (`memory`), and non-atomic JSON file writes that can corrupt on concurrent requests.
- Data is stored as flat JSON files. That is fine for now but will not scale to tasks, calendar, and users.
- No `.gitignore`: `data/` (personal memories and error logs), `__pycache__`, and any future `.env` could be committed accidentally.
- Weather-code map is rebuilt inside the function on every call and is missing several codes (56/57, 66/67, 77, 85/86).
- No request timeouts or retries on Groq calls; no rate limiting.
- Stray files: `tasks.json`, the unused `REPAIR_LOG`, and the unused `python-dotenv`.
- The front end uses inline `onclick` handlers, has no framework or build step, and does not sanitize markdown (the model's output is shown as plain text, so markdown formatting is not rendered).

## Important dependencies

- **Python:** Flask, groq (SDK), requests (python-dotenv is declared but unused).
- **External services:**
  - Groq API, models `openai/gpt-oss-120b` and `groq/compound` (needs `GROQ_API_KEY`).
  - OpenStreetMap Nominatim (reverse geocoding; usage policy requires a valid User-Agent and light use).
  - Open-Meteo (free, no key).
- **Browser APIs:** Geolocation, webkitSpeechRecognition. Both need a secure context on iOS.

## Configuration / secrets

The only configuration is the environment variable `GROQ_API_KEY`. The app refuses to start without it. No `.env` files or committed secrets were found in the repository or its history (secret values were not read or printed at any point).

## Deployment setup

There is **no deployment configuration in the repo**. Clues (the "GitHub Codespaces secret" error text, port 8080, `0.0.0.0` binding) suggest it is run **manually inside a GitHub Codespace** with `python app.py` and accessed through the Codespaces forwarded port URL. This is *(inferred)*, so please confirm. Consequences: the app only runs while the Codespace is running, and the URL and visibility settings of the forwarded port control who can reach it.

To run locally:
```bash
pip install -r requirements.txt
export GROQ_API_KEY=...   # set in your shell, not committed
python app.py             # http://localhost:8080
```

## iPhone / iPad client

There is no native client. The iPad connects by **opening the Flask app's URL in Safari**. The page has `apple-mobile-web-app-capable` and a viewport tag, so it can be added to the Home Screen, but there is no manifest, icon, service worker, or offline behavior. The location error text explicitly refers to "your iPad browser settings". The iPhone is not specifically addressed (the CSS has one `max-width: 600px` breakpoint). There is no Apple Shortcuts bridge; the system prompt only mentions that one would be required.

---

## Recommended development sequence

1. **Housekeeping** (small, safe): add `.gitignore` (`data/`, `.env`, `__pycache__`), finish the KYVON rename (title, brand, banner, README), delete `tasks.json`, write a real README, pin dependency versions, and use `python-dotenv` or remove it.
2. **Decide deployment target and get HTTPS working**: this blocks reliable iPad location and voice, and makes the app reachable when your Codespace is off. Options: a small VPS/Fly.io/Render, or a home server with Tailscale. Use gunicorn/waitress.
3. **Add authentication** before adding personal data (tasks, calendar). A single-user login or token is enough to start. Protect all `/api/*` routes.
4. **Refactor the backend lightly**: split `app.py` into modules (config, memory, environment, ai, routes) and move persistence to SQLite. Do this before adding features so they don't pile into one file.
5. **Conversation history and cleaner chat**: send the recent turns, render markdown, and make `/api/status` cheap (no LLM call).
6. **Tasks**: CRUD API, UI panel, and storage in SQLite.
7. **Replace prefix keywords with LLM tool/function calling** (remember, create task, search web, get weather), and keep the "never claim actions you didn't perform" rule by reporting real tool results.
8. **Calendar**: choose a provider (Google Calendar OAuth vs. Apple/CalDAV), and store the OAuth tokens securely.
9. **iPhone/iPad polish**: PWA manifest and icons, Home Screen install, spoken replies (speechSynthesis), and optionally Apple Shortcuts endpoints for device actions.
10. **Tests and CI** for the routing, memory, and tool functions.

## Questions to confirm

1. Is it really run from GitHub Codespaces today, and how do you reach it from the iPad?
2. Google Calendar or Apple Calendar?
3. Is the app just for you (single user), or will others use it?
4. Do you want a PWA, or a native iOS app later?
