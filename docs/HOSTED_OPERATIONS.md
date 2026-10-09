# Operating a hosted KYVON: requests, abuse and incidents

Practical procedures for the person running the service. They assume the admin tools in the code: an
administrator account, `GET /api/v1/admin/users`, suspend/restore endpoints, `GET /api/v1/admin/top-users`, and
the CLI. **Not legal advice**; have your lawyer set the deadlines and wording for your markets.

## A person asks for their data

Normally they use **Account, Download my data**. If they cannot sign in: verify they control the email address
(they reply from the address on file, or use the password-reset link sent there), then have them reset their
password and use the button themselves. Do not sign in as them or read their data to answer a request. Keep a
note of the date and what you did.

## A person asks for deletion

Normally **Account, Delete my account** (needs their password; cancels the subscription first). If they cannot
sign in, verify the same way, have them reset their password, then delete. Record the request. Remember backups:
deleted data persists until backups rotate; say so in your reply.

## Abuse report or a person breaking the rules

1. Find the account: `GET /api/v1/admin/users?q=<email part>`; check usage with `top-users`.
2. Suspend: `POST /api/v1/admin/users/<id>/disable` (signs it out everywhere, blocks sign-in, keeps data).
3. Tell them what happened and how to appeal ([SUPPORT EMAIL]).
4. Restore with `.../enable` if wrong. Illegal content involving children or imminent harm goes to the
   authorities; get legal advice about preserving evidence.

## Cost spike

`GET /api/v1/admin/top-users?days=1` shows the heaviest accounts. Lower `KYVON_QUOTA_*` and restart, suspend the
account, or set `KYVON_SIGNUP_OPEN=false`. Check your Groq dashboard limits as a backstop.

## Security incident

1. Contain: rotate `GROQ_API_KEY`, `STRIPE_*`, `KYVON_SMTP_PASSWORD`, and `KYVON_ENCRYPTION_KEY` as relevant;
   sign everyone out by deleting rows in `api_tokens` (or set new database credentials).
2. Preserve logs; find what was accessed.
3. Notify affected people and regulators as the law requires (often within 72 hours of becoming aware; confirm
   with your lawyer).
4. Fix, then write down what happened and what changed.

## Routine

Weekly: look at errors (`/api/v1/admin/errors`), Stripe webhook failures, Groq spend, mail bounces.
Monthly: restore a backup into a scratch database and check it.
