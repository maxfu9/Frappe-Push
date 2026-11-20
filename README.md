# Frappe Push Notifications 🚀

A robust, self-hosted Firebase Cloud Messaging (FCM) integration for Frappe and ERPNext. This app allows you to send real-time push notifications to Chrome, Safari, and other modern browsers without relying on external relay services.

## ✨ Features

- **Cross-Browser Support**: Fully compatible with Chrome, Firefox, and Safari (including the user-gesture requirements for Safari 16.4+).
- **Intelligent Triggers**:
  - **Document Assignments**: Notifies users immediately when a task or document is assigned to them (including self-assignments).
  - **Mentions**: Captures `@mentions` from the Notification Log.
  - **System Notifications**: (e.g., Sales Order Submission).
- **Delivery and Configuration**:
  - **Dynamic Configuration**: Manage Firebase and prompt settings in the `FCM Config` DocType.
  - **On-the-Fly Service Worker**: The Service Worker is dynamically templated, ensuring site-specific IDs are always correct.
  - **Token De-duplication**: Keeps one active registration per browser and revokes it on logout or disconnect.
  - **Silent Refresh**: Keeps connection alive in the background without intrusive progress messages.
- **Privacy & Control**: You own your data. Messages are sent directly from your server to Firebase.

## 🚀 Installation

Install the app using the Frappe Bench CLI:

```bash
cd /your-bench-path
bench get-app https://github.com/maxfu9/Frappe-Push.git
bench --site yoursite.local install-app frappe_push
bench --site yoursite.local migrate
bench build --app frappe_push
```

## ⚙️ Configuration

1. **Firebase Console Setup**:
   - Create a project on [Firebase Console](https://console.firebase.google.com/).
   - Add a "Web App" to your project.
   - Go to **Project Settings > Cloud Messaging**:
     - Generate a **VAPID Key** (Web Push certificate).
     - Note down the **Messaging Sender ID**.
   - Go to **Project Settings > Service accounts**:
     - Click **Generate new private key** to download the JSON service account file.

2. **Frappe Setup**:
   - Search for **FCM Config** in the Frappe Desk.
   - Fill in the following fields:
     - **Enable**: Check to activate.
     - **API Key**: From Firebase Web App config.
     - **Project ID**: Your Firebase project ID.
     - **Messaging Sender ID**: From Firebase Cloud Messaging settings.
     - **App ID**: From Firebase Web App config.
     - **VAPID Key**: Your generated Web Push certificate key.
     - **Service Account JSON**: Paste the ENTIRE content of the downloaded private key JSON file here.

3. **User Action**:
   - Once configured, users will see a dialog asking to "Enable Push Notifications" on their next refresh.
   - In Safari, this must be triggered by the user clicking "Enable Now" in the dialog.

## 🛡️ Self-Cleanup & Maintenance

The app automatically manages tokens. A registered browser refreshes its subscription when it returns. After upgrading from an older release, existing devices must revisit the site to register with the new browser credential. The previous registrations are no longer used. A user who signs out or disconnects can reconnect from Push notifications in the Desk user menu or website footer.

Broadcasts and document notifications are queued after the originating transaction commits. The **FCM Delivery** list records Firebase acceptance and failures. An accepted message may still be blocked by the device. Keep the Bench scheduler and long worker active. Broadcast links must stay on the site's origin. **Staff** targets enabled System Users.

On Europlast Webshop, a guest who enabled push before checkout can receive updates on new orders placed from that browser. The link opens the website's order tracking form.

Frappe Push uses its own subscription endpoints. Native Frappe and HRMS mobile subscriptions use their existing relay configuration.

## 🤝 Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.

## 📄 License

MIT

## Device diagnostics and delivery health

Open **Push notifications** and choose **Send a test to this device**. Keep that tab visible until it reports browser confirmation. The test ID matches an **FCM Delivery** record. An accepted send without browser confirmation may still have been displayed in the background. **FCM Config** shows the queue, retry, stalled and credential-error counts for System Managers.

Staff alerts expire after five minutes and order updates expire after 30 minutes. Their previews omit document details and order status. New updates to the same order replace older notifications where the browser supports grouping. The web app retries eligible, explicitly rejected targets up to two times. Frappe Push records ambiguous outcomes as **Unknown** to avoid automatic duplicate sends.
