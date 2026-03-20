importScripts("https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js");

// This placeholder will be replaced by the backend with actual config
const firebaseConfig = {};

self.addEventListener('install', (event) => {
    console.log('[firebase-messaging-sw.js] Service Worker installing.');
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    console.log('[firebase-messaging-sw.js] Service Worker activating.');
    event.waitUntil(clients.claim());
});

try {
	if (firebaseConfig.apiKey) {
		firebase.initializeApp(firebaseConfig);
		const messaging = firebase.messaging();

		messaging.onBackgroundMessage((payload) => {
		  console.log('[firebase-messaging-sw.js] Received background message ', payload);
		  
		  // Data-only payload support
		  const data = payload.data || {};
		  const notificationTitle = data.title || (payload.notification ? payload.notification.title : "New Notification");
		  const notificationBody = data.body || (payload.notification ? payload.notification.body : "");
		  
		  const notificationOptions = {
		    body: notificationBody,
		    icon: data.notification_icon || '/assets/frappe/images/frappe-favicon.png',
		    data: {
		        click_action: data.click_action || '/app'
		    },
		    tag: data.document_name || data.document_type || 'frappe-push-notification',
		    renotify: true
		  };

		  return self.registration.showNotification(notificationTitle, notificationOptions);
		});
	}
} catch (e) {
	console.error("SW Init Error", e);
}

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const urlToOpen = (event.notification.data && event.notification.data.click_action) ? event.notification.data.click_action : '/app';
    
    event.waitUntil(
        clients.matchAll({
            type: 'window',
            includeUncontrolled: true
        }).then(function(windowClients) {
            for (var i = 0; i < windowClients.length; i++) {
                var client = windowClients[i];
                if (client.url.indexOf(urlToOpen) !== -1 && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(urlToOpen);
            }
        })
    );
});
