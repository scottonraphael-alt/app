/* Service worker d'Iris : notifications push uniquement, aucun cache hors ligne. */

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

function readPayload(event) {
  if (!event.data) return {};
  try {
    const data = event.data.json();
    return data && typeof data === "object" ? data : {};
  } catch (error) {
    try {
      return { body: event.data.text() };
    } catch (innerError) {
      return {};
    }
  }
}

function sameOriginUrl(value) {
  try {
    const target = new URL(typeof value === "string" ? value : "/", self.location.origin);
    return target.origin === self.location.origin ? target.href : self.location.origin + "/";
  } catch (error) {
    return self.location.origin + "/";
  }
}

self.addEventListener("push", (event) => {
  const payload = readPayload(event);
  const title = String(payload.title || "Iris").slice(0, 120);
  const options = {
    body: String(payload.body || "").slice(0, 300),
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: sameOriginUrl(payload.url) },
  };
  if (payload.tag) options.tag = String(payload.tag).slice(0, 80);
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = sameOriginUrl(event.notification.data && event.notification.data.url);

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (clients) => {
      for (const client of clients) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        try {
          await client.focus();
          if ("navigate" in client) await client.navigate(url);
          return;
        } catch (error) {
          /* on essaie d'ouvrir une nouvelle fenêtre */
        }
      }
      await self.clients.openWindow(url);
    }),
  );
});
