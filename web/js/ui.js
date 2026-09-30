// DOM helpers shared by the other modules.

const conversation = document.getElementById("conversation");
const status = document.getElementById("status");
const listening = document.getElementById("listening");

export function addMessage(speaker, text, type) {
    const message = document.createElement("div");
    message.className = `message ${type}-message`;

    const who = document.createElement("span");
    who.className = "speaker";
    who.textContent = `${speaker}:`;

    // textContent (never innerHTML) so model or server text cannot inject markup.
    const body = document.createElement("span");
    body.textContent = text;

    message.append(who, " ", body);
    conversation.appendChild(message);
    conversation.scrollTop = conversation.scrollHeight;
}

export function say(text) {
    addMessage("Kyvon", text, "kyvon");
}

export function setStatus(text) {
    status.textContent = text;
}

export function setListening(text) {
    listening.textContent = text;
}

export function clearConversation() {
    conversation.replaceChildren();
    say("Conversation cleared.");
}
