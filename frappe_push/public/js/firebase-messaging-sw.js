importScripts('https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js');

// Force Service Worker to update and take control immediately
self.addEventListener('install', (event) => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

// This placeholder will be replaced by the backend with actual config
const firebaseConfig = {};

if (firebaseConfig.apiKey) {
    firebase.initializeApp(firebaseConfig);
    const messaging = firebase.messaging();

    // Background message handler
    messaging.onBackgroundMessage((payload) => {
        console.log('[firebase-messaging-sw.js] Received background message: ', JSON.stringify(payload, null, 2));
        
        // If FCM auto-displays, this might still be called for the data portion.
        // We log it to help debug "silent" deliveries.
        if (!payload.notification && payload.data) {
            const data = payload.data;
            const notificationTitle = data.title || "New Notification";
            const notificationOptions = {
                body: data.body || "",
                icon: data.notification_icon || '/assets/frappe/images/frappe-favicon.png',
                data: data,
                tag: data.document_name || 'frappe-push-' + Date.now(), // Unique tag allows stacking
                renotify: true,
                requireInteraction: true,
                vibrate: [200, 100, 200]
            };
            return self.registration.showNotification(notificationTitle, notificationOptions);
        }
    });

    // Handle notification click
    self.addEventListener('notificationclick', function(event) {
        console.log('[firebase-messaging-sw.js] Notification click Received.');
        event.notification.close();

        const data = event.notification.data || {};
        // Use click_action_url (absolute) or click_action (relative)
        const urlToOpen = data.click_action_url || data.click_action || '/app';

        event.waitUntil(
            clients.matchAll({
                type: 'window',
                includeUncontrolled: true
            }).then(function(windowClients) {
                // If a window is already open, focus it AND navigate to the specific doc
                for (var i = 0; i < windowClients.length; i++) {
                    var client = windowClients[i];
                    if ('focus' in client) {
                        client.focus();
                        
                        // Robust URL comparison: Compare path and search, ignore protocol/origin differences if site matches
                        try {
                            const clientUrl = new URL(client.url);
                            const targetUrl = new URL(urlToOpen, self.location.origin);
                            
                            // Normalize by removing trailing slashes
                            const normalize = (path) => path.replace(/\/+$/, '') || '/';
                            
                            console.log('[firebase-messaging-sw.js] Client URL:', client.url);
                            console.log('[firebase-messaging-sw.js] Target URL:', urlToOpen);

                            if (normalize(clientUrl.pathname) !== normalize(targetUrl.pathname) || 
                                clientUrl.search !== targetUrl.search || 
                                clientUrl.hash !== targetUrl.hash) {
                                console.log('[firebase-messaging-sw.js] URLs differ. Navigating client...');
                                return client.navigate(urlToOpen);
                            } else {
                                console.log('[firebase-messaging-sw.js] URLs match. Only focusing.');
                            }
                        } catch (e) {
                            console.error('[firebase-messaging-sw.js] URL Parse error, navigating just in case:', e);
                            return client.navigate(urlToOpen);
                        }
                        return;
                    }
                }
                // Otherwise, open a new window
                if (clients.openWindow) {
                    return clients.openWindow(urlToOpen);
                }
            })
        );
    });
}
