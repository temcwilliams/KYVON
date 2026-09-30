// "Calendar" panel: connect Google Calendar, see upcoming events, add and delete events.

import { api } from "./api.js";
import { h } from "./dom.js";
import { registerPanel } from "./panels.js";
import { on } from "./state.js";
import { say } from "./ui.js";

let bodyEl = null;
let noteEl = null;

function note(text, isError = false) {
    if (!noteEl) return;
    noteEl.textContent = text;
    noteEl.classList.toggle("error", isError);
}

function when(event) {
    if (event.all_day) return new Date(`${event.start}T00:00`).toLocaleDateString([], { dateStyle: "medium" }) + " (all day)";
    const start = new Date(event.start);
    const end = new Date(event.end);
    return `${start.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} – ${end.toLocaleTimeString([], { timeStyle: "short" })}`;
}

async function load() {
    if (!bodyEl) return;
    let status;
    try {
        status = await api("/calendar/status");
    } catch (error) {
        if (error.status !== 401) bodyEl.replaceChildren(h("p", { class: "empty" }, error.message));
        return;
    }
    if (!status.configured) {
        bodyEl.replaceChildren(
            h("p", { class: "empty" }, "Google Calendar isn't set up on this server yet. See the deployment guide for the Google credentials it needs.")
        );
        return;
    }
    if (!status.connected) {
        bodyEl.replaceChildren(
            h("p", {}, "Connect your Google Calendar so KYVON can read and (with your approval) change your events."),
            h("button", { onclick: connect, text: "Connect Google Calendar" })
        );
        return;
    }
    await renderConnected(status);
}

async function connect() {
    try {
        const data = await api("/calendar/connect", { method: "POST" });
        // Only ever navigate to Google's sign-in page, whatever the server sent.
        if (!data.authorization_url.startsWith("https://accounts.google.com/")) {
            throw new Error("Unexpected sign-in address.");
        }
        window.location.assign(data.authorization_url);
    } catch (error) {
        note(error.message, true);
    }
}

async function disconnect() {
    if (!window.confirm("Disconnect Google Calendar from KYVON?")) return;
    try {
        await api("/calendar/disconnect", { method: "POST" });
        load();
    } catch (error) {
        note(error.message, true);
    }
}

async function renderConnected(status) {
    const list = h("ul", { class: "list", "aria-label": "Upcoming events" });
    const title = h("input", { type: "text", placeholder: "Event title", "aria-label": "Event title", maxlength: "200", required: true });
    const start = h("input", { type: "datetime-local", "aria-label": "Start", required: true });
    const end = h("input", { type: "datetime-local", "aria-label": "End (optional)" });
    const form = h(
        "form",
        {
            class: "stack",
            onsubmit: async event => {
                event.preventDefault();
                try {
                    await api("/calendar/events", {
                        method: "POST",
                        body: { title: title.value, start: start.value, end: end.value || null },
                    });
                    title.value = "";
                    note("Event added.");
                    loadEvents(list);
                } catch (error) {
                    note(error.message, true);
                }
            },
        },
        title,
        h("div", { class: "row" }, start, end),
        h("button", { type: "submit", text: "Add event" })
    );
    bodyEl.replaceChildren(
        h("p", { class: "item-meta" }, `Connected: ${status.account_email || "Google Calendar"}`),
        form,
        h("h3", { class: "section" }, "Next 7 days"),
        list,
        h("button", { class: "mini danger", onclick: disconnect, text: "Disconnect" })
    );
    loadEvents(list);
}

async function loadEvents(list) {
    try {
        const data = await api("/calendar/events");
        if (!data.events.length) {
            list.replaceChildren(h("p", { class: "empty" }, "Nothing on your calendar for the next week."));
            return;
        }
        list.replaceChildren(
            ...data.events.map(event =>
                h(
                    "li",
                    { class: "item" },
                    h(
                        "div",
                        { class: "item-body" },
                        h("span", { class: "item-title" }, event.title),
                        h("span", { class: "item-meta" }, when(event) + (event.location ? ` · ${event.location}` : ""))
                    ),
                    h(
                        "span",
                        { class: "item-actions" },
                        h("button", {
                            class: "mini danger",
                            text: "Delete",
                            "aria-label": `Delete ${event.title}`,
                            onclick: async () => {
                                if (!window.confirm(`Delete "${event.title}" from Google Calendar?`)) return;
                                try {
                                    await api(`/calendar/events/${encodeURIComponent(event.id)}?calendar_id=${encodeURIComponent(event.calendar_id)}`, { method: "DELETE" });
                                    loadEvents(list);
                                } catch (error) {
                                    note(error.message, true);
                                }
                            },
                        })
                    )
                )
            )
        );
    } catch (error) {
        if (error.status === 409) load();
        else if (error.status !== 401) note(error.message, true);
    }
}

registerPanel({
    id: "calendar",
    label: "Calendar",
    mount(container) {
        noteEl = h("p", { class: "note", role: "status" });
        bodyEl = h("div", {});
        container.append(noteEl, bodyEl);
        load();
    },
    refresh: load,
});

// Result of the Google sign-in redirect (?calendar=connected|error).
export function handleOAuthReturn() {
    const params = new URLSearchParams(window.location.search);
    const result = params.get("calendar");
    if (!result) return;
    say(
        result === "connected"
            ? "Google Calendar is connected."
            : `Google Calendar could not be connected${params.get("reason") ? `: ${params.get("reason")}` : "."}`
    );
    window.history.replaceState({}, "", window.location.pathname);
}

on("turn:done", () => load());
