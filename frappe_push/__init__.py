__version__ = "0.0.1"

def monkey_patch_push_notification():
    try:
        import frappe
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
        
    except (ImportError, ModuleNotFoundError):
        # This happens during app installation/build when frappe is not in the environment
        pass

# Execute patch
monkey_patch_push_notification()
