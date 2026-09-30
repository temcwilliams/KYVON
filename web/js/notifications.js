// Inbox: notifications from reminders and scheduled tasks, plus the unread badge in the header.

import { api } from "./api.js";
import { formatDate, h } from "./dom.js";
import { openConversation } from "./chat.js";
import { openPanel, registerPanel, setDrawerOpen } from "./panels.js";

const badge = document.getElementById("bellBadge");
const bell = document.getElementById("bellButton");
const POLL_MS = 60_000;

let listEl = null;
let timer = null;

function setBadge(count) {
    badge.textContent = count > 99 ? "99+" : String(count);
    badge.hidden = count === 0;
    bell.setAttribute("aria-label", count ? `Inbox, ${count} unread` : "Inbox");
}

export async function refreshBadge() {
    try {
        const data = await api("/notifications?unread=1&limit=1");
        setBadge(data.unread_count);
    } catch {
        // The badge is a convenience.
    }
}

export function startPolling() {
    stopPolling();
    refreshBadge();
    timer = window.setInterval(refreshBadge, POLL_MS);
    document.addEventListener("visibilitychange", onVisible);
}

export function stopPolling() {
    if (timer) window.clearInterval(timer);
    timer = null;
    document.removeEventListener("visibilitychange", onVisible);
    setBadge(0);
}

function onVisible() {
    if (!document.hidden) refreshBadge();
}

async function load() {
    if (!listEl) return;
    try {
        const data = await api("/notifications?limit=50");
        setBadge(data.unread_count);
        if (!data.notifications.length) {
            listEl.replaceChildren(h("p", { class: "empty" }, "Nothing here yet. Reminders and results of scheduled tasks appear in this inbox."));
            return;
        }
        listEl.replaceChildren(...data.notifications.map(render));
    } catch (error) {
        if (error.status !== 401) listEl.replaceChildren(h("p", { class: "empty" }, error.message));
    }
}

function render(note) {
    const open = note.conversation_id
        ? h("button", {
              class: "mini",
              text: "Open chat",
              onclick: async () => {
                  await openConversation(note.conversation_id);
                  setDrawerOpen(false);
              },
          })
        : null;
    return h(
        "li",
        { class: `item${note.read ? "" : " unread"}` },
        h(
            "div",
            { class: "item-body" },
            h("span", { class: "item-title" }, note.title),
            h("span", { class: "note-body" }, note.body),
            h("span", { class: "item-meta" }, formatDate(note.created_at))
        ),
        h(
            "span",
            { class: "item-actions" },
            note.read
                ? null
                : h("button", {
                      class: "mini",
                      text: "Mark read",
                      onclick: async () => {
                          await api(`/notifications/${note.id}/read`, { method: "POST" });
                          load();
                      },
                  }),
            open,
            h("button", {
                class: "mini danger",
                text: "Delete",
                "aria-label": `Delete ${note.title}`,
                onclick: async () => {
                    await api(`/notifications/${note.id}`, { method: "DELETE" });
                    load();
                },
            })
        )
    );
}

registerPanel({
    id: "inbox",
    label: "Inbox",
    mount(container) {
        listEl = h("ul", { class: "list", "aria-label": "Notifications" });
        container.append(
            h("div", { class: "toolbar" }, h("button", { class: "mini", text: "Mark all read", onclick: async () => {
                await api("/notifications/read-all", { method: "POST" });
                load();
            } })),
            listEl
        );
        load();
    },
    refresh: load,
});

bell.addEventListener("click", () => {
    openPanel("inbox");
    setDrawerOpen(true);
});
