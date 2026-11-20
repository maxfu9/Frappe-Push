const firebaseConfig = {};
const CACHE_NAME = "frappe-push-v1";
const BADGE_KEY = "/badge-count";

self.addEventListener("install", (event) => event.waitUntil(self.skipWaiting()));

function safeURL(value, fallback) {
	try {
		const url = new URL(value || fallback, self.location.origin);
		if (url.origin === self.location.origin && /^https?:$/.test(url.protocol)) return url.href;
	} catch (_) {
		// Fall back to a safe site route.
	}
	return new URL(fallback, self.location.origin).href;
}

self.addEventListener("notificationclick", (event) => {
	const data = event.notification.data || {};
	if (!data.frappePush) return;
	event.stopImmediatePropagation();
	event.notification.close();
	event.waitUntil(Promise.all([
		openSitePage(safeURL(data.url, "/app")),
		clearBadge(),
	]));
});

async function openSitePage(url) {
	const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
	const target = windows.find((client) => client.url === url);
	if (target) return target.focus();
	return self.clients.openWindow(url);
}

async function clearBadge() {
	try {
		if (self.navigator.clearAppBadge) await self.navigator.clearAppBadge();
		const cache = await caches.open(CACHE_NAME);
		await cache.delete(BADGE_KEY);
	} catch (_) {
		// Badge support varies by browser and should not affect the notification.
	}
}

let badgeUpdate = Promise.resolve();
function incrementBadge() {
	badgeUpdate = badgeUpdate.then(async () => {
		if (!self.navigator.setAppBadge) return;
		const cache = await caches.open(CACHE_NAME);
		const previous = await cache.match(BADGE_KEY);
		const count = (previous ? parseInt(await previous.text(), 10) || 0 : 0) + 1;
		await cache.put(BADGE_KEY, new Response(String(count)));
		await self.navigator.setAppBadge(count);
	}).catch(() => {});
	return badgeUpdate;
}

if (firebaseConfig.apiKey) {
	importScripts("https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js");
	importScripts("https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js");
	firebase.initializeApp(firebaseConfig);
	firebase.messaging().onBackgroundMessage(async ({ data = {} }) => {
		await Promise.all([
			self.registration.showNotification(data.title || "New Notification", {
				body: data.body || "",
				icon: safeURL(data.icon, "/assets/frappe/images/frappe-favicon.png"),
				tag: data.event_id || undefined,
				data: { frappePush: true, url: safeURL(data.url, "/app") },
			}),
			incrementBadge(),
		]);
	});
}
