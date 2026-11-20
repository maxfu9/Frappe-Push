import "./push_prompt.js";

frappe.provide("frappe_push");

const method = "frappe_push.frappe_push.api.";
const workerRoute = "/api/method/" + method + "get_service_worker";
const workerScope = "/frappe-push/";
const optOutKey = "frappe_push_disabled_v1";

function browserOptedOut() {
	try { return localStorage.getItem(optOutKey) === "1"; } catch (_) { return false; }
}

function rememberOptOut(disconnected) {
	try {
		if (disconnected) localStorage.setItem(optOutKey, "1");
		else localStorage.removeItem(optOutKey);
	} catch (_) {
		// The server opt-out cookie still applies when local storage is restricted.
	}
}
const firebaseScripts = [
	"https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js",
	"https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js",
];

frappe_push.init = function () {
	if (window.frappe_push_initialized || !("Notification" in window)
		|| !("serviceWorker" in navigator) || !("PushManager" in window)) return;
	window.frappe_push_initialized = true;
	clearBadge();

	frappe.call({
		method: method + "get_public_config",
		callback({ message: config }) {
			if (!config) return;
			if (config.disconnected) rememberOptOut(true);
			config.disconnected = config.disconnected || browserOptedOut();
			if (config.disconnected) config.connected = false;

			let setup;
			const connectFirebase = () => {
				if (!setup) {
					setup = withTimeout(frappe_push.setup_firebase(config), 15000).catch((error) => {
						setup = null;
						throw error;
					});
				}
				return setup;
			};
			const serialize = (fn) => navigator.locks?.request
				? navigator.locks.request("frappe-push-subscription", fn) : fn();
			const subscribe = (reconnect = false) => serialize(async () => {
				if (!reconnect && browserOptedOut()) return;
				const { messaging, registration } = await connectFirebase();
				const save = async () => {
					const token = await messaging.getToken({
						vapidKey: config.vapidKey, serviceWorkerRegistration: registration,
					});
					if (!token) throw new Error("No push registration available");
					const response = await frappe.call({
						method: method + "subscribe",
						args: { fcm_token: token, browser: navigator.userAgent, reconnect },
					});
					return response.message;
				};

				let result = await save();
				if (result?.reset_token) {
					await messaging.deleteToken();
					result = await save();
				}
				if (!result?.success) throw new Error("Push registration was not saved");
				if (reconnect) rememberOptOut(false);
				frappe_push.prompt.connected = true;
				return "granted";
			});
			const enable = async () => {
				const permission = Notification.permission === "default"
					? await Notification.requestPermission() : Notification.permission;
				return permission === "granted" ? subscribe(true) : permission;
			};
			const disconnect = () => serialize(async () => {
				const response = await frappe.call({ method: method + "unsubscribe" });
				if (!response.message?.success) throw new Error("Push registration was not disconnected");
				rememberOptOut(true);
				// The server-side subscription is authoritative. The browser may already
				// have revoked the Firebase token or lost access to the Firebase SDK.
				if (setup) await setup.then(({ messaging }) => messaging.deleteToken()).catch(() => {});
			});

			frappe_push.prompt.setup(config, enable, disconnect);
			if (Notification.permission === "granted" && !config.disconnected) {
				subscribe().catch(() => console.warn("Frappe Push could not refresh this subscription"));
			} else if (Notification.permission === "default" && !config.disconnected) {
				connectFirebase().catch(() => {});
			}
		},
		error() { window.frappe_push_initialized = false; },
	});
};

function withTimeout(promise, delay) {
	let timer;
	return Promise.race([promise, new Promise((_, reject) => {
		timer = setTimeout(() => reject(new Error("Push setup timed out")), delay);
	})]).finally(() => clearTimeout(timer));
}

async function activeRegistration(registration) {
	if (registration.active?.state === "activated") return registration;
	const worker = registration.installing || registration.waiting || registration.active;
	if (!worker) throw new Error("Push service worker is unavailable");
	return new Promise((resolve, reject) => {
		const check = () => {
			if (worker.state === "activated" || worker.state === "redundant") {
				worker.removeEventListener("statechange", check);
				if (worker.state === "activated") resolve(registration);
				else reject(new Error("Push service worker did not activate"));
			}
		};
		worker.addEventListener("statechange", check);
		check();
	});
}

frappe_push.setup_firebase = async function (config) {
	await new Promise((resolve, reject) => {
		const loaded = frappe.require(firebaseScripts, resolve);
		if (loaded?.catch) loaded.catch(reject);
	});
	if (!await firebase.messaging.isSupported()) throw new Error("Firebase Messaging is unavailable");

	const app = firebase.apps.find((item) => item.name === "frappe-push")
		|| firebase.initializeApp(config, "frappe-push");
	const messaging = app.messaging();
	const registration = await activeRegistration(await navigator.serviceWorker.register(workerRoute, {
		scope: workerScope,
	}));

	const legacy = await navigator.serviceWorker.getRegistration("/");
	const oldWorker = legacy?.active || legacy?.waiting || legacy?.installing;
	if (legacy?.scope === new URL("/", location.origin).href
		&& oldWorker?.scriptURL === new URL(workerRoute, location.origin).href) {
		await legacy.unregister();
	}

	if (!frappe_push.foreground_listener) {
		frappe_push.foreground_listener = messaging.onMessage((payload) => showForeground(payload, registration));
	}
	return { messaging, registration };
};

function siteUrl(value, fallback = "") {
	try {
		const url = new URL(value || fallback, location.origin);
		return url.origin === location.origin && /^https?:$/.test(url.protocol) ? url.href : fallback;
	} catch (_) {
		return fallback;
	}
}

function clearBadge() {
	if (navigator.clearAppBadge) navigator.clearAppBadge().catch(() => {});
	if ("caches" in window) caches.open("frappe-push-v1").then(cache => cache.delete("/badge-count")).catch(() => {});
}

function showForeground(payload, registration) {
	if (document.hidden) return;

	const data = payload.data || {};
	const title = data.title || payload.notification?.title || __("New Notification");
	const body = data.body || payload.notification?.body || "";
	const url = siteUrl(data.url || data.click_action_url || data.click_action, "/app");
	const icon = siteUrl(data.icon, "/assets/frappe/images/frappe-favicon.png");
	const tag = data.tag || data.event_id || "frappe-push-" + Date.now();

	const toast = document.createElement("aside");
	toast.className = "frappe-push-notification";
	toast.dataset.pushTag = tag;
	toast.setAttribute("aria-label", __("Push notification"));
	toast.setAttribute("role", "status");

	const heading = document.createElement("strong");
	heading.textContent = title;
	const message = document.createElement("p");
	message.textContent = body;
	const link = document.createElement("a");
	link.href = url;
	link.textContent = __("Open Details");
	const close = document.createElement("button");
	close.type = "button";
	close.textContent = __("Dismiss");
	close.onclick = () => toast.remove();
	toast.append(heading, message, link, close);

	let host = document.getElementById("frappe-push-toasts");
	if (!host) {
		host = document.createElement("div");
		host.id = "frappe-push-toasts";
		document.body.append(host);
	}
	const previous = Array.from(host.children).find(item => item.dataset.pushTag === tag);
	if (previous) previous.remove();
	if (host.children.length >= 3) host.firstElementChild.remove();
	host.append(toast);
	if (data.device_test === "1" && data.event_id) {
		frappe.call({ method: method + "confirm_device_test", args: { delivery: data.event_id } }).catch(() => {});
	}

	if (Notification.permission === "granted") {
		registration.showNotification(title, {
			body, icon, tag, data: { frappePush: true, url },
		}).catch(() => {});
	}
}

$(function () {
	$(document).one("click", frappe_push.init);
	setTimeout(frappe_push.init, 3000);
});
