// Application entry point: sign-in gate, then wire the modules together.

import { currentUser, hideLogin, initLogin, logout, showLogin } from "./auth.js";
import { newConversation, openConversation, sendMessage } from "./chat.js";
import "./conversations.js";
import "./tasks.js";
import { handleOAuthReturn } from "./calendar.js";
import { api } from "./api.js";
import { runDiagnostics } from "./diagnostics.js";
import { requestLocation } from "./env.js";
import { openMemoryPanel } from "./memory.js";
import { initDrawer } from "./panels.js";
import { state } from "./state.js";
import { clearConversation, say, setStatus } from "./ui.js";
import { initVoice } from "./voice.js";

const input = document.getElementById("messageInput");
let started = false;

async function restoreLastConversation() {
    try {
        const data = await api("/conversations?limit=1");
        if (data.conversations.length) {
            await openConversation(data.conversations[0].id);
        }
    } catch {
        // Starting with an empty view is fine.
    }
}

function start() {
    setStatus("ONLINE");
    if (started) return;
    started = true;

    restoreLastConversation();
    handleOAuthReturn();
    runDiagnostics();
    // Ask the device for location permission.
    requestLocation();
}

function bindControls() {
    document.getElementById("sendButton").addEventListener("click", sendMessage);
    input.addEventListener("keydown", event => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });

    document.getElementById("systemButton").addEventListener("click", () =>
        runDiagnostics({ deep: true })
    );
    document.getElementById("memoryButton").addEventListener("click", openMemoryPanel);
    document.getElementById("clearButton").addEventListener("click", () => {
        newConversation();
    });
    document.getElementById("logoutButton").addEventListener("click", async () => {
        await logout();
        started = false;
        state.conversationId = null;
        clearConversation();
        say("Signed out.");
        setStatus("SIGNED OUT");
        showLogin();
    });

    initVoice(sendMessage);
}

async function boot() {
    bindControls();
    initDrawer();
    initLogin(start);

    try {
        const user = await currentUser();
        if (user) {
            hideLogin();
            start();
        } else {
            setStatus("SIGN IN");
            showLogin();
        }
    } catch {
        setStatus("OFFLINE");
        showLogin("Unable to reach the KYVON server.");
    }
}

boot();
