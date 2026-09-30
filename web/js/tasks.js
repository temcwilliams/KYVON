// "Tasks" panel.

import { api } from "./api.js";
import { h } from "./dom.js";
import { registerPanel } from "./panels.js";
import { on } from "./state.js";

const PRIORITIES = [
    ["1", "Low"],
    ["2", "Normal"],
    ["3", "High"],
    ["4", "Urgent"],
];
const RECURRENCES = ["", "daily", "weekly", "monthly", "yearly"];

let listEl = null;
let noteEl = null;
let status = "open";

function note(text, isError = false) {
    if (!noteEl) return;
    noteEl.textContent = text;
    noteEl.classList.toggle("error", isError);
}

async function load() {
    if (!listEl) return;
    try {
        const data = await api(`/tasks?status=${status}`);
        render(data.tasks);
    } catch (error) {
        if (error.status !== 401) note(error.message, true);
    }
}

function dueText(task) {
    if (!task.due) return "No due date";
    const date = new Date(task.due);
    const text = task.due_has_time
        ? date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
        : new Date(`${task.due}T00:00`).toLocaleDateString([], { dateStyle: "medium" });
    return (task.overdue ? "Overdue · " : "Due ") + text;
}

function render(tasks) {
    if (!tasks.length) {
        listEl.replaceChildren(h("p", { class: "empty" }, status === "done" ? "Nothing completed yet." : "No tasks. Add one above, or ask KYVON."));
        return;
    }
    listEl.replaceChildren(...tasks.map(renderTask));
}

function renderTask(task) {
    const done = task.status === "done";
    const check = h("input", {
        type: "checkbox",
        checked: done,
        "aria-label": done ? `Reopen ${task.title}` : `Complete ${task.title}`,
        onchange: () => toggle(task),
    });
    const item = h(
        "li",
        { class: `item task${done ? " done" : ""}${task.overdue ? " overdue" : ""}` },
        h(
            "div",
            { class: "task-row" },
            check,
            h(
                "div",
                { class: "item-body" },
                h("span", { class: "item-title" }, task.title),
                h(
                    "span",
                    { class: "item-meta" },
                    `${task.priority_name} · ${dueText(task)}${task.recurrence ? ` · repeats ${task.recurrence}` : ""}`
                ),
                task.notes ? h("span", { class: "item-meta" }, task.notes) : null
            )
        ),
        h(
            "span",
            { class: "item-actions" },
            h("button", { class: "mini", onclick: () => edit(item, task), text: "Edit", "aria-label": `Edit ${task.title}` }),
            h("button", { class: "mini danger", onclick: () => remove(task), text: "Delete", "aria-label": `Delete ${task.title}` })
        )
    );
    return item;
}

async function toggle(task) {
    try {
        await api(`/tasks/${task.id}/${task.status === "done" ? "reopen" : "complete"}`, { method: "POST" });
        load();
    } catch (error) {
        note(error.message, true);
        load();
    }
}

async function remove(task) {
    if (!window.confirm(`Delete "${task.title}"?`)) return;
    try {
        await api(`/tasks/${task.id}`, { method: "DELETE" });
        load();
    } catch (error) {
        note(error.message, true);
    }
}

function localInputValue(task) {
    if (!task.due) return "";
    return task.due_has_time ? task.due.slice(0, 16) : task.due;
}

function fields(task = {}) {
    const title = h("input", { type: "text", value: task.title || "", placeholder: "What needs doing?", "aria-label": "Task title", maxlength: "200", required: true });
    const due = h("input", { type: "datetime-local", value: task.due && task.due_has_time ? localInputValue(task) : "", "aria-label": "Due date and time" });
    const priority = h(
        "select",
        { "aria-label": "Priority" },
        PRIORITIES.map(([value, label]) => h("option", { value, selected: value === String(task.priority || 2) }, label))
    );
    const repeat = h(
        "select",
        { "aria-label": "Repeat" },
        RECURRENCES.map(value => h("option", { value, selected: value === (task.recurrence || "") }, value ? `Repeats ${value}` : "No repeat"))
    );
    const notes = h("input", { type: "text", value: task.notes || "", placeholder: "Notes (optional)", "aria-label": "Notes", maxlength: "2000" });
    return { title, due, priority, repeat, notes };
}

function payload(f) {
    return {
        title: f.title.value,
        notes: f.notes.value,
        priority: Number(f.priority.value),
        due: f.due.value || null,
        recurrence: f.repeat.value || null,
    };
}

function edit(item, task) {
    const f = fields(task);
    const form = h(
        "form",
        {
            class: "stack",
            onsubmit: async event => {
                event.preventDefault();
                try {
                    await api(`/tasks/${task.id}`, { method: "PATCH", body: payload(f) });
                    note("Task updated.");
                    load();
                } catch (error) {
                    note(error.message, true);
                }
            },
        },
        f.title,
        f.notes,
        f.due,
        h("div", { class: "row" }, f.priority, f.repeat),
        h("div", { class: "row" }, h("button", { type: "submit", class: "mini", text: "Save" }), h("button", { type: "button", class: "mini", onclick: load, text: "Cancel" }))
    );
    item.replaceChildren(form);
    f.title.focus();
}

registerPanel({
    id: "tasks",
    label: "Tasks",
    mount(container) {
        listEl = h("ul", { class: "list", "aria-label": "Tasks" });
        noteEl = h("p", { class: "note", role: "status" });
        const f = fields();
        const add = h(
            "form",
            {
                class: "stack",
                onsubmit: async event => {
                    event.preventDefault();
                    try {
                        await api("/tasks", { method: "POST", body: payload(f) });
                        f.title.value = "";
                        f.notes.value = "";
                        f.due.value = "";
                        note("Task added.");
                        load();
                    } catch (error) {
                        note(error.message, true);
                    }
                },
            },
            f.title,
            f.due,
            h("div", { class: "row" }, f.priority, f.repeat),
            h("button", { type: "submit", text: "Add task" })
        );
        const filter = h(
            "select",
            {
                "aria-label": "Show",
                onchange: event => {
                    status = event.target.value;
                    load();
                },
            },
            [
                ["open", "Open"],
                ["done", "Completed"],
                ["all", "All"],
            ].map(([value, label]) => h("option", { value, selected: value === status }, label))
        );
        container.append(add, noteEl, h("div", { class: "row" }, filter), listEl);
        load();
    },
    refresh: load,
});

// Tasks change when KYVON creates them in a conversation.
on("turn:done", () => load());
