# Frappe Push Notifications 🚀

A robust, self-hosted Firebase Cloud Messaging (FCM) integration for Frappe and ERPNext. This app allows you to send real-time push notifications to Chrome, Safari, and other modern browsers without relying on external relay services.

## ✨ Features

- **Cross-Browser Support**: Fully compatible with Chrome, Firefox, and Safari (including the user-gesture requirements for Safari 16.4+).
- **Intelligent Triggers**:
  - **Document Assignments**: Notifies users immediately when a task or document is assigned to them (including self-assignments).
  - **Mentions**: Captures `@mentions` from the Notification Log.
  - **Custom Triggers**: Easily hook into any Frappe event (e.g., Sales Order Submission).
- **Production-Ready Architecture**:
  - **Dynamic Configuration**: No hardcoded keys. All settings are managed in the `FCM Config` DocType.
  - **On-the-Fly Service Worker**: The Service Worker is dynamically templated, ensuring site-specific IDs are always correct.
  - **Token De-duplication**: Automatically cleans up old tokens per browser/user to prevent duplicate alerts.
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

The app automatically manages tokens. When a user logs in from a new browser session, old tokens for that same browser are cleared to ensure exactly one notification is delivered per device.

## 🤝 Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.

## 📄 License

MIT
