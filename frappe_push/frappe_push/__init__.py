import frappe

def patch_push_notifications():
	try:
		from frappe.push_notification import PushNotification
		from frappe_push.frappe_push.api import send_notification_to_user as custom_send_notification_to_user
		
		# Store the original method just in case
		if not hasattr(PushNotification, "_original_send_notification_to_user"):
			PushNotification._original_send_notification_to_user = PushNotification.send_notification_to_user
		
		# Define a wrapper to check if FCM is enabled
		def send_notification_wrapper(user, title, body, data=None):
			config = frappe.get_single("FCM Config")
			if config.enable:
				return custom_send_notification_to_user(user, title, body, data)
			else:
				# Fallback to original if FCM is disabled
				return PushNotification._original_send_notification_to_user(user, title, body, data)
		
		PushNotification.send_notification_to_user = send_notification_wrapper
		# print("Frappe Push: Core messaging patched successfully.")
	except Exception as e:
		# Don't fail the whole app if patch fails
		pass

# Apply the patch
patch_push_notifications()
