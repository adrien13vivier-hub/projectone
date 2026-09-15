/* ═══════════════════════════════════════════════════════════════════
   sw.js — travailleur de service de ProjectOne.

   Son seul role est de recevoir les notifications et de les afficher.
   Il ne met AUCUNE page en cache : un site financier qui servirait des
   chiffres d'hier serait pire qu'un site indisponible.

   REGLE IOS : toute notification recue doit etre affichee. Si on la
   laisse passer sans rien montrer, le systeme revoque l'abonnement et
   plus rien n'arrive ensuite, sans message d'erreur.
   ═══════════════════════════════════════════════════════════════════ */

self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('push', evenement => {
  let d = {};
  try { d = evenement.data ? evenement.data.json() : {}; }
  catch (e) { d = { titre: 'ProjectOne', corps: evenement.data ? evenement.data.text() : '' }; }

  const titre = d.titre || 'ProjectOne';
  const options = {
    body: d.corps || '',
    icon: '/icone-192.png',
    badge: '/icone-192.png',
    tag: d.tag || 'projectone',
    renotify: true,
    data: { url: d.url || '/' }
  };
  // waitUntil est obligatoire : sans lui le systeme peut arreter le
  // travailleur avant que la notification soit affichee.
  evenement.waitUntil(self.registration.showNotification(titre, options));
});

self.addEventListener('notificationclick', evenement => {
  evenement.notification.close();
  const cible = (evenement.notification.data && evenement.notification.data.url) || '/';
  evenement.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(fenetres => {
      for (const f of fenetres) {
        if ('focus' in f) { f.navigate && f.navigate(cible); return f.focus(); }
      }
      if (self.clients.openWindow) return self.clients.openWindow(cible);
    })
  );
});
