/* TenderLens service worker: makes the app installable and opens it offline.
 *
 * It caches only the app shell (index.html, the manifest, icons) and Vite's content-hashed
 * bundles under /assets/. It never touches the API, the admin, sign-in, Django's static
 * files, the calendar feed or the Copilot's event stream: those requests go straight to the
 * network, exactly as without a service worker. Registered by main.tsx in production builds.
 */
const SHELL = "tl-shell-v1";
const ASSETS = "tl-assets-v1";
const MAX_ASSETS = 80;
const SHELL_FILES = ["/", "/manifest.webmanifest", "/favicon.svg", "/icons/icon-192.png", "/apple-touch-icon.png"];
const NEVER = /^\/(api|admin|accounts|static|media|health)(\/|$)/;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then((c) => c.addAll(SHELL_FILES))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== ASSETS).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

/** Old bundles pile up after each deploy; keep the newest MAX_ASSETS. */
async function trim(cache) {
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_ASSETS)).map((k) => cache.delete(k)));
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || NEVER.test(url.pathname)) return;
  if ((req.headers.get("accept") || "").includes("text/event-stream")) return;

  // Pages: always the network (a deploy shows at once); the cached shell only when offline.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok && (res.headers.get("content-type") || "").includes("text/html")) {
            const copy = res.clone();
            caches.open(SHELL).then((c) => c.put("/", copy));
          }
          return res;
        })
        .catch(() => caches.match("/").then((r) => r || Response.error())),
    );
    return;
  }

  // Hashed bundles never change under the same name: cache first.
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.open(ASSETS).then(async (cache) => {
        const hit = await cache.match(req);
        if (hit) return hit;
        const res = await fetch(req);
        if (res.ok) {
          await cache.put(req, res.clone());
          trim(cache);
        }
        return res;
      }),
    );
    return;
  }

  // Icons and the manifest: the cached copy, refreshed in the background.
  if (SHELL_FILES.includes(url.pathname) || url.pathname.startsWith("/icons/")) {
    event.respondWith(
      caches.open(SHELL).then(async (cache) => {
        const hit = await cache.match(req);
        const fresh = fetch(req)
          .then((res) => {
            if (res.ok) cache.put(req, res.clone());
            return res;
          })
          .catch(() => hit);
        return hit || fresh;
      }),
    );
  }
  // Anything else: not intercepted.
});
