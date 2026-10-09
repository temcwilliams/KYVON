# Running KYVON as a hosted service

This is for operating KYVON for **other people** (sign-up, free and paid plans). It is separate from
[DEPLOYMENT.md](DEPLOYMENT.md), which covers a personal install for one owner. The two modes share the
code: `KYVON_MODE=hosted` switches on accounts, quotas and billing; the default `personal` is unchanged.

> **Status, plainly.** Everything here is implemented and tested with fakes and, for the database, against
> PostgreSQL in CI. **Nothing has been run against real Stripe, a real mail server, real traffic, or on a
> real host.** It has not been load tested. Treat a first launch as a trial with friendly users, in Stripe
> test mode, with sign-up closed to the public.

## What you need

| Need | Notes |
|---|---|
| A host that can run containers or Python 3.12 | Small to start; the model calls are made to Groq, not on your machine |
| PostgreSQL 14+ | Managed (RDS, Cloud SQL, Neon, Supabase...) is the safest. Do not run a public service on SQLite |
| HTTPS in front | Cloudflare Tunnel, Caddy or nginx. Set `KYVON_PROXY_HOPS` to the number of proxies |
| A domain and an email provider | Verification and reset emails must arrive. Set up SPF and DKIM or they will land in spam |
| A Groq account with billing | Every user's chat goes through your key. Quotas are your only cost control |
| A Stripe account | Start in **test mode** |
| Legal documents | The drafts in `docs/legal/hosted/` need a lawyer before you take money or strangers' data |

## Moving parts

```
people --HTTPS--> proxy --> web workers (gunicorn, N processes) --> PostgreSQL
                                   \--> Groq (chat, search, voice)   ^
                                   \--> Stripe (checkout, portal)    |
                                   \--> SMTP (verification, reset)   |
                   scheduler (exactly one process) -----------------/
                   Stripe --signed webhook--> /api/v1/billing/webhook
```

Shared across workers (safe to scale web): the database, sign-up and login limits, plan and usage.
Per process (approximate, fine): the per-user API rate limit and the location cache.
The scheduler should run as **one** dedicated process (`kyvon scheduler`); two would still be safe because every
automation run is claimed atomically, but they waste work.

## Step by step (Docker Compose on one machine)

1. `cp .env.hosted.example .env.hosted` and fill it in. `chmod 600` it. Never commit it.
2. `docker compose -f deploy/docker-compose.hosted.yml --env-file .env.hosted up -d --build`
   (Postgres starts, `db-upgrade` runs once, then web and the scheduler).
3. Create the first administrator: 
   `docker compose -f deploy/docker-compose.hosted.yml exec web flask --app wsgi kyvon create-user --email you@example.com --admin`
4. Put HTTPS in front of port 8080 and set `KYVON_PUBLIC_URL` to that address.
5. Run `flask --app wsgi kyvon doctor`: it flags a missing mail transport, an `http://` public URL, SQLite, and
   a missing proxy setting. Fix every FAIL.
6. Open sign-up only when everything below passes: `KYVON_SIGNUP_OPEN=true`.

Without Docker: use `deploy/kyvon.service` for the web process, `deploy/kyvon-scheduler.service` for the scheduler,
and `KYVON_SCHEDULER=false` in the web environment.

## Email

Set `KYVON_EMAIL_FROM` and `KYVON_SMTP_*`. Sign up with a throwaway address and confirm both emails (verification,
then password reset) arrive in an inbox, not spam. Links carry the token after a `#` so it never reaches logs.
An account cannot use the assistant until its email is verified.

## Stripe (test mode first)

1. Create a Product with a monthly recurring Price; put the Price id in `STRIPE_PRICE_ID`.
2. Add a webhook endpoint `https://<your domain>/api/v1/billing/webhook` for these events:
   `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`. Put its signing secret in
   `STRIPE_WEBHOOK_SECRET`.
3. In the Stripe dashboard enable the Customer Portal (this is where people cancel and update cards).
4. Subscribe with Stripe's test card `4242 4242 4242 4242`; confirm the account shows the paid plan, then cancel
   in the portal and confirm it drops back. Replay a webhook from the dashboard: it must change nothing.
5. Only then switch to live keys.

Cards are entered on Stripe's pages: KYVON never sees card numbers. Refunds and disputes are handled in Stripe;
KYVON does not issue refunds. Sales tax / VAT is your responsibility (Stripe Tax can help).

**Apple.** Selling a subscription *inside the iPhone app* requires Apple's in-app purchase system (and Apple's
cut). That is **not implemented**. Until it is, the App Store build must not offer or link to the Stripe
purchase; paid sign-up works on the website and the web app only.

## Controlling cost

The monthly allowances (`KYVON_QUOTA_*`) are enforced before every model call, voice transcription and web
search, and recorded after. Work out the worst case: `pro tokens x your Groq price` must be well under what the
subscription earns. `GET /api/v1/admin/top-users` shows who spends the most. A burst of simultaneous requests can
overshoot a limit by one request; a failed model call still counts. Titles and summaries are not metered (small).

## Backups and data

Back up PostgreSQL with `pg_dump` (or your provider's snapshots) on a schedule, and **test a restore**. The
`kyvon backup` command is for SQLite only. Account deletion and export are built in
(`DELETE /api/v1/account`, `GET /api/v1/account/export`); deleting also cancels any subscription first and is
refused if Stripe cannot confirm.

## Security notes specific to hosting

* Administrators only for server-wide endpoints and the diagnostics tools; ordinary accounts never see them.
* Logseq and Hermes are disabled in hosted mode (they reach server folders and private endpoints).
* Sign-up, reset, verification and webhook rate limits and login lockouts are shared across workers (stored in the
  database). Ten wrong passwords lock an account for 15 minutes from any address.
* **Google Calendar for the public** needs Google to verify your OAuth app (sensitive scopes). Until then only
  listed test users can connect.
* Conversation text is stored unencrypted in the database and sent to Groq; encrypt the disk and restrict access.

## Launch checklist

- [ ] `kyvon doctor` has no FAIL; database is Postgres; HTTPS works; cookies Secure
- [ ] Verification and reset emails arrive in an inbox
- [ ] Stripe test-mode purchase, cancel, and webhook replay behave
- [ ] Quotas set from real prices; Groq billing alert configured
- [ ] Backups run and a restore was practiced
- [ ] Privacy policy, terms and subscription terms reviewed by a lawyer and published
- [ ] An abuse / support email address monitored
- [ ] Sign-up opened to a small group first
