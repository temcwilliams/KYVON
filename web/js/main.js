// Application entry point: sign-in gate, then wire the modules together.

import { currentUser, handleEmailLink, hideLogin, initLogin, loadConfig, logout, showLogin } from "./auth.js";
import { registerAccountPanel } from "./account.js";
import { newConversation, openConversation, sendMessage } from "./chat.js";
import "./conversations.js";
import "./tasks.js";
import "./notes.js";
import "./automations.js";
import "./admin.js";
import { reportTimezone } from "./settings.js";
import { startPolling, stopPolling } from "./notifications.js";
import { handleOAuthReturn } from "./calendar.js";
import { api } from "./api.js";
import { runDiagnostics } from "./diagnostics.js";
import { initConnection } from "./connection.js";
import { requestLocation } from "./env.js";
import { registerServiceWorker } from "./pwa.js";
import { openMemoryPanel } from "./memory.js";
import { initDrawer } from "./panels.js";
import { state } from "./state.js";
import { clearConversation, say, setStatus } from "./ui.js";
import { initVoice, refreshVoiceConfig } from "./voice.js";

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

    if (new URLSearchParams(window.location.search).get("new") === "1") {
        newConversation();
        window.history.replaceState({}, "", window.location.pathname);
    } else {
        restoreLastConversation();
    }
    reportTimezone();
    refreshVoiceConfig();
    startPolling();
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
        stopPolling();
        state.conversationId = null;
        clearConversation();
        say("Signed out.");
        setStatus("SIGNED OUT");
        showLogin();
    });

    initVoice(sendMessage);
}

async function boot() {
    registerServiceWorker();
    initConnection();
    bindControls();
    const config = await loadConfig();  // personal or hosted: decides which screens exist
    if (config.mode === "hosted") registerAccountPanel();
    initDrawer();
    initLogin(start);

    // A link from an email (confirm address / reset password) takes over the sign-in screen,
    // including when the app is already open and only the part after '#' changes.
    window.addEventListener("hashchange", () => {
        handleEmailLink().then(handled => handled && setStatus("SIGN IN"));
    });
    if (await handleEmailLink()) {
        setStatus("SIGN IN");
        return;
    }

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
