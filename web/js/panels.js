// The side drawer: a tab bar plus one panel at a time. Feature modules register panels.

import { clear, h } from "./dom.js";

const panels = [];
let active = null;
let tabs;
let body;
let drawer;
let toggle;

export function registerPanel(panel) {
    panels.push(panel);
}

export function initDrawer() {
    drawer = document.getElementById("drawer");
    tabs = document.getElementById("tabs");
    body = document.getElementById("panel");
    toggle = document.getElementById("menuButton");

    toggle.addEventListener("click", () => setDrawerOpen(!drawer.classList.contains("open")));
    document.getElementById("drawerClose").addEventListener("click", () => setDrawerOpen(false));
    document.getElementById("scrim").addEventListener("click", () => setDrawerOpen(false));
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") setDrawerOpen(false);
    });

    tabs.replaceChildren(
        ...panels.map(panel =>
            h("button", {
                class: "tab",
                role: "tab",
                id: `tab-${panel.id}`,
                "aria-controls": "panel",
                onclick: () => openPanel(panel.id),
                text: panel.label,
            })
        )
    );
    if (panels.length) openPanel(panels[0].id);
}

export function setDrawerOpen(open) {
    drawer.classList.toggle("open", open);
    document.getElementById("scrim").classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
}

export function openPanel(id) {
    const panel = panels.find(p => p.id === id);
    if (!panel) return;
    active = panel;
    for (const tab of tabs.children) {
        const selected = tab.id === `tab-${id}`;
        tab.setAttribute("aria-selected", String(selected));
        tab.classList.toggle("active", selected);
    }
    body.setAttribute("aria-labelledby", `tab-${id}`);
    clear(body);
    panel.mount(body);
}

export function refreshActivePanel() {
    if (active && active.refresh) active.refresh();
}
