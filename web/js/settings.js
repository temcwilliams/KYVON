// "Settings" panel: personalisation the user can inspect and change.

import { api } from "./api.js";
import { h } from "./dom.js";
import { registerPanel } from "./panels.js";
import { canPromptInstall, disablePush, enablePush, isIOS, isStandalone, onInstallStateChange, promptInstall, pushStatus } from "./pwa.js";

// Tell the server which time zone this device is in (used unless the user sets one).
export async function reportTimezone() {
    try {
        const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (zone) await api("/settings", { method: "PATCH", body: { detected_timezone: zone } });
    } catch {
        // Not critical.
    }
}

const CHOICES = {
    response_style: [["concise", "Concise"], ["balanced", "Balanced"], ["detailed", "Detailed"]],
    tone: [["default", "Default"], ["warm", "Warm"], ["formal", "Formal"], ["playful", "Playful"]],
    units: [["imperial", "Imperial (°F, mph)"], ["metric", "Metric (°C, km/h)"]],
    week_starts_on: [["sun", "Sunday"], ["mon", "Monday"]],
};

let noteEl = null;

function note(text, isError = false) {
    if (!noteEl) return;
    noteEl.textContent = text;
    noteEl.classList.toggle("error", isError);
}

async function save(patch) {
    try {
        await api("/settings", { method: "PATCH", body: patch });
        note("Saved.");
    } catch (error) {
        note(error.message, true);
    }
}

function selectField(label, key, value) {
    return h(
        "label",
        { class: "field" },
        h("span", {}, label),
        h(
            "select",
            { onchange: event => save({ [key]: event.target.value }) },
            CHOICES[key].map(([v, text]) => h("option", { value: v, selected: v === value }, text))
        )
    );
}

function textField(label, key, value, { multiline = false, maxlength = 60 } = {}) {
    const input = h(multiline ? "textarea" : "input", { value, maxlength: String(maxlength), rows: multiline ? "3" : null, type: multiline ? null : "text" });
    if (multiline) input.textContent = value || "";
    input.addEventListener("change", () => save({ [key]: input.value.trim() === "" && key === "display_name" ? null : input.value }));
    return h("label", { class: "field" }, h("span", {}, label), input);
}

function toggle(label, key, value, disabled = false) {
    return h(
        "label",
        { class: "check field" },
        h("input", { type: "checkbox", checked: value, disabled, onchange: event => save({ [key]: event.target.checked }) }),
        ` ${label}`
    );
}

// "This device": install as an app and notifications.
function devicePanel() {
    const box = h("div", { class: "stack" });
    const message = h("p", { class: "note", role: "status" });

    async function render() {
        const rows = [];
        if (isStandalone()) {
            rows.push(h("p", { class: "item-meta" }, "KYVON is installed on this device."));
        } else if (canPromptInstall()) {
            rows.push(h("button", { onclick: async () => { await promptInstall(); render(); }, text: "Install KYVON as an app" }));
        } else if (isIOS()) {
            rows.push(h("p", { class: "item-meta" }, "To install: tap the Share button in Safari, then “Add to Home Screen”."));
        } else {
            rows.push(h("p", { class: "item-meta" }, "To install, use your browser's “Install app” option (usually in the address bar or menu)."));
        }

        const push = await pushStatus();
        if (!push.supported) {
            rows.push(h("p", { class: "item-meta" }, isIOS() && !isStandalone() ? "Notifications on iPhone and iPad need KYVON installed to the Home Screen first." : "This browser doesn't support push notifications."));
        } else if (!push.configured) {
            rows.push(h("p", { class: "item-meta" }, "Push notifications aren't set up on this server (reminders still appear in your Inbox)."));
        } else {
            rows.push(h("label", { class: "check field" }, h("input", {
                type: "checkbox",
                checked: push.subscribed,
                onchange: async event => {
                    try {
                        if (event.target.checked) await enablePush(); else await disablePush();
                        message.textContent = event.target.checked ? "Notifications on for this device." : "Notifications off for this device.";
                    } catch (error) {
                        message.textContent = error.message;
                        event.target.checked = !event.target.checked;
                    }
                },
            }), " Notify me on this device"));
        }
        box.replaceChildren(...rows, message);
    }
    onInstallStateChange(render);
    render();
    return box;
}

registerPanel({
    id: "settings",
    label: "Settings",
    async mount(container) {
        noteEl = h("p", { class: "note", role: "status" });
        let data;
        try {
            data = await api("/settings");
        } catch (error) {
            container.append(h("p", { class: "empty" }, error.message));
            return;
        }
        const s = data.settings;
        const i = data.integrations;
        container.append(
            h("p", { class: "item-meta" }, `Time zone in use: ${data.effective_timezone}`),
            noteEl,
            h(
                "div",
                { class: "stack" },
                textField("What should I call you?", "display_name", s.display_name || ""),
                selectField("Answer length", "response_style", s.response_style),
                selectField("Tone", "tone", s.tone),
                selectField("Units", "units", s.units),
                textField("Language", "language", s.language, { maxlength: 30 }),
                selectField("Week starts on", "week_starts_on", s.week_starts_on),
                textField("Time zone (leave as is to use this device's)", "timezone", s.timezone || "", { maxlength: 64 }),
                textField("Anything else I should know about how you like to be helped", "assistant_notes", s.assistant_notes, { multiline: true, maxlength: 500 })
            ),
            h("h3", { class: "section" }, "Assistant"),
            h(
                "div",
                { class: "stack" },
                toggle("Let KYVON propose things to remember (you approve each one)", "allow_memory_proposals", s.allow_memory_proposals),
                toggle("Read replies aloud", "voice_replies", s.voice_replies)
            ),
            h("h3", { class: "section" }, "This device"),
            devicePanel(),
            h("h3", { class: "section" }, "Connected services"),
            h(
                "div",
                { class: "stack" },
                toggle(`Google Calendar${i.calendar.available ? "" : " (not set up on this server)"}`, "calendar_enabled", s.calendar_enabled, !i.calendar.available),
                toggle(`Logseq notes${i.logseq.available ? "" : " (not set up on this server)"}`, "logseq_enabled", s.logseq_enabled, !i.logseq.available),
                toggle(`Hermes helper${i.hermes.available ? "" : " (not set up on this server)"}`, "hermes_enabled", s.hermes_enabled, !i.hermes.available)
            ),
            h("button", { class: "mini danger", text: "Reset to defaults", onclick: async () => {
                if (!window.confirm("Reset all personalisation settings?")) return;
                await api("/settings/reset", { method: "POST" });
                container.replaceChildren();
                this.mount(container);
            } })
        );
    },
});
