// Service worker do painel Mobilli: recebe as notificações e abre a tela certa ao tocar
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {corpo: e.data && e.data.text()}; }
  e.waitUntil(self.registration.showNotification(d.titulo || 'Mobilli Digital', {
    body: d.corpo || '',
    icon: '/static/icone-192.png',
    badge: '/static/icone-192.png',
    data: {url: d.url || '/'}
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(abertas => {
    for (const c of abertas) {
      if ('focus' in c) { c.navigate(url); return c.focus(); }
    }
    return self.clients.openWindow(url);
  }));
});
