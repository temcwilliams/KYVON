// "Notes" panel: search and read the Logseq graph (writes happen through approved chat actions).

import { api } from "./api.js";
import { h } from "./dom.js";
import { registerPanel } from "./panels.js";

let resultsEl = null;

async function search(query) {
    if (query.trim().length < 2) {
        resultsEl.replaceChildren();
        return;
    }
    try {
        const data = await api(`/logseq/search?q=${encodeURIComponent(query)}`);
        if (!data.hits.length) {
            resultsEl.replaceChildren(h("p", { class: "empty" }, "Nothing found."));
            return;
        }
        resultsEl.replaceChildren(
            ...data.hits.map(hit =>
                h(
                    "li",
                    { class: "item" },
                    h(
                        "button",
                        { class: "item-main", onclick: () => openPage(hit.page) },
                        h("span", { class: "item-title" }, hit.page),
                        h("span", { class: "item-meta" }, hit.text)
                    )
                )
            )
        );
    } catch (error) {
        if (error.status !== 401) resultsEl.replaceChildren(h("p", { class: "empty" }, error.message));
    }
}

async function openPage(name) {
    try {
        const data = await api(`/logseq/page?name=${encodeURIComponent(name)}`);
        resultsEl.replaceChildren(
            h("button", { class: "mini", onclick: () => resultsEl.replaceChildren(), text: "Back" }),
            h("h3", { class: "section" }, data.page.name),
            h("pre", { class: "page-text" }, data.page.content),
            data.page.truncated ? h("p", { class: "item-meta" }, "(shortened)") : null
        );
    } catch (error) {
        resultsEl.replaceChildren(h("p", { class: "empty" }, error.message));
    }
}

registerPanel({
    id: "notes",
    label: "Notes",
    async mount(container) {
        let configured = false;
        try {
            configured = (await api("/logseq/status")).configured;
        } catch {
            // Treated as not configured.
        }
        if (!configured) {
            container.append(h("p", { class: "empty" }, "Logseq isn't connected on this server (set KYVON_LOGSEQ_DIR)."));
            return;
        }
        resultsEl = h("ul", { class: "list", "aria-label": "Notes results" });
        container.append(
            h("input", { type: "search", placeholder: "Search your notes", "aria-label": "Search notes", oninput: event => search(event.target.value) }),
            h("p", { class: "item-meta" }, "To save something to your notes, just ask KYVON — you'll be asked to approve it."),
            resultsEl
        );
    },
});
