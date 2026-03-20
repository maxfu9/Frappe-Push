frappe.provide("frappe_push");
console.log("Frappe Push script loaded from /assets/frappe_push/js/frappe_push.js");

frappe_push.init = function() {
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
			
			// Handle foreground messages
			messaging.onMessage((payload) => {
				console.log('Frappe Push: Received foreground message ', payload);
				
				// De-duplicate: Only show notification in the active tab
				if (document.visibilityState !== 'visible') {
					console.log('Frappe Push: Tab is background, skipping foreground alert.');
					return;
				}

				// MERGE FIX: Data and Notification payloads
				const data = Object.assign({}, payload.data, payload.notification);
				const notificationTitle = data.title || "New Notification";
				const notificationBody = data.body || "";
				// Use absolute click_action_url if available
				const clickAction = data.click_action_url || data.click_action || '/app';
				
				const notificationOptions = {
					body: notificationBody,
					icon: config.siteLogo || data.notification_icon || '/assets/frappe/images/frappe-favicon.png'
				};
				
				// Show a desktop notification even in foreground
				if (Notification.permission === "granted") {
					const n = new Notification(notificationTitle, notificationOptions);
					n.onclick = (e) => {
						e.preventDefault();
						window.focus();
						if (clickAction) {
							window.location.href = clickAction;
						}
						n.close();
					};
				}
				
				// Also show a Frappe alert (clickable)
				frappe.show_alert({
					message: `<b>${notificationTitle}</b><br>${notificationBody}`,
					indicator: 'blue',
					onClick: () => {
						if (clickAction) {
							window.location.href = clickAction;
						}
					}
				});
			});

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

					// Proactive Dialog: Re-show whenever state is default (reset)
					if (Notification.permission === 'default') {
						const dialog = new frappe.ui.Dialog({
							title: __('Enable Push Notifications'),
							fields: [
								{
									fieldname: 'info',
									fieldtype: 'HTML',
									options: `<p>${__('Stay updated with real-time alerts for assignments, mentions, and more.')}</p>`
								}
							],
							primary_action_label: __('Enable Now'),
							primary_action(values) {
								request_and_get_token(false);
								dialog.hide();
							}
						});
						dialog.show();
					} else if (Notification.permission === 'granted') {
						request_and_get_token(true);
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
	if (frappe.session.user !== "Guest") {
		frappe_push.init();
	}
});
