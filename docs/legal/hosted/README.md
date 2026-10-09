# Legal drafts for the hosted service

**Drafts written by an AI assistant. Not legal advice. They do not make a public, paid service safe from
legal claims.** A public service that takes payments and holds strangers' conversations raises questions
(consumer-protection and privacy law in each country you sell to, tax, children's data, content liability,
payment-processor rules, data-transfer rules, AI-specific rules) that need a qualified lawyer who knows where
you and your users are.

What these drafts are good for: giving that lawyer an accurate starting point. Every statement was written
against what the code does today. Where something is **not implemented**, the document says so, and the list
below must be resolved before launch.

Fill in every `[BRACKETED]` placeholder.

| File | Purpose |
|---|---|
| [PRIVACY_POLICY.md](PRIVACY_POLICY.md) | What is collected, why, who receives it, how long it is kept, people's rights |
| [TERMS_OF_SERVICE.md](TERMS_OF_SERVICE.md) | The agreement people accept when they sign up |
| [SUBSCRIPTION_TERMS.md](SUBSCRIPTION_TERMS.md) | Price, renewal, cancellation, refunds, failed payments |
| [ACCEPTABLE_USE.md](ACCEPTABLE_USE.md) | What may not be done with the service, and what happens if it is |
| [SUBPROCESSORS.md](SUBPROCESSORS.md) | The companies that receive personal data on your behalf |
| [../../HOSTED_OPERATIONS.md](../../HOSTED_OPERATIONS.md) | Handling deletion and export requests, abuse reports, incidents |

## Known gaps that the documents cannot paper over

1. **No re-acceptance flow.** The terms version is recorded at sign-up, but existing users are not asked to
   accept a new version. Changing the terms materially needs that built first.
2. **No Apple in-app purchase.** Selling the subscription inside the iPhone app is not allowed with Stripe alone.
3. **Backups keep deleted data** until they rotate. The policy states a retention period you must actually meet.
4. **Conversation text is not encrypted at rest by the application** (encrypt the database volume), and it is
   sent to the AI provider.
5. **Google Calendar for the public** needs Google's OAuth app verification.
6. **No content moderation of AI output**, and no automated abuse detection beyond limits. Reports are handled
   by hand with the admin tools.
7. **Not run against real Stripe, real email, real load, or a real host.**
8. **No data processing agreements, transfer mechanisms or records of processing are in place** until you
   sign them with each provider.
