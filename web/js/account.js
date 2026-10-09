// "Account" panel (hosted mode): email status, plan and usage, billing, password, data export and deletion.

import { api } from "./api.js";
import { formatDate, h } from "./dom.js";
import { registerPanel } from "./panels.js";
import { showLogin } from "./auth.js";

const LABELS = { messages: "Messages", tokens: "AI usage", voice: "Voice clips", searches: "Web searches" };
const PLAN_NAMES = { free: "Free", pro: "Paid", admin: "Administrator" };

let bodyEl = null;

function bar(name, used, limit) {
    const percent = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
    // The page's content-security policy forbids inline style attributes, so set the width here.
    const fill = h("div", { class: `usage-fill${percent >= 90 ? " hot" : ""}` });
    fill.style.width = `${percent}%`;
    return h(
        "div",
        { class: "usage-row" },
        h(
            "div",
            { class: "usage-label" },
            h("span", {}, LABELS[name]),
            h("span", {}, limit === undefined ? `${used}` : `${used.toLocaleString()} of ${limit.toLocaleString()}`)
        ),
        h(
            "div",
            {
                class: "usage-bar",
                role: "progressbar",
                "aria-label": LABELS[name],
                "aria-valuemin": "0",
                "aria-valuemax": "100",
                "aria-valuenow": String(percent),
            },
            fill
        )
    );
}

function note(text, kind = "") {
    return h("p", { class: `account-note ${kind}`, role: "status" }, text);
}

// The only places the billing buttons may send the browser: Stripe's hosted pages.
const STRIPE_HOSTS = ["checkout.stripe.com", "billing.stripe.com"];

function isStripeUrl(value) {
    try {
        const url = new URL(value);
        return url.protocol === "https:" && STRIPE_HOSTS.includes(url.hostname);
    } catch {
        return false;
    }
}

async function go(path, button) {
    button.disabled = true;
    try {
        const data = await api(path, { method: "POST" });
        if (!isStripeUrl(data.url)) throw new Error("Billing returned an unexpected address.");
        window.location.assign(data.url);
    } catch (error) {
        button.disabled = false;
        bodyEl.prepend(note(error.message, "bad"));
    }
}

function emailSection(user) {
    if (!user.email) return null;
    const children = [
        h("h3", { class: "section" }, "Email"),
        h("div", { class: "kv" }, h("span", { class: "k" }, user.email),
            h("span", { class: `v ${user.email_verified ? "good" : "bad"}` },
                user.email_verified ? "confirmed" : "not confirmed")),
    ];
    if (!user.email_verified) {
        const message = h("p", { class: "account-note" }, "Confirm your email to use the assistant. Check your inbox for the link.");
        children.push(
            message,
            h("button", {
                class: "mini",
                text: "Resend the email",
                onclick: async event => {
                    event.target.disabled = true;
                    try {
                        await api("/auth/resend-verification", { method: "POST" });
                        message.textContent = "Sent. It can take a minute to arrive.";
                    } catch (error) {
                        message.textContent = error.message;
                    }
                },
            })
        );
    }
    return h("section", { class: "admin-section" }, ...children);
}

function usageSection(usage) {
    const rows = ["messages", "tokens", "voice", "searches"].map(name =>
        usage.limits ? bar(name, usage.used[name], usage.limits[name]) : null
    );
    return h(
        "section",
        { class: "admin-section" },
        h("h3", { class: "section" }, "Plan and usage"),
        h("div", { class: "kv" }, h("span", { class: "k" }, "Plan"), h("span", { class: "v" }, PLAN_NAMES[usage.plan] || usage.plan)),
        usage.limits ? rows : note("No limits on this account."),
        usage.limits ? h("p", { class: "account-note" }, `Resets ${formatDate(usage.resets_at)}.`) : null
    );
}

function billingSection(billing) {
    if (!billing.configured) return null;
    const pro = billing.plan === "pro";
    const children = [h("h3", { class: "section" }, "Billing")];
    if (pro) {
        if (billing.cancel_at_period_end) {
            children.push(note(`Your plan ends on ${formatDate(billing.current_period_end)}.`));
        } else if (billing.current_period_end) {
            children.push(note(`Renews ${formatDate(billing.current_period_end)}.`));
        }
        children.push(h("button", { class: "mini", text: "Manage billing", onclick: e => go("/billing/portal", e.target) }));
    } else {
        children.push(
            note(billing.status === "past_due" ? "Your last payment did not go through. Update your card to keep the paid plan." : `Get more messages and usage${billing.price_label ? ` for ${billing.price_label}` : ""}.`),
            h("button", { class: "mini", text: "Upgrade", onclick: e => go("/billing/checkout", e.target) })
        );
        if (billing.status === "past_due" || billing.status === "canceled") {
            children.push(h("button", { class: "mini", text: "Manage billing", onclick: e => go("/billing/portal", e.target) }));
        }
    }
    return h("section", { class: "admin-section" }, ...children);
}

function passwordSection() {
    const current = h("input", { type: "password", placeholder: "Current password", "aria-label": "Current password", autocomplete: "current-password" });
    const next = h("input", { type: "password", placeholder: "New password (10+ characters)", "aria-label": "New password", autocomplete: "new-password" });
    const message = h("p", { class: "account-note", role: "status" });
    return h(
        "section",
        { class: "admin-section" },
        h("h3", { class: "section" }, "Change password"),
        current,
        next,
        h("button", {
            class: "mini",
            text: "Change password",
            onclick: async () => {
                try {
                    await api("/account/change-password", { method: "POST", body: { current_password: current.value, new_password: next.value } });
                    current.value = next.value = "";
                    message.textContent = "Password changed. Other devices were signed out.";
                    message.className = "account-note good";
                } catch (error) {
                    message.textContent = error.message;
                    message.className = "account-note bad";
                }
            },
        }),
        message
    );
}

async function download() {
    const response = await fetch("/api/v1/account/export", { credentials: "same-origin" });
    if (!response.ok) throw new Error("Could not export your data.");
    const blob = await response.blob();
    const link = h("a", { href: URL.createObjectURL(blob), download: "kyvon-data.json" });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
}

function dataSection() {
    const message = h("p", { class: "account-note", role: "status" });
    const confirm = h("input", { type: "password", placeholder: "Your password", "aria-label": "Your password to confirm deletion", autocomplete: "current-password" });
    const confirmBox = h(
        "div",
        { class: "danger-box", hidden: true },
        h("p", { class: "account-note bad" }, "This permanently deletes your account, chats, memories and tasks, and cancels any subscription. It cannot be undone."),
        confirm,
        h("button", {
            class: "mini danger",
            text: "Delete everything",
            onclick: async () => {
                try {
                    await api("/account", { method: "DELETE", body: { password: confirm.value }, notifyUnauthorized: false });
                    showLogin("Your account was deleted.");
                } catch (error) {
                    message.textContent = error.message;
                    message.className = "account-note bad";
                }
            },
        })
    );
    return h(
        "section",
        { class: "admin-section" },
        h("h3", { class: "section" }, "Your data"),
        h("button", { class: "mini", text: "Download my data", onclick: () => download().catch(e => { message.textContent = e.message; message.className = "account-note bad"; }) }),
        h("button", { class: "mini danger", text: "Delete my account", onclick: () => { confirmBox.hidden = !confirmBox.hidden; } }),
        confirmBox,
        message
    );
}

async function load() {
    if (!bodyEl) return;
    bodyEl.replaceChildren(h("p", { class: "empty" }, "Loading…"));
    try {
        const account = await api("/account");
        let billing = { configured: false };
        try {
            billing = await api("/billing");
        } catch {
            // Billing may be switched off; the rest of the panel still works.
        }
        const banner = window.location.hash.startsWith("#billing=") ? window.location.hash.slice(9) : "";
        if (banner) window.history.replaceState({}, "", window.location.pathname + window.location.search);
        // replaceChildren turns a null argument into the text "null", so drop the empty sections.
        bodyEl.replaceChildren(
            ...[
                banner === "success" ? note("Thanks! Your plan will update in a moment.", "good") : null,
                banner === "cancelled" ? note("No payment was made.") : null,
                emailSection(account.user),
                usageSection(account.usage),
                billingSection(billing),
                passwordSection(),
                dataSection(),
            ].filter(Boolean)
        );
    } catch (error) {
        if (error.status !== 401) bodyEl.replaceChildren(h("p", { class: "empty" }, error.message));
    }
}

export function registerAccountPanel() {
    registerPanel({
        id: "account",
        label: "ACCOUNT",
        mount(el) {
            bodyEl = el;
            load();
        },
        refresh: load,
    });
}
