// "Memory" panel: view, search, add, edit and delete long-term memories.

import { api } from "./api.js";
import { formatDate, h } from "./dom.js";
import { openPanel, registerPanel, setDrawerOpen } from "./panels.js";

let listEl = null;
let messageEl = null;
let categories = ["general"];
let filters = { q: "", category: "" };

function note(text, isError = false) {
    if (!messageEl) return;
    messageEl.textContent = text;
    messageEl.classList.toggle("error", isError);
}

async function load() {
    if (!listEl) return;
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    else if (filters.category) params.set("category", filters.category);
    try {
        const data = await api(`/memories?${params}`);
        render(data.memories);
    } catch (error) {
        if (error.status !== 401) note(error.message, true);
    }
}

function render(memories) {
    if (!memories.length) {
        listEl.replaceChildren(
            h("p", { class: "empty" }, filters.q ? "Nothing matches that search." : "No memories yet.")
        );
        return;
    }
    listEl.replaceChildren(...memories.map(renderItem));
}

function renderItem(m) {
    const meta = `${m.category} · importance ${m.importance} · ${m.source} · ${formatDate(m.created_at)}`;
    const item = h(
        "li",
        { class: "item" },
        h("div", { class: "item-body" }, h("span", { class: "item-title" }, m.memory), h("span", { class: "item-meta" }, meta)),
        h(
            "span",
            { class: "item-actions" },
            h("button", { class: "mini", onclick: () => edit(item, m), text: "Edit", "aria-label": "Edit memory" }),
            h("button", { class: "mini danger", onclick: () => remove(m), text: "Delete", "aria-label": "Delete memory" })
        )
    );
    return item;
}

function categorySelect(selected) {
    return h(
        "select",
        { "aria-label": "Category" },
        categories.map(c => h("option", { value: c, selected: c === selected }, c))
    );
}

function importanceSelect(selected) {
    return h(
        "select",
        { "aria-label": "Importance" },
        [1, 2, 3, 4, 5].map(n => h("option", { value: String(n), selected: n === selected }, `Importance ${n}`))
    );
}

function edit(item, m) {
    const text = h("input", { type: "text", value: m.memory, "aria-label": "Memory text", maxlength: "500" });
    const category = categorySelect(m.category);
    const importance = importanceSelect(m.importance);
    const form = h(
        "form",
        {
            class: "stack",
            onsubmit: async event => {
                event.preventDefault();
                try {
                    await api(`/memories/${m.id}`, {
                        method: "PATCH",
                        body: { text: text.value, category: category.value, importance: Number(importance.value) },
                    });
                    note("Memory updated.");
                    load();
                } catch (error) {
                    note(error.message, true);
                }
            },
        },
        text,
        h("div", { class: "row" }, category, importance),
        h(
            "div",
            { class: "row" },
            h("button", { type: "submit", class: "mini", text: "Save" }),
            h("button", { type: "button", class: "mini", onclick: load, text: "Cancel" })
        )
    );
    item.replaceChildren(form);
    text.focus();
}

async function remove(m) {
    if (!window.confirm(`Forget this?\n\n${m.memory}`)) return;
    try {
        await api(`/memories/${m.id}`, { method: "DELETE" });
        note("Memory deleted.");
        load();
    } catch (error) {
        note(error.message, true);
    }
}

async function add(event, text, category, importance) {
    event.preventDefault();
    try {
        const data = await api("/memories", {
            method: "POST",
            body: { text: text.value, category: category.value, importance: Number(importance.value) },
        });
        text.value = "";
        note(data.duplicate ? "I already had that memory." : "Memory saved.");
        load();
    } catch (error) {
        note(error.message, true);
    }
}

export function openMemoryPanel() {
    openPanel("memory");
    setDrawerOpen(true);
}

registerPanel({
    id: "memory",
    label: "Memory",
    async mount(container) {
        try {
            categories = (await api("/memories/categories")).categories;
        } catch {
            // Keep the default list.
        }
        filters = { q: "", category: "" };
        listEl = h("ul", { class: "list", "aria-label": "Saved memories" });
        messageEl = h("p", { class: "note", role: "status" });

        const text = h("input", { type: "text", placeholder: "Something for KYVON to remember", "aria-label": "New memory", maxlength: "500", required: true });
        const category = categorySelect("general");
        const importance = importanceSelect(3);

        const search = h("input", {
            type: "search",
            placeholder: "Search memories",
            "aria-label": "Search memories",
            oninput: event => {
                filters.q = event.target.value.trim();
                load();
            },
        });
        const filter = h(
            "select",
            {
                "aria-label": "Filter by category",
                onchange: event => {
                    filters.category = event.target.value;
                    load();
                },
            },
            h("option", { value: "" }, "All categories"),
            categories.map(c => h("option", { value: c }, c))
        );

        container.append(
            h("form", { class: "stack", onsubmit: e => add(e, text, category, importance) }, text, h("div", { class: "row" }, category, importance), h("button", { type: "submit", text: "Add memory" })),
            messageEl,
            h("div", { class: "row" }, search, filter),
            listEl
        );
        load();
    },
    refresh: load,
});
