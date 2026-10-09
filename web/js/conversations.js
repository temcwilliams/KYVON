// "Chats" panel: list, switch, rename, archive and delete conversations.

import { api } from "./api.js";
import { newConversation, openConversation } from "./chat.js";
import { formatDate, h } from "./dom.js";
import { registerPanel, setDrawerOpen } from "./panels.js";
import { on, state } from "./state.js";
import { say } from "./ui.js";

let listEl = null;
let showArchived = false;

async function load() {
    if (!listEl) return;
    try {
        const data = await api(`/conversations?archived=${showArchived ? 1 : 0}`);
        render(data.conversations);
    } catch (error) {
        if (error.status !== 401) listEl.replaceChildren(h("p", { class: "empty" }, error.message));
    }
}

function render(conversations) {
    if (!conversations.length) {
        listEl.replaceChildren(
            h("p", { class: "empty" }, showArchived ? "No archived chats." : "No conversations yet.")
        );
        return;
    }
    listEl.replaceChildren(
        ...conversations.map(c =>
            h(
                "li",
                { class: `item${c.id === state.conversationId ? " current" : ""}` },
                h(
                    "button",
                    {
                        class: "item-main",
                        onclick: async () => {
                            await openConversation(c.id);
                            setDrawerOpen(false);
                        },
                    },
                    h("span", { class: "item-title" }, c.title),
                    h("span", { class: "item-meta" }, `${formatDate(c.updated_at)} · ${c.message_count ?? 0} msgs`)
                ),
                h(
                    "span",
                    { class: "item-actions" },
                    h("button", { class: "mini", "aria-label": `Rename ${c.title}`, onclick: () => rename(c), text: "Rename" }),
                    h("button", {
                        class: "mini",
                        "aria-label": `${c.archived ? "Restore" : "Archive"} ${c.title}`,
                        onclick: () => archive(c),
                        text: c.archived ? "Restore" : "Archive",
                    }),
                    h("button", { class: "mini danger", "aria-label": `Delete ${c.title}`, onclick: () => remove(c), text: "Delete" })
                )
            )
        )
    );
}

async function rename(c) {
    const title = window.prompt("Conversation title", c.title);
    if (!title || !title.trim()) return;
    try {
        await api(`/conversations/${c.id}`, { method: "PATCH", body: { title } });
        load();
    } catch (error) {
        say(`Unable to rename: ${error.message}`);
    }
}

async function archive(c) {
    try {
        await api(`/conversations/${c.id}`, { method: "PATCH", body: { archived: !c.archived } });
        if (c.id === state.conversationId && !c.archived) newConversation();
        load();
    } catch (error) {
        say(`Unable to update: ${error.message}`);
    }
}

async function remove(c) {
    if (!window.confirm(`Delete "${c.title}" and all of its messages?`)) return;
    try {
        await api(`/conversations/${c.id}`, { method: "DELETE" });
        if (c.id === state.conversationId) newConversation();
        load();
    } catch (error) {
        say(`Unable to delete: ${error.message}`);
    }
}

registerPanel({
    id: "chats",
    label: "Chats",
    mount(container) {
        listEl = h("ul", { class: "list", "aria-label": "Conversations" });
        container.append(
            h(
                "div",
                { class: "toolbar" },
                h("button", {
                    onclick: () => {
                        newConversation();
                        setDrawerOpen(false);
                    },
                    text: "New chat",
                }),
                h(
                    "label",
                    { class: "check" },
                    h("input", {
                        type: "checkbox",
                        onchange: event => {
                            showArchived = event.target.checked;
                            load();
                        },
                    }),
                    " Archived"
                )
            ),
            listEl
        );
        load();
    },
    refresh: load,
});

on("conversations:changed", load);
on("conversation:opened", load);
