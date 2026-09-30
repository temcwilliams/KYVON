// "Admin" panel: health, errors, usage and run traces for the owner. No secrets are shown.

import { api } from "./api.js";
import { formatDate, h } from "./dom.js";
import { registerPanel } from "./panels.js";

let bodyEl = null;

function row(label, value, ok = null) {
    return h(
        "div",
        { class: "kv" },
        h("span", { class: "k" }, label),
        h("span", { class: `v${ok === false ? " bad" : ok === true ? " good" : ""}` }, String(value))
    );
}

function section(title, ...children) {
    return h("section", { class: "admin-section" }, h("h3", { class: "section" }, title), ...children);
}

async function load(deep = false) {
    if (!bodyEl) return;
    bodyEl.replaceChildren(h("p", { class: "empty" }, deep ? "Running deep check…" : "Loading…"));
    try {
        const [status, errors, usage, tools, agents, autos] = await Promise.all([
            api(`/admin/status${deep ? "?deep=1" : ""}`),
            api("/admin/errors?resolved=false&limit=10"),
            api("/admin/usage"),
            api("/tool-runs?limit=10"),
            api("/agents/runs?limit=10"),
            api("/admin/automation-runs?limit=10"),
        ]);
        render(status, errors.errors, usage, tools.tool_runs, agents.runs, autos.runs);
    } catch (error) {
        if (error.status !== 401) bodyEl.replaceChildren(h("p", { class: "empty" }, error.message));
    }
}

function render(status, errors, usage, toolRuns, agentRuns, autoRuns) {
    const db = status.database;
    const llm = status.llm;
    bodyEl.replaceChildren(
        h("div", { class: "toolbar" }, h("button", { class: "mini", text: "Refresh", onclick: () => load(false) }), h("button", { class: "mini", text: "Deep check (calls the AI)", onclick: () => load(true) })),
        section(
            "Health",
            row("Overall", status.healthy ? "healthy" : "needs attention", status.healthy),
            row("Database", db.ok ? `ok${db.up_to_date === false ? " (migrations pending)" : ""}` : "unreachable", db.ok && db.up_to_date !== false),
            row("AI model", llm.reachable === undefined ? `${llm.model} (not tested)` : llm.reachable ? "reachable" : "unreachable", llm.reachable === undefined ? null : llm.reachable),
            row("Scheduler", status.scheduler.running ? "running" : status.scheduler.enabled ? "stopped" : "off", status.scheduler.enabled ? status.scheduler.running : null),
            row("Uptime", `${Math.round(status.uptime_seconds / 60)} min`),
            row("Disk free", status.disk ? `${Math.round(status.disk.free_bytes / 1e9)} GB` : "unknown")
        ),
        section(
            "Services",
            row("Google Calendar", status.integrations.calendar.configured ? `${status.integrations.calendar.connected_accounts} connected` : "not set up"),
            row("Logseq", status.integrations.logseq.configured ? "connected" : "not set up"),
            row("Hermes", status.integrations.hermes.configured ? (status.integrations.hermes.reachable === false ? "unreachable" : "configured") : "not set up"),
            row("Push notifications", status.integrations.push.configured ? "configured" : "not set up"),
            row("Speech to text", status.integrations.speech_to_text.configured ? "available" : "off")
        ),
        section(
            "Activity (7 days)",
            row("Assistant replies", usage.assistant_replies),
            row("Tokens in / out", `${usage.chat_tokens.in} / ${usage.chat_tokens.out}`),
            row("Agent tokens in / out", `${usage.agent_tokens.in} / ${usage.agent_tokens.out}`),
            row("Tool calls", Object.entries(usage.tool_calls_by_tool).map(([k, v]) => `${k}×${v}`).join(", ") || "none"),
            row("Pending approvals", status.tools.pending_approvals)
        ),
        section(
            `Unresolved errors (${status.errors.unresolved})`,
            ...(errors.length ? errors.map(errorItem) : [h("p", { class: "empty" }, "No unresolved errors.")])
        ),
        section("Recent tool runs", ...list(toolRuns, r => `${r.tool} · ${r.status}${r.error ? ` · ${r.error}` : ""}`, r => r.created_at)),
        section("Recent agent runs", ...list(agentRuns, r => `${r.agent} · ${r.status} · ${r.steps} steps · ${r.tool_calls} tools`, r => r.created_at)),
        section("Recent automation runs", ...list(autoRuns, r => `#${r.automation_id} · ${r.status}${r.error ? ` · ${r.error}` : ""}`, r => r.started_at))
    );
}

function list(items, text, when) {
    if (!items.length) return [h("p", { class: "empty" }, "Nothing yet.")];
    return items.map(item => h("p", { class: "item-meta" }, `${formatDate(when(item))} — ${text(item)}`));
}

function errorItem(e) {
    return h(
        "div",
        { class: "item" },
        h("div", { class: "item-body" }, h("span", { class: "item-title" }, e.kind), h("span", { class: "note-body" }, e.message), h("span", { class: "item-meta" }, `${formatDate(e.created_at)}${e.request_id ? ` · request ${e.request_id}` : ""}`)),
        h("span", { class: "item-actions" }, h("button", { class: "mini", text: "Mark resolved", onclick: async () => {
            const note = window.prompt("What fixed it? (optional)", "") ?? "";
            await api(`/admin/errors/${e.id}/resolve`, { method: "POST", body: { note } });
            load(false);
        } }))
    );
}

registerPanel({
    id: "admin",
    label: "Admin",
    mount(container) {
        bodyEl = h("div", {});
        container.append(bodyEl);
        load(false);
    },
    refresh: () => load(false),
});
