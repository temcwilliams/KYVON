// Conversation view helpers shared by the other modules.

import { h } from "./dom.js";

const conversation = document.getElementById("conversation");
const status = document.getElementById("status");
const listening = document.getElementById("listening");

const STATUS_NOTES = {
    partial: " (interrupted)",
    error: "",
};

// Adds a message and returns a handle so streamed text can be appended.
export function addMessage(speaker, text, type, { status: messageStatus = "complete" } = {}) {
    const body = h("span", { class: "message-text" }, text);
    const note = h("span", { class: "message-note" });
    const el = h(
        "div",
        { class: `message ${type}-message${messageStatus === "error" ? " message-error" : ""}` },
        speaker ? h("span", { class: "speaker" }, `${speaker}:`) : null,
        speaker ? " " : null,
        body,
        note
    );
    if (STATUS_NOTES[messageStatus]) note.textContent = STATUS_NOTES[messageStatus];
    conversation.appendChild(el);
    scrollToEnd();

    return {
        el,
        append(more) {
            body.textContent += more;
            scrollToEnd();
        },
        set(value) {
            body.textContent = value;
            scrollToEnd();
        },
        markError() {
            el.classList.add("message-error");
        },
        markInterrupted() {
            note.textContent = STATUS_NOTES.partial;
        },
    };
}

export function say(text) {
    return addMessage("Kyvon", text, "kyvon");
}

export function scrollToEnd() {
    conversation.scrollTop = conversation.scrollHeight;
}

export function setStatus(text) {
    status.textContent = text;
}

export function setListening(text) {
    listening.textContent = text;
}

export function clearConversation() {
    conversation.replaceChildren();
}
