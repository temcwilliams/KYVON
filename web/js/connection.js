// Connection state: notices when the device or the server is unreachable and reconnects.

import { setStatus } from "./ui.js";
import { emit, on, state } from "./state.js";

const banner = document.getElementById("offlineBanner");
const sendButton = document.getElementById("sendButton");
const HEALTH = "/api/v1/health";
const MIN_DELAY = 2000;
const MAX_DELAY = 30000;

let online = navigator.onLine;
let timer = null;
let delay = MIN_DELAY;

export function isOnline() {
    return online;
}

function apply() {
    banner.hidden = online;
    sendButton.disabled = !online && !state.busy;
    if (!online) setStatus("OFFLINE");
}

function setOnline(value) {
    if (value === online) return;
    online = value;
    apply();
    if (online) {
        delay = MIN_DELAY;
        setStatus("ONLINE");
        emit("connection:restored");
    } else {
        emit("connection:lost");
        scheduleProbe();
    }
}

async function probe() {
    timer = null;
    try {
        const response = await fetch(HEALTH, { cache: "no-store" });
        if (response.ok) {
            setOnline(true);
            return;
        }
    } catch {
        // Still unreachable.
    }
    delay = Math.min(delay * 2, MAX_DELAY);
    scheduleProbe();
}

function scheduleProbe() {
    if (timer) return;
    timer = window.setTimeout(probe, delay);
}

// Call when a request failed for network reasons, so we notice quickly.
export function reportNetworkFailure() {
    setOnline(false);
}

export function initConnection() {
    window.addEventListener("offline", () => setOnline(false));
    window.addEventListener("online", () => {
        delay = MIN_DELAY;
        probe();
    });
    on("turn:done", () => setOnline(true));
    apply();
    if (!online) scheduleProbe();
}
