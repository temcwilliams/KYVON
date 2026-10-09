// Approval cards for actions KYVON wants to take but must not take without the user's say-so.

import { api } from "./api.js";
import { h } from "./dom.js";
import { scrollToEnd } from "./ui.js";

const conversation = document.getElementById("conversation");

export function showPending(runs) {
    for (const run of runs || []) {
        if (run.status === "pending_confirmation" && !conversation.querySelector(`[data-run="${run.id}"]`)) {
            conversation.appendChild(card(run));
        }
    }
    scrollToEnd();
}

function card(run) {
    const status = h("p", { class: "confirm-status", role: "status" });
    const approve = h("button", { class: "mini", onclick: () => respond(run, "confirm", el, status), text: "Approve" });
    const decline = h("button", { class: "mini danger", onclick: () => respond(run, "reject", el, status), text: "Decline" });

    const details = h(
        "details",
        {},
        h("summary", {}, "Details"),
        h("pre", { class: "confirm-args" }, JSON.stringify(run.arguments ?? {}, null, 2)),
        h("p", { class: "item-meta" }, `Tool: ${run.tool} · risk: ${run.risk}`)
    );

    const el = h(
        "div",
        { class: "confirm-card", role: "group", "aria-label": "Approval needed", dataset: { run: String(run.id) } },
        h("strong", {}, "Approval needed"),
        h("p", { class: "confirm-summary" }, run.summary || `Run ${run.tool}`),
        details,
        h("div", { class: "row" }, approve, decline),
        status
    );
    return el;
}

async function respond(run, action, el, status) {
    for (const button of el.querySelectorAll("button")) button.disabled = true;
    status.textContent = action === "confirm" ? "Working…" : "Declining…";
    try {
        const data = await api(`/tool-runs/${run.id}/${action}`, { method: "POST" });
        const finished = data.tool_run;
        if (action === "reject") {
            status.textContent = "Declined.";
        } else if (finished.status === "succeeded") {
            status.textContent = "Done.";
        } else {
            status.textContent = `That didn't work: ${finished.error || finished.status}`;
        }
        el.querySelector(".row").remove();
    } catch (error) {
        status.textContent = error.message;
        for (const button of el.querySelectorAll("button")) button.disabled = false;
    }
}

// After a refresh or switching chats, show approvals that are still waiting.
export async function loadPending(conversationId) {
    try {
        const data = await api("/tool-runs/pending");
        showPending(data.tool_runs.filter(r => r.conversation_id === conversationId));
    } catch {
        // Not critical.
    }
}
