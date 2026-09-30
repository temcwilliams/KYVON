# KYVON — Roadmap

Companion to [ARCHITECTURE.md](ARCHITECTURE.md). Each phase ends with a working app. Phases are sequential unless noted. Nothing here starts until you approve it.

**Out of scope until you say otherwise:** changing the model provider, integrating Hermes, and building the native iOS app.

---

## Phase 1 — Foundation

**Goal:** a clean, safe base with no new user-visible features.

- `.gitignore`, `.env.example`, pinned dependencies, README rewrite, and the finished KYVON rename
- Lint/format (ruff) and pytest, with CI on pull requests
- Characterization tests that pin the current prototype's behavior
- `kyvon/` package: app factory, typed config, logging, and the uniform error envelope
- Existing logic moved into modules (memory, environment, llm, chat) with no behavior change
- SQLAlchemy + Alembic, and the `users`, `memories` and `conversations`/`messages` tables. One-time import of `kyvon_memory.json`
- Authentication: the create-user CLI, login, per-device tokens, and protected routes. The web client gets a login screen
- `/health` and a cheap `/status`, and legacy `/api/*` aliases kept
- Dockerfile and gunicorn entry point

**Exit criteria:** the old chat, memory, web search and location/weather flows work on the new structure, tests pass in CI, no secrets are in the repo, and nothing is reachable without login.

## Phase 2 — Conversational Intelligence

**Goal:** KYVON holds a real conversation.

- Conversation persistence, with a list, open, rename and delete UI
- Context assembly with a token budget, conversation summaries for older turns, and server-side current time and timezone
- Server-built environment block (no client-supplied prompt text)
- Streaming responses (SSE), safe markdown rendering, and better error messages
- Prompt and persona moved into versioned files under `llm/prompts.py`

**Exit criteria:** follow-up questions work, history survives restarts and devices, and long chats stay within token limits.

## Phase 3 — Memory

**Goal:** memory that is useful, visible and controllable.

- Memory CRUD API and a UI (view, edit, delete, categories)
- A `remember` mechanism that isn't keyword-only (the old prefixes stay as shortcuts)
- Relevance-based retrieval (FTS/keyword + recency), replacing "last 20"
- Proposed-memory approval flow, and `last_used_at` tracking
- Decision point: are embeddings needed? Add them only if keyword retrieval falls short

**Exit criteria:** KYVON recalls relevant facts without stuffing every memory into the prompt, and the user can inspect and remove anything it knows.

## Phase 4 — Tools

**Goal:** the tool architecture, with the existing capabilities converted first.

- Tool registry, schemas, `ToolContext`, the tool-call loop with iteration caps, and `tool_runs` logging
- Convert existing capabilities to tools: `remember`/`search_memories`/`forget`, `web_search`, `get_weather`, `get_current_time`
- Confirmation mechanism for side-effecting tools (API and UI)
- Tool activity shown in the chat UI, and a `GET /tools` endpoint
- Tests using the FakeLLM to script tool calls

**Exit criteria:** KYVON never reports an action it didn't perform, since each claim maps to a logged tool result.

## Phase 5 — Personal Assistant

**Goal:** the README's promise of tasks and calendar.

- Tasks: model, API, UI panel, and tools (`create_task`, `list_tasks`, `complete_task`), including due dates and natural-language dates
- Calendar: choose a provider (Google Calendar first, subject to your answer), OAuth flow with encrypted tokens, read events, create events with confirmation
- Daily briefing (weather, events, tasks) as an on-demand feature
- Timezone handling and user settings

**Exit criteria:** "add a task to call the dentist Friday" and "what's on my calendar tomorrow?" both work end to end, with the calendar write requiring confirmation.

## Phase 6 — Agents

**Goal:** bounded multi-step work.

- Agent definitions (prompt, tool subset, budget), the runner, and `agent_runs` persistence with cancel and timeout
- Background execution (thread pool first)
- The `delegate` tool. Initial agents: Researcher, Planner
- Run-history view in the UI. Hermes and Logseq are evaluated here as an agent backend and an integration, **only after a separate approval**.

**Exit criteria:** a multi-step research or planning goal completes, is fully traceable step by step, and stays within its budget and permissions.

## Phase 7 — iPhone/iPad

**Goal:** a great mobile experience on the same API.

- PWA manifest, icons, Home Screen install, and responsive layouts for iPhone and iPad
- Spoken replies (`speechSynthesis`), and improved voice input
- Apple Shortcuts endpoints and documentation for device actions
- OpenAPI spec published, and per-device token management UI
- Push notifications for reminders (web push, where supported)
- Decision point: native SwiftUI app, and only if the PWA limits you. It would consume the existing API unchanged.

**Exit criteria:** you use KYVON daily from your iPad and iPhone with working location, voice and notifications.

## Phase 8 — Automation and advanced capabilities

**Goal:** proactive and integrated behavior.

- Scheduled jobs (reminders, morning briefing, recurring tasks) with a scheduler
- Logseq integration (notes search, journal append, memory import)
- Hermes integration as a provider or agent backend
- Optional server-side speech-to-text and text-to-speech
- Additional integrations (email, notes, smart home) via the tool interface, each with the confirmation rules
- Observability: usage and cost dashboards, an audit log viewer, and backup/restore tooling
- Optional Postgres migration and multi-user support

**Exit criteria:** defined per feature at the time the phase is planned.

---

## Open questions (needed before the noted phase)

| Question | Needed by |
|---|---|
| Where will KYVON be hosted long term (Codespaces, Fly/Render, home server + Tailscale)? | Phase 1 |
| Single user only, or eventually others? | Phase 1 |
| Google Calendar or Apple/iCloud Calendar? | Phase 5 |
| PWA only, or a native app later? | Phase 7 |
| Logseq: which graph/setup, and local file access or API? | Phase 8 |
| Hermes: what is it in your setup (model, agent framework, or service)? | Phase 6/8 |
