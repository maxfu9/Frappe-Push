importScripts('https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js');

// This placeholder will be replaced by the backend with actual config
const firebaseConfig = {};

if (firebaseConfig.apiKey) {
    firebase.initializeApp(firebaseConfig);
    const messaging = firebase.messaging();

    // Background message handler
    messaging.onBackgroundMessage((payload) => {
        console.log('[firebase-messaging-sw.js] Received background message ', payload);
        
        /* 
           IPHONE DUPLICATE FIX:
           When using a "Hybrid" payload (notification + data), the OS (especially iOS/Safari) 
           often displays the notification automatically. 
           If the Service Worker ALSO calls showNotification, the user gets two.
           
           We only show a manual notification if the 'notification' object is MISSING 
           (meaning it's a data-only payload).
        */
        
        if (!payload.notification && payload.data) {
            const data = payload.data;
            const notificationTitle = data.title || "New Notification";
            const notificationOptions = {
                body: data.body || "",
                icon: data.notification_icon || '/assets/frappe/images/frappe-favicon.png',
                data: data // Pass data for click handler
            };
            return self.registration.showNotification(notificationTitle, notificationOptions);
        }
    });

    // Handle notification click
    self.addEventListener('notificationclick', function(event) {
        console.log('[firebase-messaging-sw.js] Notification click Received.');
        event.notification.close();

        const data = event.notification.data || {};
        const urlToOpen = data.click_action || '/app';

        event.waitUntil(
            clients.matchAll({
                type: 'window',
                includeUncontrolled: true
            }).then(function(windowClients) {
                // If a window is already open, focus it and navigate
                for (var i = 0; i < windowClients.length; i++) {
                    var client = windowClients[i];
                    if (client.url.indexOf(urlToOpen) !== -1 && 'focus' in client) {
                        return client.focus();
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
