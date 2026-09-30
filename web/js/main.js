// Application entry point: sign-in gate, then wire the modules together.

import { currentUser, hideLogin, initLogin, logout, showLogin } from "./auth.js";
import { sendMessage } from "./chat.js";
import { runDiagnostics } from "./diagnostics.js";
import { requestLocation } from "./env.js";
import { showMemory } from "./memory.js";
import { clearConversation, setStatus } from "./ui.js";
import { initVoice } from "./voice.js";

const input = document.getElementById("messageInput");
let started = false;

function start() {
    setStatus("ONLINE");
    if (started) return;
    started = true;

    runDiagnostics();
    // Ask the device for location permission.
    requestLocation();
}

function bindControls() {
    document.getElementById("sendButton").addEventListener("click", sendMessage);
    input.addEventListener("keydown", event => {
        if (event.key === "Enter") sendMessage();
    });

    document.getElementById("systemButton").addEventListener("click", () =>
        runDiagnostics({ deep: true })
    );
    document.getElementById("memoryButton").addEventListener("click", showMemory);
    document.getElementById("clearButton").addEventListener("click", clearConversation);
    document.getElementById("logoutButton").addEventListener("click", async () => {
        await logout();
        started = false;
        setStatus("SIGNED OUT");
        showLogin();
    });

    initVoice(sendMessage);
}

async function boot() {
    bindControls();
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
