// Thin wrapper around fetch for the KYVON API (/api/v1).
//
// Authentication is an HttpOnly cookie set by the server, so this code never
// sees the session token. For state-changing requests the CSRF token cookie
// (readable on purpose) is echoed back in a header.

const BASE = "/api/v1";

export class ApiError extends Error {
    constructor(message, status, code) {
        super(message);
        this.status = status;
        this.code = code;
    }
}

let onUnauthorized = () => {};

export function setUnauthorizedHandler(handler) {
    onUnauthorized = handler;
}

function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)kyvon_csrf=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
}

export async function api(path, { method = "GET", body, notifyUnauthorized = true } = {}) {
    const headers = {};
    if (body !== undefined) {
        headers["Content-Type"] = "application/json";
    }
    if (method !== "GET" && method !== "HEAD") {
        headers["X-CSRF-Token"] = csrfToken();
    }

    let response;
    try {
        response = await fetch(BASE + path, {
            method,
            headers,
            credentials: "same-origin",
            body: body === undefined ? undefined : JSON.stringify(body),
        });
    } catch {
        throw new ApiError("Unable to reach the KYVON server.", 0, "network");
    }

    let data = null;
    try {
        data = await response.json();
    } catch {
        // Non-JSON response; handled below.
    }

    if (!response.ok) {
        const error = data && data.error ? data.error : {};
        if (response.status === 401 && notifyUnauthorized) {
            onUnauthorized();
        }
        throw new ApiError(
            error.message || `Request failed (${response.status}).`,
            response.status,
            error.code
        );
    }

    return data;
}
