# Graph Report - jarvis-assistant  (2026-10-09)

## Corpus Check
- 218 files · ~120,435 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 13 file(s) not represented in the graph (top: (none) 4, .service 2, .example 1)

## Summary
- 3340 nodes · 9676 edges · 151 communities (128 shown, 23 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 721 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `eacff5d4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- models/__init__.py
- test_observability.py
- View
- test_environment_service.py
- APIClient
- pytest
- ToolArgs
- test_settings.py
- test_hermes.py
- test_hosted_accounts.py
- chat.js
- Base
- test_tool_executor.py
- AppModel
- h
- kyvon/__init__.py
- email_service.py
- LLMResponse
- test_conversations.py
- test_memory_system.py
- test_agents.py
- test_tasks.py
- CalendarService
- alembic
- Settings
- test_llm.py
- ToolRegistry
- KeychainTokenStore
- cli.py
- test_chat_service.py
- test_automation.py
- test_builtin_tools.py
- ToolError
- ChatService
- services
- Models.swift
- ApiError
- ToolExecutor
- VoiceController
- MemoryService
- test_operations.py
- get_session
- test_memory_db.py
- test_auth.py
- ChatStreamEvent
- test_usage_quotas.py
- create_app
- login_required
- schemas.py
- post
- api/errors.py
- auth_service.py
- webpush.py
- test_pwa.py
- calendar_service.py
- UsageGate
- test_calendar.py
- test_security.py
- FileLogseqGraph
- KYVON — Target Architecture
- llm/base.py
- ToolCall
- memory_rules.py
- AgentRunner
- ConversationService
- main.js
- APIError
- test_voice.py
- settings.js
- Session
- TaskService
- conftest.py
- google_calendar.py
- register_error_handlers
- Scheduler
- Views.swift
- automations.py
- next_run
- speech.py
- voice.js
- AutomationService
- User
- re
- run_checks
- automation_tools.py
- task_tools.py
- As built
- AgentRun
- NotificationService
- KYVON - Project Status
- test_cli.py
- connection.js
- tasks.js
- integrations/logseq.py
- ValidationFailure
- agent_tools.py
- SecretBox
- App Store submission pack
- KYVON for iPhone and iPad
- Controls
- memories.py
- conversations.py
- AutomationRunner
- GoogleCalendarAPI
- context_builder.py
- KYVON privacy policy
- WebPushError
- register
- FakeGoogle
- FakeHTTPResponse
- notifications.js
- Deploying KYVON
- register
- smoke_test.py
- call
- call
- api
- KYVON — Roadmap
- WebPushSender
- FailureThrottle
- make_icons.py
- KYVON_STATUS.md
- parse_json
- PushSubscription
- export_user_data
- test_deploy_files.py
- FakeLLM
- Clock
- call
- legal/README.md
- register
- RateLimiter
- fixture
- flow
- .build
- KYVON
- parametrize
- verify_login
- _clean_schema
- docker-entrypoint.sh
- Package.swift
- test_callback_needs_no_session_cookie

## God Nodes (most connected - your core abstractions)
1. `ValidationFailure` - 115 edges
2. `login_required()` - 98 edges
3. `LLMResponse` - 94 edges
4. `NotFoundError` - 74 edges
5. `AppModel` - 68 edges
6. `api()` - 67 edges
7. `Settings` - 66 edges
8. `get_session()` - 65 edges
9. `services()` - 61 edges
10. `APIClient` - 59 edges

## Surprising Connections (you probably didn't know these)
- `8. AI and personal data (Guideline 5.1.2(i))` --references--> `ConsentView`  [INFERRED]
  docs/appstore/APP_STORE_SUBMISSION.md → ios/Sources/KYVONApp/Views.swift
- `6. Operating it` --references--> `doctor()`  [INFERRED]
  docs/DEPLOYMENT.md → kyvon/cli.py
- `Production deployment (existing Ubuntu VM)` --references--> `doctor()`  [INFERRED]
  KYVON_STATUS.md → kyvon/cli.py
- `Agents` --references--> `delegate_to_agent()`  [INFERRED]
  docs/ARCHITECTURE.md → kyvon/tools/builtin/agent_tools.py
- `Residual risks and limits (honest list)` --references--> `delegate_to_agent()`  [INFERRED]
  docs/SECURITY.md → kyvon/tools/builtin/agent_tools.py

## Import Cycles
- None detected.

## Communities (151 total, 23 thin omitted)

### Community 0 - "models/__init__.py"
Cohesion: 0.09
Nodes (10): UTCDateTime, utcnow(), AutomationRun, BillingEvent, Subscription, ToolRun, UsageEvent, EmailToken (+2 more)

### Community 1 - "test_observability.py"
Cohesion: 0.05
Nodes (29): configure_logging(), ContextFilter, JsonFormatter, TextFormatter, ErrorRecord, database_status(), list_errors(), record_error() (+21 more)

### Community 2 - "View"
Cohesion: 0.05
Nodes (45): ApprovalCard, .body, ChatTab, .body, ChatView, .body, .composer, ComposerField (+37 more)

### Community 3 - "test_environment_service.py"
Cohesion: 0.07
Nodes (33): forward_geocode(), reverse_geocode(), fetch_current_weather(), EnvironmentService, ErrorLog, app(), env_service(), test_environment_weather_failure_is_500() (+25 more)

### Community 4 - "APIClient"
Cohesion: 0.12
Nodes (4): APIClient, InMemoryTokenStore, KYVONKitTests, MockTransport

### Community 5 - "pytest"
Cohesion: 0.06
Nodes (29): build_graph(), NotFoundError, test_unknown_conversation_is_not_found(), test_delete_removes_messages(), test_rename_and_validation(), kb(), lapp(), lclient() (+21 more)

### Community 6 - "ToolArgs"
Cohesion: 0.07
Nodes (34): ToolArgs, CreateEventArgs, DeleteEventArgs, ListEventsArgs, NoArgs, UpdateEventArgs, ArchiveArgs, DeleteArgs (+26 more)

### Community 7 - "test_settings.py"
Cohesion: 0.08
Nodes (32): connected_services(), make_chat_service(), allowed_tool_names(), disabled_tool_prefixes(), get_settings(), render_profile(), reset_settings(), _stored() (+24 more)

### Community 8 - "test_hermes.py"
Cohesion: 0.08
Nodes (30): build_hermes(), validate_url(), FakeHermesHTTP, client_for(), hclient(), hermes_app(), hermes_http(), hermes_http_messages() (+22 more)

### Community 9 - "test_hosted_accounts.py"
Cohesion: 0.08
Nodes (41): make_app(), test_create_app_creates_data_dir(), test_unconfigured_server_hides_calendar_tools_and_refuses_to_connect(), _cli(), hosted(), hosted_settings(), http(), login() (+33 more)

### Community 10 - "chat.js"
Cohesion: 0.11
Nodes (38): ApiError, csrfToken(), onUnauthorized(), stream(), cancelReply(), input, newConversation(), openConversation() (+30 more)

### Community 11 - "Base"
Cohesion: 0.07
Nodes (27): alembic_config(), Base, make_engine(), make_session_factory(), upgrade_database(), Conversation, Memory, _refresh_content_hash() (+19 more)

### Community 12 - "test_tool_executor.py"
Cohesion: 0.09
Nodes (38): OAuth (Google Calendar), ConflictError, call(), executor(), origin(), runs(), session(), state() (+30 more)

### Community 13 - "AppModel"
Cohesion: 0.11
Nodes (4): AppModel, .hasConsented, Array, .body

### Community 14 - "h"
Cohesion: 0.13
Nodes (38): errorItem(), list(), load(), mount(), render(), row(), section(), DAYS (+30 more)

### Community 15 - "kyvon/__init__.py"
Cohesion: 0.07
Nodes (6): _NoCookies, _outbound_session(), HermesConfigError, main(), render(), rows()

### Community 16 - "email_service.py"
Cohesion: 0.06
Nodes (16): account_deleted_message(), already_registered_message(), _build(), build_email_sender(), ConsoleEmailSender, deliver(), EmailError, EmailSender (+8 more)

### Community 17 - "LLMResponse"
Cohesion: 0.14
Nodes (34): LLMResponse, test_tool_call_cap(), ask(), call(), test_bad_journal_day(), test_declining_writes_nothing(), test_notes_with_hostile_instructions_are_only_data(), test_oversized_and_malformed_arguments_are_rejected_before_running() (+26 more)

### Community 18 - "test_conversations.py"
Cohesion: 0.08
Nodes (26): estimate_tokens(), title_from_text(), build(), chat(), fill(), parse_sse(), svc(), test_api_failed_llm_call_is_reported_and_recorded() (+18 more)

### Community 19 - "test_memory_system.py"
Cohesion: 0.08
Nodes (23): stem(), tokens(), add_all(), chat(), clock(), memory(), ranked(), test_chat_duplicate_remember_is_reported() (+15 more)

### Community 20 - "test_agents.py"
Cohesion: 0.09
Nodes (29): ask(), call(), connect_calendar(), make_run(), run_agent(), session(), svc(), test_a_finished_run_is_not_rerun() (+21 more)

### Community 21 - "test_tasks.py"
Cohesion: 0.08
Nodes (15): _add_months(), is_overdue(), next_occurrence(), parse_due(), to_local_iso(), tasks(), test_api_validation(), test_create_validation() (+7 more)

### Community 22 - "CalendarService"
Cohesion: 0.12
Nodes (9): CalendarService, check_calendar_id(), check_event_id(), complete_authorization(), _hash_state(), normalize_event(), redirect_uri(), IntegrationError (+1 more)

### Community 23 - "alembic"
Cohesion: 0.05
Nodes (12): upgrade(), upgrade(), upgrade(), upgrade(), upgrade(), upgrade(), upgrade(), upgrade() (+4 more)

### Community 24 - "Settings"
Cohesion: 0.11
Nodes (18): ConfigError, Settings, test_api_key_optional_when_not_required(), test_bad_env_name(), test_bad_log_level(), test_bad_port(), test_bad_token_ttl(), test_blank_api_key_raises() (+10 more)

### Community 25 - "test_llm.py"
Cohesion: 0.10
Nodes (18): StreamEvent, GroqClient, _usage(), build_system_prompt(), _chunk(), FakeGroq, StreamingGroq, test_chat_returns_tool_calls_and_usage() (+10 more)

### Community 26 - "ToolRegistry"
Cohesion: 0.10
Nodes (11): RiskLevel, Tool, register(), build_registry(), ToolRegistry, decorator(), registry(), toolerr() (+3 more)

### Community 27 - "KeychainTokenStore"
Cohesion: 0.07
Nodes (9): KYVONMain, .body, LocationProvider, .hasToken, KeychainError, KeychainTokenStore, .baseQuery, TokenStore (+1 more)

### Community 28 - "cli.py"
Cohesion: 0.14
Nodes (17): Command execution and filesystem, backup(), create_user(), db_upgrade(), doctor(), generate_key_command(), generate_vapid_keys_command(), import_memories() (+9 more)

### Community 29 - "test_chat_service.py"
Cohesion: 0.09
Nodes (21): ChatFailed, ChatInputError, chat(), llm(), make_chat(), build(), rows(), test_blank_message_rejected() (+13 more)

### Community 30 - "test_automation.py"
Cohesion: 0.14
Nodes (29): local(), make(), notes(), run(), test_a_crashing_run_replans_the_automation(), test_create_computes_first_run_in_the_automations_timezone(), test_daily_next_run(), test_disabled_between_claim_and_run_is_cancelled() (+21 more)

### Community 31 - "test_builtin_tools.py"
Cohesion: 0.11
Nodes (29): conversation(), make_conversation(), run_tool(), session(), stranger(), svc(), test_conversation_delete_requires_confirmation_and_names_the_target(), test_conversation_list_search_and_read() (+21 more)

### Community 32 - "ToolError"
Cohesion: 0.11
Nodes (30): 8. Tool system design, Phase 4 — Tools  ✅, ToolContext, ToolError, _escape_like(), register(), conversation_archive(), conversation_delete() (+22 more)

### Community 33 - "ChatService"
Cohesion: 0.13
Nodes (6): How a chat turn works, Message, ChatService, TurnResult, ContextBuilder, serialize_message()

### Community 34 - "services"
Cohesion: 0.14
Nodes (23): serialize_agent_run(), services(), cancel_run(), get_run(), list_agents(), list_runs(), start_run(), callback() (+15 more)

### Community 35 - "Models.swift"
Cohesion: 0.18
Nodes (24): Phase, needsConsent, needsServer, signedIn, signedOut, APIUser, ChatMessage, Conversation (+16 more)

### Community 36 - "ApiError"
Cohesion: 0.11
Nodes (23): wrapper(), enforce_ip_rate(), ApiError, change_password(), delete(), export(), profile(), usage() (+15 more)

### Community 37 - "ToolExecutor"
Cohesion: 0.17
Nodes (4): CallOrigin, _jsonable(), ToolExecutor, ToolOutcome

### Community 38 - "VoiceController"
Cohesion: 0.09
Nodes (9): AVFoundation, CoreLocation, AppDelegate, PushRegistrar, VoiceController, KYVONApp, KYVONKit, UIKit (+1 more)

### Community 39 - "MemoryService"
Cohesion: 0.13
Nodes (11): Scored, MemoryService, SaveResult, test_relevant_memory_is_injected_and_irrelevant_is_not(), test_remember_that_no_longer_keeps_the_word_that(), test_same_timestamp_ordering_stable(), test_scoped_to_user(), test_cap_retires_least_important_oldest_first() (+3 more)

### Community 40 - "test_operations.py"
Cohesion: 0.12
Nodes (19): all_setting_names(), cli(), db_rows(), make_backup(), test_a_real_gunicorn_process_starts_serves_and_stops_gracefully(), test_backup_creates_a_verified_private_copy(), test_backup_only_touches_its_own_files(), test_backup_refuses_non_sqlite_databases() (+11 more)

### Community 41 - "get_session"
Cohesion: 0.13
Nodes (18): admin_required(), _bearer_token(), _check_origin(), get_session(), wrapper(), automation_runs(), errors(), _int() (+10 more)

### Community 42 - "test_memory_db.py"
Cohesion: 0.11
Nodes (17): _has_date(), import_json_memories(), ImportResult, MemoryImportError, clock(), memory(), test_import_does_not_touch_file(), test_import_is_idempotent() (+9 more)

### Community 43 - "test_auth.py"
Cohesion: 0.10
Nodes (18): cookie_login(), login(), session(), test_bad_credentials_share_one_message(), test_bad_username_rejected(), test_cookie_get_works_without_csrf(), test_cookie_login_sets_httponly_token_and_hides_it_from_body(), test_cookie_logout_clears_cookies() (+10 more)

### Community 44 - "ChatStreamEvent"
Cohesion: 0.11
Nodes (16): Foundation, ChatEventDecoder, ChatStreamEvent, delta, done, error, start, tool (+8 more)

### Community 45 - "test_usage_quotas.py"
Cohesion: 0.20
Nodes (24): Usage, test_usage_and_model_metadata_saved(), make_verified(), login(), build(), chat(), events(), small() (+16 more)

### Community 46 - "create_app"
Cohesion: 0.07
Nodes (8): close_session(), create_app(), persist_error(), Services, EnvironmentCache, test_db_upgrade_creates_schema(), migrated(), test_startup_logs_a_feature_summary_without_secrets()

### Community 47 - "login_required"
Cohesion: 0.17
Nodes (22): Phase 5 — Personal Assistant  ✅ (tasks + Google Calendar; Google faked in tests), login_required(), calendars(), connect(), create_event(), delete_event(), disconnect(), get_event() (+14 more)

### Community 48 - "schemas.py"
Cohesion: 0.13
Nodes (24): AgentRunCreate, ApnsRegister, AutomationCreate, AutomationUpdate, CalendarEventCreate, CalendarEventUpdate, ChangePasswordRequest, ConversationCreate (+16 more)

### Community 49 - "post"
Cohesion: 0.10
Nodes (12): post(), test_chat_non_string_message_is_400(), test_chat_rejects_blank_message(), test_chat_rejects_oversized_message(), test_chat_requires_message(), test_client_cannot_inject_prompt_text_via_the_body(), test_environment_bad_input_is_400(), test_llm_failure_is_500_and_logged() (+4 more)

### Community 50 - "api/errors.py"
Cohesion: 0.12
Nodes (14): build_chat_service(), enforce_rate(), ChatRequest, EnvironmentRequest, chat(), chat_stream(), generate(), _sse() (+6 more)

### Community 51 - "auth_service.py"
Cohesion: 0.14
Nodes (15): signup(), AuthError, burn_hash(), change_password(), create_owner(), create_user(), find_by_email(), find_user() (+7 more)

### Community 52 - "webpush.py"
Cohesion: 0.11
Nodes (14): b64d(), b64e(), encrypt_payload(), generate_vapid_keys(), _private_from_raw(), vapid_authorization(), test_a_failing_push_never_breaks_the_reminder(), test_encrypted_payload_round_trips_with_the_receivers_key() (+6 more)

### Community 53 - "test_pwa.py"
Cohesion: 0.10
Nodes (11): service_worker(), render_service_worker(), shell_files(), version(), png_size(), session(), test_apple_and_favicon_icons(), test_manifest_icons_exist_with_the_declared_size() (+3 more)

### Community 54 - "calendar_service.py"
Cohesion: 0.14
Nodes (9): CalendarAccount, OAuthState, kmh(), mm(), render_environment(), safe_zone(), to_celsius(), timezone_for() (+1 more)

### Community 55 - "UsageGate"
Cohesion: 0.12
Nodes (10): entitled_plan(), EmailNotVerified, limits_for(), month_bounds(), plan_for(), summary(), top_users(), totals() (+2 more)

### Community 56 - "test_calendar.py"
Cohesion: 0.09
Nodes (5): calendar_service(), events(), test_events_are_normalised(), test_list_events_defaults_and_ranges(), test_service_level_validation_without_http()

### Community 57 - "test_security.py"
Cohesion: 0.11
Nodes (12): all_rules(), cookie_client(), fill(), test_a_revoked_or_garbage_token_is_rejected_everywhere(), test_cookie_sessions_need_a_csrf_token_on_every_unsafe_route(), test_cross_origin_cookie_requests_are_refused_even_with_a_valid_csrf_token(), test_every_non_public_route_requires_authentication(), test_extra_trusted_origins_are_configurable() (+4 more)

### Community 58 - "FileLogseqGraph"
Cohesion: 0.26
Nodes (3): FileLogseqGraph, to_blocks(), test_symlinked_pages_folder_is_refused()

### Community 59 - "KYVON — Target Architecture"
Cohesion: 0.10
Nodes (20): 10. Frontend / client architecture, 11. Configuration / secrets strategy, 13. Deployment strategy, 14. Migration plan from the current prototype, 15. Recommended implementation phases, 1. Proposed directory structure, 2. Backend modules and responsibilities, 3. API endpoints (`/api/v1`) (+12 more)

### Community 60 - "llm/base.py"
Cohesion: 0.10
Nodes (5): 12. Testing strategy, LLMClient, overall_ok(), run_diagnostics(), Summarizer

### Community 61 - "ToolCall"
Cohesion: 0.11
Nodes (7): HermesBackend, ToolCall, LLMError, OpenAICompatClient, test_usage_summary(), call(), test_hostile_web_content_cannot_cause_any_consequential_action()

### Community 62 - "memory_rules.py"
Cohesion: 0.13
Nodes (14): content_hash(), looks_like_secret(), normalize(), parse_memory_shortcut(), parse_recall_request(), validate_memory_text(), test_non_shortcuts(), test_shortcuts_recognized() (+6 more)

### Community 63 - "AgentRunner"
Cohesion: 0.17
Nodes (4): AgentDefinition, register_agent(), AgentRunner, test_hermes_agents_need_hermes()

### Community 64 - "ConversationService"
Cohesion: 0.17
Nodes (5): clean_title(), ConversationService, test_refresh_after_interrupted_stream_shows_saved_state(), test_user_title_is_never_overwritten(), test_isolation_between_users()

### Community 65 - "main.js"
Cohesion: 0.18
Nodes (20): setUnauthorizedHandler(), currentUser(), errorBox, form, hideLogin(), initLogin(), logout(), overlay (+12 more)

### Community 66 - "APIError"
Cohesion: 0.17
Nodes (5): APIError, .errorDescription, .isUnauthorized, HTTPTransport, URLSessionTransport

### Community 67 - "test_voice.py"
Cohesion: 0.16
Nodes (12): sniff_audio(), test_bad_uploads(), test_filename_sent_onward_comes_from_the_bytes_not_the_client(), test_formats_and_codec_parameters(), test_missing_field_and_bad_language(), test_provider_failure_is_a_502_and_logged(), test_size_limit(), test_sniffing_recognises_audio_containers() (+4 more)

### Community 68 - "settings.js"
Cohesion: 0.25
Nodes (19): canPromptInstall(), disablePush(), enablePush(), isIOS(), isStandalone(), listeners, onInstallStateChange(), promptInstall() (+11 more)

### Community 69 - "Session"
Cohesion: 0.16
Nodes (13): _send_verification(), consume_email_token(), hash_token(), issue_email_token(), list_tokens(), reset_password(), resolve_token(), revoke_all_tokens() (+5 more)

### Community 70 - "TaskService"
Cohesion: 0.21
Nodes (5): Task, clean_title(), priority_value(), TaskService, test_isolation_between_users()

### Community 71 - "conftest.py"
Cohesion: 0.15
Nodes (11): anon_client(), app(), client(), fake_environment(), fake_llm(), fake_stt(), fast_password_hashing(), no_network() (+3 more)

### Community 72 - "google_calendar.py"
Cohesion: 0.16
Nodes (6): _error_message(), GoogleAPIError, GoogleAuthError, GoogleOAuth, pkce_pair(), TokenSet

### Community 73 - "register_error_handlers"
Cohesion: 0.17
Nodes (14): error_response(), register_error_handlers(), _api_error(), _conflict(), _http_error(), _integration_error(), _not_connected(), _not_found() (+6 more)

### Community 74 - "Scheduler"
Cohesion: 0.16
Nodes (3): Scheduler, test_scheduler_survives_a_failing_tick(), test_two_schedulers_cannot_run_the_same_occurrence()

### Community 75 - "Views.swift"
Cohesion: 0.18
Nodes (12): ConsentView, .body, DeviceInfo, .name, LoginView, .body, MainView, RootView (+4 more)

### Community 76 - "automations.py"
Cohesion: 0.22
Nodes (15): automation_runs(), _automations(), create_automation(), delete_automation(), delete_notification(), get_automation(), list_automations(), list_notifications() (+7 more)

### Community 77 - "next_run"
Cohesion: 0.18
Nodes (11): describe(), _local(), next_run(), parse_time(), validate_schedule(), test_api_rejects_bad_automations(), test_describe(), test_invalid_schedules() (+3 more)

### Community 78 - "speech.py"
Cohesion: 0.14
Nodes (7): GroqWhisper, SpeechError, SpeechToText, TextToSpeech, FakeGroqAudio, test_whisper_adapter(), test_whisper_adapter_hides_provider_details()

### Community 79 - "voice.js"
Cohesion: 0.27
Nodes (17): cancelSpeech(), cancelVoice(), chunks, config, finishRecording(), initVoice(), input, micButton (+9 more)

### Community 80 - "AutomationService"
Cohesion: 0.21
Nodes (5): Automation, AutomationService, test_background_thread_lifecycle(), test_isolation(), test_per_user_limit()

### Community 81 - "User"
Cohesion: 0.21
Nodes (14): User, issue_token(), test_api_isolation_and_auth(), test_memories_are_scoped_to_the_logged_in_user(), test_revoke_cannot_touch_other_users_token(), test_api_isolation_and_auth(), test_other_users_do_not_share_the_connection(), test_api_conversation_isolation_between_users() (+6 more)

### Community 82 - "re"
Cohesion: 0.16
Nodes (11): test_html_is_accessible_enough(), test_imported_names_are_exported(), test_no_unsafe_dom_patterns(), test_relative_imports_resolve(), test_static_element_ids_used_by_scripts_exist_in_html(), test_file_writes_are_limited_to_known_modules(), test_frontend_only_navigates_to_google_and_never_builds_urls_from_data(), test_no_tool_lets_the_model_approve_its_own_actions_or_fetch_urls() (+3 more)

### Community 83 - "run_checks"
Cohesion: 0.18
Nodes (12): Check, _hosted_checks(), run_checks(), add(), factory(), test_backup_works_while_the_database_is_in_use(), test_doctor_checks_the_env_file_permissions(), test_doctor_flags_production_problems() (+4 more)

### Community 84 - "automation_tools.py"
Cohesion: 0.24
Nodes (14): _automation_label(), build_schedule(), _create_summary(), CreateArgs, EnableArgs, _guard(), IdArgs, ListArgs (+6 more)

### Community 85 - "task_tools.py"
Cohesion: 0.24
Nodes (14): CreateArgs, _guard(), ListArgs, register(), task_complete(), task_create(), task_delete(), task_list() (+6 more)

### Community 86 - "As built"
Cohesion: 0.14
Nodes (6): Agents, As built, Differences from the original design, Layout, Tool system, MemoryRetriever

### Community 88 - "NotificationService"
Cohesion: 0.19
Nodes (3): Notification, NotificationService, test_api_notifications_flow()

### Community 89 - "KYVON - Project Status"
Cohesion: 0.13
Nodes (15): Agents, Hermes, Logseq, automation, PWA, native client, voice, API, Architecture, At a glance, Completed phases, Credentials and setup you still need to do, Future ideas that are genuinely not built, Known limitations (not hidden) (+7 more)

### Community 90 - "test_cli.py"
Cohesion: 0.23
Nodes (13): run(), runner(), test_create_user_prompts_with_confirmation(), test_create_user_rejects_weak_password(), test_create_user_via_stdin(), test_import_memories_command(), test_import_missing_file_is_clean_error(), test_import_requires_owner() (+5 more)

### Community 91 - "connection.js"
Cohesion: 0.27
Nodes (12): apply(), banner, initConnection(), probe(), reportNetworkFailure(), scheduleProbe(), sendButton, setOnline() (+4 more)

### Community 92 - "tasks.js"
Cohesion: 0.32
Nodes (14): dueText(), edit(), fields(), load(), localInputValue(), mount(), note(), payload() (+6 more)

### Community 93 - "integrations/logseq.py"
Cohesion: 0.16
Nodes (3): Hit, KnowledgeBase, Page

### Community 94 - "ValidationFailure"
Cohesion: 0.21
Nodes (8): clean_page_name(), ValidationFailure, validate_category(), validate_importance(), test_api_rejects_bad_input(), test_bad_names_are_rejected(), test_good_names(), test_category_and_importance_validation()

### Community 95 - "agent_tools.py"
Cohesion: 0.24
Nodes (7): ToolResult, available_agents(), _catalogue(), DelegateArgs, register(), delegate_to_agent(), _spec()

### Community 96 - "SecretBox"
Cohesion: 0.21
Nodes (4): CryptoError, SecretBox, test_callback_connects_encrypts_tokens_and_verifies_pkce(), test_expired_access_token_is_refreshed_and_saved()

### Community 97 - "App Store submission pack"
Cohesion: 0.18
Nodes (12): 10. Pre-submission checklist, 1. What you must do outside the code, 2. The biggest review risk: a reviewer needs a server, 3. Listing text (draft), 4. App Privacy ("nutrition label") answers, 5. Export compliance (encryption), 6. Age rating, 7. Account deletion (Guideline 5.1.1(v)) (+4 more)

### Community 98 - "KYVON for iPhone and iPad"
Cohesion: 0.17
Nodes (10): KYVON for iPhone and iPad: design, Not in the app yet, Principles, Structure, Build it, Compatibility and App Store, KYVON for iPhone and iPad, Security notes (+2 more)

### Community 99 - "Controls"
Cohesion: 0.17
Nodes (12): Authentication and sessions, Controls, CSRF and cross-origin, Data isolation, How to re-run the checks, Input validation and limits, KYVON security review, Prompt injection and the tool system (+4 more)

### Community 100 - "memories.py"
Cohesion: 0.32
Nodes (9): build_memory_service(), categories(), create_memory(), delete_memory(), get_memory(), _int_arg(), list_memories(), update_memory() (+1 more)

### Community 101 - "conversations.py"
Cohesion: 0.35
Nodes (9): create_conversation(), delete_conversation(), get_conversation(), _int_arg(), list_conversations(), list_messages(), _service(), update_conversation() (+1 more)

### Community 105 - "KYVON privacy policy"
Cohesion: 0.18
Nodes (11): Changes, Children, Contact, Keeping data safe, KYVON privacy policy, Services your server may use, What KYVON is, What the app handles, and where it goes (+3 more)

### Community 106 - "WebPushError"
Cohesion: 0.22
Nodes (6): is_allowed_endpoint(), WebPushError, test_other_addresses_are_refused(), test_push_errors(), test_real_push_services_are_allowed(), test_subscribe_validation()

### Community 107 - "register"
Cohesion: 0.36
Nodes (10): _event_label(), _guard(), register(), calendar_create_event(), calendar_delete_event(), calendar_list_calendars(), calendar_list_events(), calendar_update_event() (+2 more)

### Community 108 - "FakeGoogle"
Cohesion: 0.25
Nodes (4): FakeGoogle, instant(), start_of(), test_complete_authorization_needs_configuration()

### Community 109 - "FakeHTTPResponse"
Cohesion: 0.27
Nodes (7): FakeHTTPResponse, FakePushHTTP, sender(), test_sender_posts_an_encrypted_message_with_vapid(), test_sender_refuses_bad_endpoints_without_sending(), test_service_delivers_and_prunes_dead_subscriptions(), request()

### Community 110 - "notifications.js"
Cohesion: 0.36
Nodes (10): badge, bell, load(), mount(), onVisible(), refreshBadge(), render(), setBadge() (+2 more)

### Community 111 - "Deploying KYVON"
Cohesion: 0.20
Nodes (10): 0. What is in a release, 1. First upgrade from the prototype (or a fresh install), 2. HTTPS with Cloudflare Tunnel, 3. Optional features (each is off until configured), 4. Backups, 5. Upgrading later, 6. Operating it, 7. Rollback (+2 more)

### Community 112 - "register"
Cohesion: 0.47
Nodes (10): _graph(), _guard(), register(), logseq_append(), logseq_create_page(), logseq_journal_append(), logseq_list_pages(), logseq_read_page() (+2 more)

### Community 113 - "smoke_test.py"
Cohesion: 0.27
Nodes (3): check(), Client, main()

### Community 114 - "call"
Cohesion: 0.42
Nodes (10): approve(), ask(), call(), test_bad_schedules_fail_after_approval_without_creating_anything(), test_daily_morning_and_evening_examples(), test_every_sunday_summarise_my_week(), test_intervals_below_the_floor_are_rejected_at_the_schema(), test_list_toggle_and_delete_tools() (+2 more)

### Community 115 - "call"
Cohesion: 0.38
Nodes (10): ask(), call(), test_add_dentist_friday_needs_confirmation_then_creates(), test_calendar_tool_when_not_connected_explains_itself(), test_calendar_write_errors_after_confirmation_are_reported(), test_delete_that_event_uses_the_previous_turns_results(), test_malicious_event_text_cannot_trigger_actions(), test_move_my_3pm_meeting_to_4pm() (+2 more)

### Community 116 - "api"
Cohesion: 0.58
Nodes (9): api(), connect(), disconnect(), load(), loadEvents(), mount(), note(), renderConnected() (+1 more)

### Community 117 - "KYVON — Roadmap"
Cohesion: 0.22
Nodes (9): Delivered scope, mapped to the later phase numbering, Genuinely not implemented (future ideas), KYVON — Roadmap, Open questions (needed before the noted phase), Phase 2 — Conversational Intelligence  ✅, Phase 3 — Memory  ✅ (lexical retrieval; no embeddings), Phase 6 — Agents  ✅ (also Hermes and Logseq, see below), Phase 7 — iPhone/iPad  ✅ PWA; native client source written but NOT compiled (+1 more)

### Community 118 - "WebPushSender"
Cohesion: 0.28
Nodes (3): WebPushSender, build_push(), PushService

### Community 119 - "FailureThrottle"
Cohesion: 0.33
Nodes (4): FailureThrottle, test_lockout_after_repeated_failures(), test_success_resets_failure_count(), test_throttle_window_expires()

### Community 120 - "make_icons.py"
Cohesion: 0.33
Nodes (3): draw(), main(), png()

### Community 123 - "parse_json"
Cohesion: 0.36
Nodes (5): parse_json(), public_key(), register_apns(), subscribe(), unsubscribe()

### Community 124 - "PushSubscription"
Cohesion: 0.29
Nodes (4): PushSubscription, register_apns(), subscribe_web(), unsubscribe()

### Community 125 - "export_user_data"
Cohesion: 0.29
Nodes (4): delete_account(), export_user_data(), rows(), _row()

### Community 126 - "test_deploy_files.py"
Cohesion: 0.36
Nodes (3): test_gunicorn_defaults_keep_port_8080(), test_gunicorn_port_override(), test_wsgi_exposes_app()

### Community 128 - "Clock"
Cohesion: 0.25
Nodes (4): Clock, in_chicago(), session(), svc()

### Community 129 - "call"
Cohesion: 0.48
Nodes (7): call(), chat(), test_complete_task_via_tool_and_recurring_follow_up(), test_natural_language_task_creation_through_the_model(), test_task_delete_needs_confirmation(), test_task_tools_are_scoped_to_the_user(), test_task_tools_reject_bad_input_without_side_effects()

### Community 131 - "register"
Cohesion: 0.40
Nodes (4): register(), recent_errors(), system_status(), _server_wide()

### Community 133 - "fixture"
Cohesion: 0.33
Nodes (5): connected(), google(), in_chicago(), session(), svc()

### Community 134 - "flow"
Cohesion: 0.33
Nodes (5): flow(), test_bad_authorization_code(), test_missing_refresh_token_is_reported(), test_reconnecting_replaces_the_stored_account(), test_state_only_connects_the_user_who_started_the_flow()

### Community 136 - "KYVON"
Cohesion: 0.40
Nodes (5): API, Development, KYVON, Run it locally, What it does

### Community 137 - "parametrize"
Cohesion: 0.50
Nodes (3): test_create_validation(), test_event_ids_are_validated_before_any_request(), test_unknown_state_is_rejected()

## Knowledge Gaps
- **33 isolated node(s):** `KYVONApp`, `PackageDescription`, `needsConsent`, `needsServer`, `signedOut` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 930 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `14. Migration plan from the current prototype` connect `KYVON — Target Architecture` to `ToolError`, `create_app`?**
  _High betweenness centrality (0.137) - this node is a cross-community bridge._
- **Are the 43 inferred relationships involving `ValidationFailure` (e.g. with `AgentRunner` and `register_error_handlers()`) actually correct?**
  _`ValidationFailure` has 43 INFERRED edges - model-reasoned connections that need verification._
- **What connects `KYVONApp`, `PackageDescription`, `needsConsent` to the rest of the system?**
  _33 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `models/__init__.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09193438140806562 - nodes in this community are weakly interconnected._
- **Why does `create_app()` connect `create_app` to `test_observability.py`, `test_environment_service.py`, `RateLimiter`, `pytest`, `test_hermes.py`, `test_hosted_accounts.py`, `Base`, `kyvon/__init__.py`, `email_service.py`, `Settings`, `test_llm.py`, `ToolRegistry`, `ToolExecutor`, `test_operations.py`, `test_pwa.py`, `KYVON — Target Architecture`, `llm/base.py`, `AgentRunner`, `conftest.py`, `register_error_handlers`, `Scheduler`, `speech.py`, `run_checks`, `AgentRun`, `test_cli.py`, `AutomationRunner`, `WebPushSender`, `FailureThrottle`?**
  _High betweenness centrality (0.135) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `LLMResponse` (e.g. with `GroqClient` and `OpenAICompatClient`) actually correct?**
  _`LLMResponse` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_observability.py` be split into smaller, more focused modules?**
  _Cohesion score 0.04864864864864865 - nodes in this community are weakly interconnected._