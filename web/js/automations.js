// "Auto" panel: reminders and scheduled tasks.

import { api } from "./api.js";
import { formatDate, h } from "./dom.js";
import { registerPanel } from "./panels.js";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

let listEl = null;
let noteEl = null;

function note(text, isError = false) {
    if (!noteEl) return;
    noteEl.textContent = text;
    noteEl.classList.toggle("error", isError);
}

async function load() {
    if (!listEl) return;
    try {
        const data = await api("/automations");
        if (!data.automations.length) {
            listEl.replaceChildren(h("p", { class: "empty" }, "No automations yet. Add one here, or ask KYVON: “Remind me tomorrow at 8 AM…”."));
            return;
        }
        listEl.replaceChildren(...data.automations.map(render));
    } catch (error) {
        if (error.status !== 401) note(error.message, true);
    }
}

function render(a) {
    const status = a.enabled
        ? `Next: ${a.next_run_at ? formatDate(a.next_run_at) : "—"}`
        : `Off${a.disabled_reason ? ` (${a.disabled_reason})` : ""}`;
    const toggle = h("input", {
        type: "checkbox",
        checked: a.enabled,
        "aria-label": `${a.name} enabled`,
        onchange: async event => {
            try {
                await api(`/automations/${a.id}`, { method: "PATCH", body: { enabled: event.target.checked } });
            } catch (error) {
                note(error.message, true);
            }
            load();
        },
    });
    const history = h("div", {});
    return h(
        "li",
        { class: "item" },
        h(
            "div",
            { class: "task-row" },
            toggle,
            h(
                "div",
                { class: "item-body" },
                h("span", { class: "item-title" }, a.name),
                h("span", { class: "item-meta" }, `${a.kind === "reminder" ? "Reminder" : "Scheduled task"} · ${a.schedule_text}`),
                h("span", { class: "item-meta" }, a.text || a.prompt || ""),
                h("span", { class: "item-meta" }, `${status} · ran ${a.run_count}× · last: ${a.last_status || "never"}`)
            )
        ),
        h(
            "span",
            { class: "item-actions" },
            h("button", { class: "mini", text: "Run now", onclick: async () => {
                try {
                    await api(`/automations/${a.id}/run`, { method: "POST" });
                    note("Started. The result will appear in your inbox.");
                } catch (error) {
                    note(error.message, true);
                }
            } }),
            h("button", { class: "mini", text: "History", onclick: () => showHistory(a, history) }),
            h("button", { class: "mini danger", text: "Delete", "aria-label": `Delete ${a.name}`, onclick: async () => {
                if (!window.confirm(`Delete "${a.name}"?`)) return;
                await api(`/automations/${a.id}`, { method: "DELETE" });
                load();
            } })
        ),
        history
    );
}

async function showHistory(a, container) {
    if (container.childElementCount) {
        container.replaceChildren();
        return;
    }
    try {
        const data = await api(`/automations/${a.id}/runs`);
        container.replaceChildren(
            ...(data.runs.length
                ? data.runs.map(run => h("p", { class: "item-meta" }, `${formatDate(run.started_at)} · ${run.status}${run.error ? ` · ${run.error}` : ""}`))
                : [h("p", { class: "item-meta" }, "No runs yet.")])
        );
    } catch (error) {
        note(error.message, true);
    }
}

function scheduleFields() {
    const type = h("select", { "aria-label": "Repeat" }, [
        ["once", "Once"],
        ["daily", "Every day"],
        ["weekly", "Weekly"],
        ["monthly", "Monthly"],
        ["interval", "Every N minutes"],
    ].map(([value, label]) => h("option", { value }, label)));
    const at = h("input", { type: "datetime-local", "aria-label": "Date and time" });
    const time = h("input", { type: "time", value: "08:00", "aria-label": "Time" });
    const days = h("div", { class: "row", role: "group", "aria-label": "Days" }, DAYS.map(day =>
        h("label", { class: "check" }, h("input", { type: "checkbox", value: day }), ` ${day}`)
    ));
    const monthDay = h("input", { type: "number", min: "1", max: "31", value: "1", "aria-label": "Day of month" });
    const minutes = h("input", { type: "number", min: "15", max: "10080", value: "60", "aria-label": "Minutes between runs" });
    const rows = { once: [at], daily: [time], weekly: [days, time], monthly: [monthDay, time], interval: [minutes] };
    const holder = h("div", { class: "stack" });
    const refresh = () => holder.replaceChildren(...rows[type.value]);
    type.addEventListener("change", refresh);
    refresh();

    return {
        elements: [type, holder],
        value() {
            switch (type.value) {
                case "once": return { type: "once", at: at.value };
                case "daily": return { type: "daily", time: time.value };
                case "weekly": return { type: "weekly", days: [...days.querySelectorAll("input:checked")].map(i => i.value), time: time.value };
                case "monthly": return { type: "monthly", day: Number(monthDay.value), time: time.value };
                default: return { type: "interval", minutes: Number(minutes.value) };
            }
        },
    };
}

registerPanel({
    id: "automations",
    label: "Auto",
    mount(container) {
        listEl = h("ul", { class: "list", "aria-label": "Automations" });
        noteEl = h("p", { class: "note", role: "status" });
        const name = h("input", { type: "text", placeholder: "Name", "aria-label": "Name", maxlength: "120", required: true });
        const kind = h("select", { "aria-label": "Type" }, h("option", { value: "reminder" }, "Reminder"), h("option", { value: "prompt" }, "Scheduled task (KYVON does this each time)"));
        const message = h("input", { type: "text", placeholder: "Reminder text, or what KYVON should do", "aria-label": "Message", maxlength: "1000", required: true });
        const schedule = scheduleFields();
        const form = h(
            "form",
            {
                class: "stack",
                onsubmit: async event => {
                    event.preventDefault();
                    const body = { name: name.value, kind: kind.value, schedule: schedule.value() };
                    body[kind.value === "reminder" ? "text" : "prompt"] = message.value;
                    try {
                        await api("/automations", { method: "POST", body });
                        name.value = "";
                        message.value = "";
                        note("Automation added.");
                        load();
                    } catch (error) {
                        note(error.message, true);
                    }
                },
            },
            name, kind, message, ...schedule.elements,
            h("button", { type: "submit", text: "Add automation" })
        );
        container.append(form, noteEl, listEl);
        load();
    },
    refresh: load,
});
