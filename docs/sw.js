// Permite instalar o painel como app. Sempre busca os dados novos na internet;
// sem internet, mostra a ultima versao da tela que ficou guardada.
const CACHE = "painel-v1";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request)
      .then(r => {
        if (r.ok && new URL(e.request.url).origin === location.origin) {
          const copia = r.clone();
          caches.open(CACHE).then(c => c.put(e.request, copia));
        }
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
