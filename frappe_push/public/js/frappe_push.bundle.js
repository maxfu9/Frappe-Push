frappe.provide("frappe_push");
console.log("Frappe Push script loaded from /assets/frappe_push/js/frappe_push.js");

frappe_push.init = function() {
	if (window.frappe_push_initialized) return;
	window.frappe_push_initialized = true;

	console.log("Frappe Push initializing for user:", frappe.session.user);
	console.log("Current Notification Permission:", Notification.permission);
	
	if (!("Notification" in window)) {
		console.log("This browser does not support desktop notification");
		return;
	}

	if (Notification.permission === "denied") {
		console.warn("Frappe Push: Notifications are BLOCKED by the browser. Please reset permissions in the address bar (lock icon).");
		return;
	}

	console.log("Frappe Push: Fetching config...");
	frappe.call({
		method: "frappe_push.frappe_push.api.get_public_config",
		callback: function(r) {
			console.log("Frappe Push: Config API response:", r.message);
			if (r.message) {
				frappe_push.setup_firebase(r.message);
			} else {
				console.log("Frappe Push: No config received or app disabled.");
			}
		},
		error: function(e) {
			console.error("Frappe Push: API Error:", e);
		}
	});
};

frappe_push.setup_firebase = function(config) {
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
					function request_and_get_token(silent = false) {
						if (!silent) {
							frappe.show_alert({message: __('Requesting permission...'), indicator: 'blue'});
						}
						
						const handlePermission = (permission) => {
							if (permission === 'granted') {
								if (!silent) {
									frappe.show_alert({message: __('Permission granted! Finalizing...'), indicator: 'green'});
								}
								
								messaging.getToken({ 
									vapidKey: config.vapidKey,
									serviceWorkerRegistration: registration 
								}).then((currentToken) => {
									if (currentToken) {
										console.log("Frappe Push: Token retrieved successfully!");
										frappe_push.register_token(currentToken);
										localStorage.setItem("frappe_push_subscribed", "true");
										if (!silent) {
											frappe.show_alert({message: __('Successfully subscribed!'), indicator: 'green'});
										}
									} else {
										if (!silent) {
											frappe.show_alert({message: __('No token available.'), indicator: 'orange'});
										}
									}
								}).catch((err) => {
									console.error('An error occurred while retrieving token. ', err);
									if (!silent) {
										frappe.msgprint(__('Failed to get Push Token: ') + err.message);
									}
								});
							} else {
								console.log('Unable to get permission:', permission);
								if (!silent) {
									frappe.show_alert({message: __('Notification permission denied.'), indicator: 'red'});
								}
							}
						};

						const promise = Notification.requestPermission();
						if (promise) {
							promise.then(handlePermission);
						} else {
							Notification.requestPermission(handlePermission);
						}
					}

					// Handle foreground messages
					messaging.onMessage((payload) => {
						console.log("Frappe Push: Foreground message received:", payload);
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
									window.location.href = click_action;
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
								window.location.href = click_action;
							} else {
								// For non-link notifications, click anywhere to dismiss
								dismiss();
							}
						};
					}

					// Premium Persistent Banner: Stays visible until interacted with
					if (Notification.permission === 'default') {
						show_subscription_banner();
					} else if (Notification.permission === 'granted') {
						request_and_get_token(true);
					}

					function show_subscription_banner() {
						if (document.getElementById('frappe-push-banner')) return;

						const is_guest = frappe.session.user === 'Guest';
						const title = is_guest ? __('Stay Updated') : __('Direct Alerts');
						const message = is_guest 
							? __('Get real-time updates on your orders and exclusive offers from Europlast.')
							: __('Receive instant alerts for assignments, mentions, and system notifications.');

						const banner_html = `
							<div id="frappe-push-overlay" style="
								position: fixed;
								top: 0;
								left: 0;
								width: 100%;
								height: 100%;
								background: rgba(0, 0, 0, 0.4);
								backdrop-filter: blur(4px);
								-webkit-backdrop-filter: blur(4px);
								z-index: 999998;
								opacity: 0;
								transition: opacity 0.3s ease;
							"></div>
							<div id="frappe-push-banner" style="
								position: fixed;
								top: 50%;
								left: 50%;
								transform: translate(-50%, -40%);
								width: calc(100% - 40px);
								max-width: 400px;
								background: rgba(255, 255, 255, 0.98);
								border-radius: 20px;
								padding: 24px;
								box-shadow: 0 20px 50px rgba(0,0,0,0.15);
								display: flex;
								flex-direction: column;
								gap: 16px;
								z-index: 999999;
								font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
								opacity: 0;
								transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
							">
								<div style="display: flex; justify-content: space-between; align-items: flex-start;">
									<div style="font-weight: 700; font-size: 18px; color: #1a1a1a;">${title} 🔔</div>
									<button id="push-close" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #bbb; line-height: 1;">&times;</button>
								</div>
								<div style="font-size: 15px; color: #444; line-height: 1.5;">
									${message}
								</div>
								<button id="push-enable" style="
									background: #2563eb;
									color: white;
									border: none;
									border-radius: 12px;
									padding: 12px 20px;
									font-weight: 600;
									font-size: 16px;
									cursor: pointer;
									transition: transform 0.1s, background 0.2s;
								">${__('Enable Notifications')}</button>
							</div>
						`;

						document.body.insertAdjacentHTML('beforeend', banner_html);
						const banner = document.getElementById('frappe-push-banner');
						const overlay = document.getElementById('frappe-push-overlay');
						
						// Animate in
						setTimeout(() => {
							overlay.style.opacity = '1';
							banner.style.transform = 'translate(-50%, -50%)';
							banner.style.opacity = '1';
						}, 50);

						document.getElementById('push-enable').onclick = () => {
							request_and_get_token(false);
							dismiss_banner();
						};

						document.getElementById('push-close').onclick = dismiss_banner;
						overlay.onclick = dismiss_banner;

						function dismiss_banner() {
							overlay.style.opacity = '0';
							banner.style.transform = 'translate(-50%, -40%)';
							banner.style.opacity = '0';
							setTimeout(() => {
								banner.remove();
								overlay.remove();
							}, 400);
						}
					}
				}).catch((err) => {
					console.error("Frappe Push: Service Worker registration failed:", err);
				});
		} catch (e) {
			console.error("Firebase Setup Error:", e);
		}
	});
};

frappe_push.register_token = function(token) {
	// Generate persistent Device ID for better de-duplication
	let device_id = localStorage.getItem("frappe_push_device_id");
	if (!device_id) {
		device_id = frappe.utils.get_random(16);
		localStorage.setItem("frappe_push_device_id", device_id);
	}

	frappe.call({
		method: "frappe_push.frappe_push.api.subscribe",
		args: {
			fcm_token: token,
			browser: navigator.userAgent,
			device_id: device_id
		}
	});
};

console.log("Frappe Push Script Execution Started");

$(function() {
	// Trigger only after user's FIRST click on the page
	$(document).one('click', function() {
		frappe_push.init();
	});
});
