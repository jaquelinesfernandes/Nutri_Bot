/**
 * NutriBot Service Worker
 * Estratégia: Cache-first para assets estáticos, Network-first para páginas.
 */
const CACHE_NAME = 'nutribot-v1';

// Assets que vão para cache no install
const PRECACHE = [
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

// ── Install: pré-carrega assets críticos ────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

// ── Activate: limpa caches antigas ──────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: Network-first para HTML/API, Cache-first para static ─────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Ignora requests não-GET e cross-origin
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Static assets (ícones, manifest) → cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => cached || fetch(request))
    );
    return;
  }

  // Páginas HTML → network-first, fallback para cache
  event.respondWith(
    fetch(request)
      .then(response => {
        // Cacheia respostas bem-sucedidas de páginas do dashboard
        if (
          response.ok &&
          ['/dashboard', '/historico', '/relatorios'].some(p =>
            url.pathname.startsWith(p)
          )
        ) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
