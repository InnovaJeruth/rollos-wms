const CACHE_VERSION = 'wms-rollos-v2.4.7';
const CORE_ASSETS = [
  './',
  './index.html',
  './admin.html',
  './config.js',
  './common.js',
  './manifest.json',
  'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js',
  'https://cdn.jsdelivr.net/npm/@undecaf/zbar-wasm@0.9.15/dist/index.js',
  'https://cdn.jsdelivr.net/npm/@undecaf/barcode-detector-polyfill@0.9.23/dist/index.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => {
      return cache.addAll(CORE_ASSETS).catch((err) => {
        console.warn('[SW] Algunos recursos no pudieron cachearse en install:', err);
        return Promise.all(
          CORE_ASSETS.map((url) =>
            cache.add(url).catch((e) => console.warn('[SW] No cacheado:', url, e))
          )
        );
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== 'GET') return;

  // Dejar pasar las llamadas a la API de GitHub sin interceptar — que el
  // browser maneje CORS, errores y autenticacion directamente, asi los
  // errores reales se ven en la consola en vez de un 503 generico.
  if (url.hostname === 'api.github.com') return;

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => {
        // Intenta servir la pagina solicitada desde cache (admin.html o index.html)
        return caches.match(req).then((c) => c || caches.match('./index.html'));
      })
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) {
        fetch(req).then((fresh) => {
          if (fresh && fresh.status === 200) {
            caches.open(CACHE_VERSION).then((c) => c.put(req, fresh.clone()));
          }
        }).catch(() => {});
        return cached;
      }
      return fetch(req).then((resp) => {
        if (resp && resp.status === 200 && (url.origin === location.origin || url.hostname === 'cdnjs.cloudflare.com' || url.hostname === 'cdn.jsdelivr.net')) {
          const clone = resp.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(req, clone));
        }
        return resp;
      }).catch(() => caches.match('./index.html'));
    })
  );
});
