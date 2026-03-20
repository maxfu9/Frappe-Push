import frappe

def monkey_patch_push_notification():
    from frappe.push_notification import PushNotification
    
    # Original method reference
    original_send = PushNotification.send_notification_to_user
    
    def custom_send(self, user_id, title, body, link=None, icon=None, data=None, truncate_body=True, strip_html=True):
        config = frappe.get_single("FCM Config")
        if config.enable:
            # Try sending via our custom FCM logic
            from frappe_push.frappe_push.api import send_notification_to_user
            try:
                # Merge link and icon into data if provided
                if data is None: data = {}
                if link: data["click_action"] = link
                if icon: data["notification_icon"] = icon
                
                success = send_notification_to_user(user_id, title, body, data)
                if success:
                    return True
            except Exception as e:
                frappe.log_error(f"Custom Push Notification Error: {str(e)}", "Frappe Push")
        
        # Fallback to original (relay) if disabled or failed
        return original_send(self, user_id, title, body, link, icon, data, truncate_body, strip_html)

    # Apply the patch
    PushNotification.send_notification_to_user = custom_send

# We can call this during app initialization
# But in Frappe, we can also use hooks to trigger this on every request or just once
monkey_patch_push_notification()
