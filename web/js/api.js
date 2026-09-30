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


// POST a request and read a Server-Sent Events response, calling ``onEvent(type, data)``.
// Resolves when the stream ends. ``signal`` (AbortController) cancels it.
export async function stream(path, body, onEvent, { signal } = {}) {
    let response;
    try {
        response = await fetch(BASE + path, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
            credentials: "same-origin",
            body: JSON.stringify(body),
            signal,
        });
    } catch (error) {
        if (error.name === "AbortError") throw error;
        throw new ApiError("Unable to reach the KYVON server.", 0, "network");
    }

    if (!response.ok) {
        let error = {};
        try {
            error = (await response.json()).error || {};
        } catch {
            // Non-JSON error body.
        }
        if (response.status === 401) onUnauthorized();
        throw new ApiError(
            error.message || `Request failed (${response.status}).`,
            response.status,
            error.code
        );
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
            const block = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            let type = "message";
            let data = "";
            for (const line of block.split("\n")) {
                if (line.startsWith("event: ")) type = line.slice(7);
                else if (line.startsWith("data: ")) data += line.slice(6);
            }
            if (data) onEvent(type, JSON.parse(data));
        }
    }
}
