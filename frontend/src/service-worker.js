const CACHE = 'iris-shell-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/iris-icon.svg'];
self.addEventListener('install', (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', (event) => event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim())));
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/')) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then((response) => { const copy = response.clone(); caches.open(CACHE).then((cache) => cache.put('/index.html', copy)); return response; }).catch(() => caches.match('/index.html')));
    return;
  }
  event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then((response) => { if (response.ok) caches.open(CACHE).then((cache) => cache.put(request, response.clone())); return response; })));
});
self.addEventListener('push', (event) => {
  let data = { title: 'IRIS', body: 'Tienes una nueva notificación', url: '/residente/servicios' };
  try { if (event.data) data = { ...data, ...event.data.json() }; } catch (_) { if (event.data) data.body = event.data.text(); }
  event.waitUntil(self.registration.showNotification(data.title || 'IRIS', { body: data.body, icon: '/iris-icon.svg', badge: '/iris-icon.svg', data: { url: data.url || '/residente/servicios' } }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/residente/servicios', self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
    const found = clients.find((client) => client.url.startsWith(self.location.origin));
    return found ? found.navigate(target).then(() => found.focus()) : self.clients.openWindow(target);
  }));
});
