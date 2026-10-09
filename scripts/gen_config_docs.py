"""Generate docs/CONFIGURATION.md from the settings tables so the docs cannot drift.

python scripts/gen_config_docs.py          # rewrite the file
python scripts/gen_config_docs.py --check  # exit 1 if it is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kyvon import config  # noqa: E402

TARGET = ROOT / "docs" / "CONFIGURATION.md"

# Variables that are read outside the tables in config.py.
SPECIAL = [
    ("GROQ_API_KEY", "(required)", "Groq API key. Secret.", "secret"),
    (
        "KYVON_ENV",
        "development",
        "`development`, `testing` or `production`. Production marks cookies Secure and logs JSON.",
        "",
    ),
    ("LOG_LEVEL", "INFO", "DEBUG, INFO, WARNING, ERROR or CRITICAL.", ""),
    (
        "KYVON_DATA_DIR",
        "data",
        "Folder for the database, error log and legacy memory file (relative to the working directory).",
        "",
    ),
    ("DATABASE_URL", "sqlite:///<data dir>/kyvon.db", "SQLAlchemy URL.", ""),
    ("KYVON_COOKIE_SECURE", "true in production", "Mark sign-in cookies Secure (needs HTTPS).", ""),
    ("KYVON_LOG_JSON", "true in production", "One JSON object per log line.", ""),
]
SECRETS = {
    "KYVON_ENCRYPTION_KEY",
    "GOOGLE_CLIENT_SECRET",
    "KYVON_HERMES_API_KEY",
    "KYVON_VAPID_PRIVATE_KEY",
    "GROQ_API_KEY",
    "KYVON_SMTP_PASSWORD",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
}
NOTES = {
    "PORT": "Port gunicorn / `python app.py` listens on. Keep 8080 for the Cloudflare Tunnel.",
    "KYVON_HOST": "Bind address.",
    "KYVON_MODEL": "Chat model (Groq).",
    "KYVON_WEB_MODEL": "Web research model (Groq).",
    "KYVON_STT_MODEL": "Speech-to-text model (Groq Whisper).",
    "KYVON_PUBLIC_URL": "How browsers reach KYVON (used for the Google OAuth redirect and trusted origin).",
    "KYVON_ENCRYPTION_KEY": "Encrypts stored OAuth tokens. `flask --app wsgi kyvon generate-key`. **Losing it disconnects Google Calendar.**",
    "GOOGLE_CLIENT_ID": "Google OAuth client id (enables Calendar).",
    "GOOGLE_CLIENT_SECRET": "Google OAuth client secret.",
    "KYVON_HERMES_URL": "OpenAI-compatible Hermes endpoint (enables the Hermes agent). Private hosts only unless allowed.",
    "KYVON_HERMES_API_KEY": "Bearer key for Hermes, if it needs one.",
    "KYVON_HERMES_MODEL": "Model name sent to Hermes.",
    "KYVON_HERMES_ALLOW_REMOTE": "Allow a Hermes URL outside the private network.",
    "KYVON_LOGSEQ_DIR": "Logseq graph folder (enables Logseq tools).",
    "KYVON_VAPID_PUBLIC_KEY": "Web Push public key. `flask --app wsgi kyvon generate-vapid-keys`.",
    "KYVON_VAPID_PRIVATE_KEY": "Web Push private key. Secret.",
    "KYVON_VAPID_SUBJECT": "Contact for push services, e.g. `mailto:you@example.com`.",
    "KYVON_TRUSTED_ORIGINS": "Comma-separated extra hosts accepted as Origin for cookie sessions.",
    "KYVON_SCHEDULER": "Run the automation scheduler inside the web process.",
    "KYVON_AUTO_TITLE_LLM": "Let the model write conversation titles.",
    "KYVON_MODE": "`personal` (one owner, the default) or `hosted` (many users with email accounts, quotas and billing).",
    "KYVON_SIGNUP_OPEN": "Hosted mode only: let new people sign up. Stays closed until you set this.",
    "KYVON_PROXY_HOPS": "Number of trusted reverse proxies in front of the app, so the real client IP is used for limits.",
    "KYVON_EMAIL_FROM": "Sender address for verification and reset emails (hosted mode).",
    "KYVON_SMTP_HOST": "SMTP server for outgoing email (hosted mode).",
    "KYVON_SMTP_PORT": "SMTP port.",
    "KYVON_SMTP_USER": "SMTP username.",
    "KYVON_SMTP_PASSWORD": "SMTP password. Secret.",
    "KYVON_SMTP_STARTTLS": "Use STARTTLS on the SMTP connection.",
    "KYVON_VERIFY_TTL_HOURS": "How long an email verification link stays valid.",
    "KYVON_RESET_TTL_MINUTES": "How long a password reset link stays valid.",
    "KYVON_AUTH_RATE_PER_MINUTE": "Sign-up, password reset and verification requests allowed per client IP per minute.",
    "STRIPE_SECRET_KEY": "Stripe secret key (hosted mode billing). Secret.",
    "STRIPE_WEBHOOK_SECRET": "Signing secret of the Stripe webhook endpoint (`/api/v1/billing/webhook`). Secret.",
    "STRIPE_PRICE_ID": "Stripe Price id of the paid subscription.",
    "KYVON_PRICE_LABEL": "Text shown beside the upgrade button, such as `$9 / month`.",
    "KYVON_PRIVACY_URL": "Public URL of the privacy policy, linked from the sign-up form (hosted mode).",
    "KYVON_TERMS_URL": "Public URL of the terms of use, linked from the sign-up form (hosted mode).",
    "KYVON_BILLING_GRACE_DAYS": "Days a past-due subscription keeps the paid plan before dropping to free.",
    "KYVON_QUOTA_FREE_MESSAGES": "Hosted: chat messages per month on the free plan.",
    "KYVON_QUOTA_FREE_TOKENS": "Hosted: model tokens per month on the free plan (the real cost cap).",
    "KYVON_QUOTA_FREE_VOICE": "Hosted: voice transcriptions per month on the free plan.",
    "KYVON_QUOTA_FREE_SEARCHES": "Hosted: web searches per month on the free plan.",
    "KYVON_QUOTA_PRO_MESSAGES": "Hosted: chat messages per month on the paid plan.",
    "KYVON_QUOTA_PRO_TOKENS": "Hosted: model tokens per month on the paid plan.",
    "KYVON_QUOTA_PRO_VOICE": "Hosted: voice transcriptions per month on the paid plan.",
    "KYVON_QUOTA_PRO_SEARCHES": "Hosted: web searches per month on the paid plan.",
    "KYVON_TERMS_VERSION": "Version label recorded when someone accepts the terms. Bump it when the terms change.",
}


def rows() -> list[tuple[str, str, str]]:
    found: dict[str, tuple[str, str, str]] = {}
    for name, default, note, _ in SPECIAL:
        found[name] = (name, str(default), note)
    for _, (env, default, low, high) in config._INTS.items():
        found[env] = (env, str(default), NOTES.get(env, f"Whole number, {low} to {high}."))
    for _, (env, default) in config._FLAGS.items():
        found[env] = (env, "true" if default else "false", NOTES.get(env, "true or false."))
    for _, (env, default) in config._STRINGS.items():
        secret = env in SECRETS
        shown = "(none)" if default == "" else default
        found[env] = (
            env,
            shown,
            NOTES.get(env, "Text.")
            + (" Secret." if secret and "Secret" not in NOTES.get(env, "") else ""),
        )
    return sorted(found.values())


def render() -> str:
    lines = [
        "# Configuration reference",
        "",
        "Generated by `scripts/gen_config_docs.py` from the settings tables. Set these as environment",
        "variables (systemd `EnvironmentFile`, Docker `--env-file`) or in a `.env` file in the working",
        "directory; real environment variables win over `.env`. **Never commit real values.**",
        "",
        "| Variable | Default | Meaning |",
        "|---|---|---|",
    ]
    for name, default, note in rows():
        lines.append(f"| `{name}` | `{default}` | {note} |")
    lines += ["", "See [.env.example](../.env.example) for a starter file.", ""]
    return "\n".join(lines)


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        return 0 if TARGET.exists() and TARGET.read_text() == text else 1
    TARGET.write_text(text)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
