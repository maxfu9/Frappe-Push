import "./push_prompt.js";

frappe.provide("frappe_push");
console.log("Frappe Push script loaded from /assets/frappe_push/js/frappe_push.js");

frappe_push.init = function() {
	if (window.frappe_push_initialized) return;
	window.frappe_push_initialized = true;

	console.log("Frappe Push initializing for user:", frappe.session.user);
	
	if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
		console.log("This browser does not support desktop notification");
		return;
	}

	// Always clear badge on init/refresh
	frappe_push.clear_badge();


	console.log("Frappe Push: Fetching config...");
	frappe.call({
		method: "frappe_push.frappe_push.api.get_public_config",
		callback: function(r) {
			console.log("Frappe Push: Config API response:", r.message);
			if (r.message) {
				let resolve_token, reject_token;
				const token_ready = new Promise((resolve, reject) => { resolve_token = resolve; reject_token = reject; });
				// Background setup failures must not create unhandled rejections or hide the settings control.
				token_ready.catch(() => {});
				frappe_push.prompt.setup(r.message, async () => {
					const permission = Notification.permission === "default"
						? await Notification.requestPermission() : Notification.permission;
					if (permission !== "granted") return permission;
					let timeout;
					try {
						const register = await Promise.race([token_ready, new Promise((_, reject) => {
							timeout = setTimeout(() => reject(new Error("Push setup timed out")), 15000);
						})]);
						return await register();
					} finally { clearTimeout(timeout); }
				});
				if (Notification.permission !== "denied") frappe_push.setup_firebase(r.message, resolve_token, reject_token);
			} else {
				console.log("Frappe Push: No config received or app disabled.");
			}
		},
		error: function(e) {
			console.error("Frappe Push: API Error:", e);
		}
	});
};

frappe_push.setup_firebase = function(config, resolve_token, reject_token) {
	frappe.require([
		"https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js",
		"https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js"
	], function() {
		try {
			if (!firebase.apps.length) {
				firebase.initializeApp(config);
			}
			const messaging = firebase.messaging();
			

			// Revert to proven API path for registration
			navigator.serviceWorker.register('/api/method/frappe_push.frappe_push.api.get_service_worker', { scope: '/' })
				.then((registration) => {
					console.log("Frappe Push: Service Worker registered with scope:", registration.scope);
					return navigator.serviceWorker.ready;
				})
				.then((registration) => {
					// Wait a moment for consistency
					return new Promise(resolve => setTimeout(() => resolve(registration), 1000));
				})
				.then((registration) => {
					async function request_and_get_token() {
						const permission = Notification.permission;
						if (permission !== "granted") return permission;
						const token = await messaging.getToken({vapidKey: config.vapidKey, serviceWorkerRegistration: registration});
						if (!token) throw new Error("No push token available");
						const response = await frappe_push.register_token(token);
						if (!response.message?.success) throw new Error("Push subscription was not saved");
						return permission;
					}

					// Handle foreground messages
					messaging.onMessage((payload) => {
						console.log("Frappe Push: Foreground message received:", payload);
						frappe_push.clear_badge();
						if (payload) {
							show_foreground_notification(payload);
						}
					});

					function show_foreground_notification(payload) {
						// Extract from notification object OR data object (for maximum compatibility)
						const data = payload.data || {};
						const notification = payload.notification || {};
						
						const notify_id = 'push-notify-' + Date.now();
						const icon = notification.icon || data.notification_icon || config.siteLogo;
						const title = notification.title || data.title || __('New Notification');
						const body = notification.body || data.body || '';
						const click_action = data.click_action || data.click_action_url || null;

						if (!title && !body) return; // Silent background data

						// Show a native desktop notification even in foreground
						if (Notification.permission === "granted") {
							const n = new Notification(title, {
								body: body,
								icon: icon,
								tag: data.document_name || 'frappe-push-' + Date.now()
							});
							n.onclick = (e) => {
								e.preventDefault();
								window.focus();
								if (click_action) {
									// Determine if it's an internal route that we should handle via frappe.set_route
									let route = click_action;
									if (click_action.startsWith(window.location.origin)) {
										route = click_action.replace(window.location.origin, '');
									}
									
									if (route.startsWith('/app') && window.frappe) {
										// Scrub leading /app/ and navigate
										const actual_route = route.replace(/^\/app\//, '');
										frappe.set_route(actual_route);
									} else {
										window.location.href = click_action;
									}
								}
								n.close();
							};
						}

						const existing_notifications = document.querySelectorAll('.frappe-push-notification');
						const offset = existing_notifications.length * 100; // 100px per notification

						const notify_html = `
							<div id="${notify_id}" class="frappe-push-notification" style="
								position: fixed;
								bottom: ${20 + offset}px;
								right: 20px;
								width: calc(100% - 40px);
								max-width: 380px;
								background: rgba(255, 255, 255, 0.98);
								backdrop-filter: blur(12px);
								-webkit-backdrop-filter: blur(12px);
								border-radius: 20px;
								padding: 24px;
								box-shadow: 0 15px 40px rgba(0,0,0,0.12);
								display: flex;
								flex-direction: column;
								gap: 16px;
								z-index: 1000000;
								font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
								cursor: pointer;
								transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease, bottom 0.3s ease;
								transform: translateX(400px);
								opacity: 0;
								border: 1px solid rgba(0,0,0,0.05);
							">
								<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;">
									<div style="font-weight: 700; font-size: 16px; color: #1a1a1a;">${title}</div>
									<button class="notify-close" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #bbb; line-height: 1; padding: 0;">&times;</button>
								</div>
								<div style="font-size: 14px; color: #444; line-height: 1.5;">${body}</div>
								${click_action ? `
									<button class="notify-action" style="
										background: #2563eb;
										color: white;
										border: none;
										border-radius: 12px;
										padding: 10px 16px;
										font-weight: 600;
										font-size: 14px;
										cursor: pointer;
										width: fit-content;
										transition: background 0.2s;
									">${__('Open Details')}</button>
								` : ''}
							</div>
						`;

						document.body.insertAdjacentHTML('beforeend', notify_html);
						const el = document.getElementById(notify_id);

						setTimeout(() => {
							el.style.transform = 'translateX(0)';
							el.style.opacity = '1';
						}, 100);

						const dismiss = () => {
							el.style.transform = 'translateX(400px)';
							el.style.opacity = '0';
							setTimeout(() => {
								el.remove();
								// Re-calculate positions for remaining notifications
								document.querySelectorAll('.frappe-push-notification').forEach((node, index) => {
									node.style.bottom = (20 + (index * 100)) + 'px';
								});
							}, 400);
						};

						el.onclick = (e) => {
							if (e.target.classList.contains('notify-close')) {
								dismiss();
							} else if (click_action) {
								// For broadcasts, always open in a new tab
								if (data.is_broadcast === "1") {
									window.open(click_action, '_blank');
									dismiss();
									return;
								}

								let route = click_action;
								if (click_action.startsWith(window.location.origin)) {
									route = click_action.replace(window.location.origin, '');
								}
								
								if (route.startsWith('/app') && window.frappe) {
									const actual_route = route.replace(/^\/app\//, '');
									frappe.set_route(actual_route);
									dismiss();
								} else {
									window.location.href = click_action;
								}
							} else {
								// For non-link notifications, click anywhere to dismiss
								dismiss();
							}
						};
					}

					resolve_token(request_and_get_token);
					if (Notification.permission === "granted") {
						request_and_get_token().catch((error) => console.warn("Frappe Push: Could not refresh subscription", error));
					}

				}).catch((err) => {
					console.error("Frappe Push: Service Worker registration failed:", err);
					reject_token(err);
				});
		} catch (e) {
			console.error("Firebase Setup Error:", e);
			reject_token(e);
		}
	});
};

frappe_push.register_token = function(token) {
	// Generate persistent Device ID for better de-duplication
	let device_id;
	try {
		device_id = localStorage.getItem("frappe_push_device_id");
		if (!device_id) {
			device_id = frappe.utils.get_random(16);
			localStorage.setItem("frappe_push_device_id", device_id);
		}
	} catch (_) { /* Permission can still be enabled when storage is restricted. */ }

	return frappe.call({
		method: "frappe_push.frappe_push.api.subscribe",
		args: {
			fcm_token: token,
			browser: navigator.userAgent,
			device_id: device_id
		}
	});
};

frappe_push.clear_badge = function() {
	if (navigator.clearAppBadge) {
		navigator.clearAppBadge();
	}
	// Also clear the persistent count in Cache (used by SW)
	if ('caches' in window) {
		caches.open('frappe-push-v1').then(cache => {
			cache.delete('/badge-count');
		});
	}
};

$(function() {
	// Trigger on user's FIRST click OR 3-second delay (for Desk/Guests who might not click immediately)
	let initialized = false;
	const run_init = () => {
		if (initialized) return;
		initialized = true;
		console.log("Frappe Push: Initializing via trigger...");
		frappe_push.init();
	};

	$(document).one('click', run_init);
	setTimeout(run_init, 3000); // Fallback for visibility
});
