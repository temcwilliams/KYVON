// Sending messages and rendering conversation history.

import { ApiError, api, stream } from "./api.js";
import { addMessage, clearConversation, say, setListening, setStatus } from "./ui.js";
import { emit, state } from "./state.js";

const input = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");

let controller = null;

export function renderHistory(messages) {
    clearConversation();
    if (!messages.length) {
        say("Systems initialized. How may I assist?");
        return;
    }
    for (const message of messages) {
        if (message.kind === "event") {
            addMessage("System", message.content, "kyvon");
        } else if (message.role === "user") {
            addMessage("You", message.content, "user");
        } else {
            addMessage("Kyvon", message.content, "kyvon", { status: message.status });
        }
    }
}

export async function openConversation(id) {
    const data = await api(`/conversations/${id}/messages`);
    state.conversationId = id;
    renderHistory(data.messages);
    emit("conversation:opened", id);
}

export function newConversation() {
    if (controller) controller.abort();
    state.conversationId = null;
    clearConversation();
    say("Systems initialized. How may I assist?");
    emit("conversation:opened", null);
    input.focus();
}

export function cancelReply() {
    if (controller) controller.abort();
}

function setBusy(busy) {
    state.busy = busy;
    sendButton.textContent = busy ? "STOP" : "SEND";
    sendButton.setAttribute("aria-label", busy ? "Stop response" : "Send message");
}

export async function sendMessage() {
    if (state.busy) {
        cancelReply();
        return;
    }
    const message = input.value.trim();
    if (!message) return;

    addMessage("You", message, "user");
    input.value = "";
    setStatus("THINKING");
    setListening("PROCESSING");
    setBusy(true);

    controller = new AbortController();
    let reply = null;
    let failed = false;

    try {
        await stream(
            "/chat/stream",
            { message, conversation_id: state.conversationId },
            (type, data) => {
                if (type === "start") {
                    state.conversationId = data.conversation.id;
                } else if (type === "delta") {
                    if (!reply) reply = addMessage("Kyvon", "", "kyvon");
                    reply.append(data.text);
                } else if (type === "done") {
                    if (!reply) reply = addMessage("Kyvon", data.message.content, "kyvon");
                    emit("turn:done", data);
                } else if (type === "error") {
                    failed = true;
                    if (!reply) reply = addMessage("Kyvon", "", "kyvon");
                    reply.append((reply.el.textContent.endsWith(":") ? "" : "\n") +
                        "I encountered an error: " + data.message);
                    reply.markError();
                }
            },
            { signal: controller.signal }
        );
    } catch (error) {
        if (error.name === "AbortError") {
            if (reply) reply.markInterrupted();
        } else if (!(error instanceof ApiError && error.status === 401)) {
            say("I encountered an error: " + error.message);
        }
    } finally {
        controller = null;
        setBusy(false);
        setStatus("ONLINE");
        setListening("STANDBY");
        emit("conversations:changed");
        if (failed) input.focus();
    }
}
