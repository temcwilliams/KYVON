// Sending messages to KYVON.

import { api } from "./api.js";
import { environmentText } from "./env.js";
import { addMessage, say, setListening, setStatus } from "./ui.js";

const input = document.getElementById("messageInput");

export async function sendMessage() {
    const message = input.value.trim();
    if (!message) return;

    addMessage("You", message, "user");
    input.value = "";
    setStatus("THINKING");
    setListening("PROCESSING");

    try {
        const data = await api("/chat", {
            method: "POST",
            body: { message, environment: environmentText() },
        });
        say(data.response);
    } catch (error) {
        if (error.status !== 401) {
            say("I encountered an error: " + error.message);
        }
    } finally {
        setStatus("ONLINE");
        setListening("STANDBY");
    }
}
