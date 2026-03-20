import frappe
from frappe.model.document import Document
from frappe_push.frappe_push.api import send_promo_broadcast

class FCMBroadcast(Document):
	@frappe.whitelist()
	def send_broadcast(self):
		if self.status == "Sent":
			frappe.throw("This broadcast has already been sent.")
		
		# Call the central API
		result = send_promo_broadcast(
			title=self.title,
			message=self.message,
			click_action=self.click_action,
			target=self.target
		)
		
		if result.get("status") == "success":
			self.status = "Sent"
			self.sent_count = result.get("sent_count")
			self.save()
			frappe.msgprint(f"Broadcast sent successfully to {self.sent_count} devices!")
		else:
			frappe.msgprint(f"Failed to send broadcast: {result.get('message')}")
