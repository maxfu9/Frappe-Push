import frappe
from frappe.model.document import Document
import firebase_admin
from firebase_admin import credentials, messaging
import json
import base64

class FCMConfig(Document):
	def validate(self):
		if self.enable and self.fcm_service_account_json:
			try:
				json.loads(self.get_password("fcm_service_account_json"))
			except Exception:
				frappe.throw("Invalid FCM Service Account JSON")

@frappe.whitelist()
def send_test_notification():
	config = frappe.get_single("FCM Config")
	if not config.enable:
		frappe.throw("FCM is not enabled")
	
	token = config.test_token
	if not token:
		# Try to find the latest token for the current user
		last_token = frappe.get_all("FCM Token", 
			filters={"user": frappe.session.user}, 
			order_by="last_used desc", 
			limit=1, 
			fields=["fcm_token"]
		)
		if last_token:
			token = last_token[0].fcm_token
		else:
			frappe.throw("No registered token found for your user. Please refresh the page to register your device.")
	
	from frappe_push.frappe_push.api import send_push_notification
	
	try:
		success = send_push_notification(
			token=token,
			title="Test Notification",
			body="If you can see this, FCM is working!",
			data={"test": "true"}
		)
		if success:
			return {"success": True, "message": "Test notification sent successfully!"}
		else:
			return {"success": False, "message": "Failed to send test notification"}
	except Exception as e:
		frappe.throw(str(e))
