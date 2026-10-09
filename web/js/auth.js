// Sign-in / sign-out, and (hosted mode) sign-up, email verification and password reset.

import { api, setUnauthorizedHandler } from "./api.js";
import { h } from "./dom.js";

const overlay = document.getElementById("login");
const form = document.getElementById("loginForm");
const username = document.getElementById("loginUsername");
const password = document.getElementById("loginPassword");
const errorBox = document.getElementById("loginError");
const loginLinks = document.getElementById("loginLinks");

const signupForm = document.getElementById("signupForm");
const forgotForm = document.getElementById("forgotForm");
const resetForm = document.getElementById("resetForm");
const forms = { login: form, signup: signupForm, forgot: forgotForm, reset: resetForm };

let config = { mode: "personal", signup_open: false, billing: false };
let resetToken = "";
let wasSignedIn = false;  // so a 401 on a first visit is not announced as an expired session

export function getConfig() {
    return config;
}

// What mode the server is in (public, no secrets). Falls back to personal if unreachable.
export async function loadConfig() {
    try {
        config = await api("/config", { notifyUnauthorized: false });
    } catch {
        // Keep the personal-mode defaults: the sign-in form still works.
    }
    return config;
}

export async function currentUser() {
    try {
        const data = await api("/auth/me", { notifyUnauthorized: false });
        wasSignedIn = true;
        return data.user;
    } catch (error) {
        if (error.status === 401) {
            return null;
        }
        throw error;
    }
}

function show(which) {
    for (const [name, el] of Object.entries(forms)) el.hidden = name !== which;
}

export function showLogin(message = "") {
    show("login");
    errorBox.textContent = message;
    const hosted = config.mode === "hosted";
    loginLinks.hidden = !hosted;
    document.getElementById("showSignup").hidden = !config.signup_open;
    username.placeholder = hosted ? "Email or username" : "Username";
    username.setAttribute("aria-label", username.placeholder);
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

function say(box, text, ok = false) {
    box.textContent = text;
    box.classList.toggle("ok", ok);
}

// Links in emails carry a one-time token after '#'. Handle it, then remove it from the address bar.
// Returns true if the page should show the login overlay (verification / reset in progress).
export async function handleEmailLink() {
    const match = window.location.hash.match(/^#(verify|reset)=([A-Za-z0-9_-]+)$/);
    if (!match) return false;
    const [, kind, token] = match;
    window.history.replaceState({}, "", window.location.pathname + window.location.search);
    overlay.hidden = false;
    if (kind === "verify") {
        showLogin();
        try {
            await api("/auth/verify-email", {
                method: "POST", body: { token }, notifyUnauthorized: false,
            });
            say(errorBox, "Email confirmed. You can sign in now.", true);
        } catch (error) {
            say(errorBox, error.message);
        }
    } else {
        resetToken = token;
        show("reset");
        document.getElementById("resetPassword").focus();
    }
    return true;
}

function bindHostedForms() {
    document.getElementById("showSignup").addEventListener("click", () => show("signup"));
    document.getElementById("showForgot").addEventListener("click", () => show("forgot"));
    for (const back of document.querySelectorAll("[data-back]")) {
        back.addEventListener("click", () => showLogin());
    }

    const { privacy_url: privacy, terms_url: terms } = config;
    if (terms || privacy) {
        const link = (url, label) =>
            url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: label }) : label;
        document.getElementById("signupTermsText").replaceChildren(
            "I agree to the ", link(terms, "terms of use"), " and ", link(privacy, "privacy policy"), "."
        );
    }

    signupForm.addEventListener("submit", async event => {
        event.preventDefault();
        const box = document.getElementById("signupMessage");
        say(box, "");
        try {
            const result = await api("/auth/signup", {
                method: "POST",
                body: {
                    email: document.getElementById("signupEmail").value,
                    password: document.getElementById("signupPassword").value,
                    accept_terms: document.getElementById("signupTerms").checked,
                },
                notifyUnauthorized: false,
            });
            document.getElementById("signupPassword").value = "";
            say(box, result.message, true);
        } catch (error) {
            say(box, error.message);
        }
    });

    forgotForm.addEventListener("submit", async event => {
        event.preventDefault();
        const box = document.getElementById("forgotMessage");
        try {
            const result = await api("/auth/forgot-password", {
                method: "POST",
                body: { email: document.getElementById("forgotEmail").value },
                notifyUnauthorized: false,
            });
            say(box, result.message, true);
        } catch (error) {
            say(box, error.message);
        }
    });

    resetForm.addEventListener("submit", async event => {
        event.preventDefault();
        const box = document.getElementById("resetMessage");
        try {
            await api("/auth/reset-password", {
                method: "POST",
                body: { token: resetToken, password: document.getElementById("resetPassword").value },
                notifyUnauthorized: false,
            });
            resetToken = "";
            document.getElementById("resetPassword").value = "";
            showLogin();
            say(errorBox, "Password changed. Sign in with the new one.", true);
        } catch (error) {
            say(box, error.message);
        }
    });
}

// Calls ``onSignedIn`` after a successful login. Returns nothing.
export function initLogin(onSignedIn) {
    setUnauthorizedHandler(() =>
        showLogin(wasSignedIn ? "Session expired. Please sign in again." : "")
    );
    if (config.mode === "hosted") bindHostedForms();

    form.addEventListener("submit", async event => {
        event.preventDefault();
        errorBox.textContent = "";
        errorBox.classList.remove("ok");
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
            wasSignedIn = true;
            hideLogin();
            onSignedIn();
        } catch (error) {
            errorBox.textContent = error.message;
            password.value = "";
        }
    });
}
