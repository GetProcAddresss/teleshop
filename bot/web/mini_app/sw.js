/* Evrest Market — Service Worker */
const VERSION = "evrest-v2.1.2";
const STATIC_CACHE = `${VERSION}-static`;
const RUNTIME_CACHE = `${VERSION}-runtime`;

const STATIC_ASSETS = [
  "/mini/",
  "/mini/index.html",
  "/mini/style.css",
  "/mini/logo.png",
  "/mini/manifest.webmanifest",
  "/mini/js/main.js",
  "/mini/js/state.js",
  "/mini/js/api.js",
  "/mini/js/theme.js",
  "/mini/js/tg.js",
  "/mini/js/ui.js",
  "/mini/js/views/shop.js",
  "/mini/js/views/cart.js",
  "/mini/js/views/orders.js",
  "/mini/js/views/profile.js",
  "/mini/js/views/detail.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(STATIC_CACHE).then((c) => c.addAll(STATIC_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/mini/")) return;
  if (url.pathname.startsWith("/mini/api/")) return; // never cache API

  // Static assets — cache first
  if (STATIC_ASSETS.includes(url.pathname) || /\.(css|js|png|svg|webmanifest)$/.test(url.pathname)) {
    e.respondWith(
      caches.match(req).then((hit) =>
        hit || fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(STATIC_CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
      )
    );
    return;
  }

  // HTML — network first, fall back to cache
  e.respondWith(
    fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(RUNTIME_CACHE).then((c) => c.put(req, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match(req).then((hit) => hit || caches.match("/mini/index.html")))
  );
});
