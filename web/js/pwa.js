// Installability, the service worker, and push subscription.

import { api } from "./api.js";

let installPrompt = null;
const listeners = new Set();

export function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(error => {
            console.warn("Service worker registration failed:", error);
        });
    });
}

window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    installPrompt = event;
    for (const fn of listeners) fn();
});

window.addEventListener("appinstalled", () => {
    installPrompt = null;
    for (const fn of listeners) fn();
});

export function onInstallStateChange(fn) {
    listeners.add(fn);
}

export function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
}

export function canPromptInstall() {
    return installPrompt !== null;
}

export async function promptInstall() {
    if (!installPrompt) return false;
    installPrompt.prompt();
    const choice = await installPrompt.userChoice;
    installPrompt = null;
    return choice.outcome === "accepted";
}

export function isIOS() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

// ---- push -----------------------------------------------------------------

function urlBase64ToUint8Array(base64) {
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, c => c.charCodeAt(0));
}

export async function pushStatus() {
    const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    let server = { configured: false };
    try {
        server = await api("/push/public-key");
    } catch {
        // Not signed in or unreachable.
    }
    let subscribed = false;
    if (supported) {
        const registration = await navigator.serviceWorker.getRegistration();
        subscribed = Boolean(registration && (await registration.pushManager.getSubscription()));
    }
    return { supported, configured: server.configured, subscribed, permission: supported ? Notification.permission : "denied" };
}

export async function enablePush() {
    const { public_key: key } = await api("/push/public-key");
    const permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("Notifications were not allowed.");
    const registration = await navigator.serviceWorker.ready;
    const subscription =
        (await registration.pushManager.getSubscription()) ||
        (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) }));
    const json = subscription.toJSON();
    await api("/push/subscribe", { method: "POST", body: { endpoint: json.endpoint, keys: json.keys } });
}

export async function disablePush() {
    const registration = await navigator.serviceWorker.getRegistration();
    const subscription = registration && (await registration.pushManager.getSubscription());
    if (!subscription) return;
    await api("/push/subscribe", { method: "DELETE", body: { endpoint: subscription.endpoint } });
    await subscription.unsubscribe();
}
