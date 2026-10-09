// KYVON service worker.
//
// * The app shell (page, styles, scripts, icons) is cached so KYVON opens instantly and shows
//   an offline state instead of a browser error page.
// * The API is NEVER cached: replies, memories, tasks and calendar data always come from the
//   server (and private data never lands in a cache).
// * "__VERSION__" is replaced by the server with a hash of the shipped files, so a new
//   release installs a fresh cache and removes the old one.

const VERSION = "__VERSION__";
const CACHE = `kyvon-shell-${VERSION}`;
const SHELL = __SHELL__;

self.addEventListener("install", event => {
    event.waitUntil(
        caches
            .open(CACHE)
            .then(cache => cache.addAll(SHELL))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches
            .keys()
            .then(keys => Promise.all(keys.filter(k => k.startsWith("kyvon-shell-") && k !== CACHE).map(k => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", event => {
    const request = event.request;
    const url = new URL(request.url);

    if (request.method !== "GET" || url.origin !== self.location.origin) return;
    if (url.pathname.startsWith("/api/")) return; // network only, never cached

    if (request.mode === "navigate") {
        // Network first; fall back to the cached shell when offline.
        event.respondWith(
            fetch(request).catch(() => caches.match("/").then(hit => hit || Response.error()))
        );
        return;
    }

    if (url.pathname.startsWith("/static/")) {
        // Stale-while-revalidate for the app's own files.
        event.respondWith(
            caches.open(CACHE).then(cache =>
                cache.match(request).then(hit => {
                    const refresh = fetch(request)
                        .then(response => {
                            if (response.ok) cache.put(request, response.clone());
                            return response;
                        })
                        .catch(() => hit);
                    return hit || refresh;
                })
            )
        );
    }
});

// ---- push notifications -------------------------------------------------------------

self.addEventListener("push", event => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch {
        data = { title: "KYVON", body: event.data ? event.data.text() : "" };
    }
    event.waitUntil(
        self.registration.showNotification(data.title || "KYVON", {
            body: data.body || "",
            icon: "/static/icons/icon-192.png",
            badge: "/static/icons/favicon-32.png",
            tag: data.tag || "kyvon",
            data: { url: data.url || "/" },
        })
    );
});

self.addEventListener("notificationclick", event => {
    event.notification.close();
    const target = (event.notification.data && event.notification.data.url) || "/";
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(windows => {
            for (const client of windows) {
                if ("focus" in client) return client.focus();
            }
            return self.clients.openWindow(target);
        })
    );
});
