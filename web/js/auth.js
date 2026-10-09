// Sign-in / sign-out and the login overlay.

import { api, setUnauthorizedHandler } from "./api.js";

const overlay = document.getElementById("login");
const form = document.getElementById("loginForm");
const username = document.getElementById("loginUsername");
const password = document.getElementById("loginPassword");
const errorBox = document.getElementById("loginError");

export async function currentUser() {
    try {
        const data = await api("/auth/me", { notifyUnauthorized: false });
        return data.user;
    } catch (error) {
        if (error.status === 401) {
            return null;
        }
        throw error;
    }
}

export function showLogin(message = "") {
    errorBox.textContent = message;
    overlay.hidden = false;
    username.focus();
}

export function hideLogin() {
    overlay.hidden = true;
    password.value = "";
    errorBox.textContent = "";
}

export async function logout() {
    try {
        await api("/auth/logout", { method: "POST", notifyUnauthorized: false });
    } catch {
        // Already signed out; nothing to do.
    }
}

// Calls ``onSignedIn`` after a successful login. Returns nothing.
export function initLogin(onSignedIn) {
    setUnauthorizedHandler(() => showLogin("Session expired. Please sign in again."));

    form.addEventListener("submit", async event => {
        event.preventDefault();
        errorBox.textContent = "";
        try {
            await api("/auth/login", {
                method: "POST",
                body: {
                    username: username.value,
                    password: password.value,
                    cookie: true,
                    device_name: "Web browser",
                },
                notifyUnauthorized: false,
            });
            hideLogin();
            onSignedIn();
        } catch (error) {
            errorBox.textContent = error.message;
            password.value = "";
        }
    });
}
