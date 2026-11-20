import frappe
from frappe import _
from frappe.model.document import Document

from frappe_push.frappe_push.api import require_system_manager
from frappe_push.frappe_push.delivery import queue_event
from frappe_push.frappe_push.sending import click_path


class FCMBroadcast(Document):
	def validate(self):
		previous = self.get_doc_before_save()
		if previous and previous.status != "Draft":
			frappe.throw(_("A queued broadcast cannot be edited."), frappe.PermissionError)

		self.status = "Draft"
		self.sent_count = 0
		self.failed_count = 0
		self.last_error = ""
		if self.target not in ("Both", "Guests", "Staff"):
			frappe.throw(_("Choose a valid broadcast audience."))
		if self.click_action and not click_path(self.click_action, default=""):
			frappe.throw(_("The notification link must point to this site."))

	@frappe.whitelist(methods=["POST"])
	def send_broadcast(self):
		require_system_manager()
		self.check_permission("write")
		if frappe.db.get_value(self.doctype, self.name, "status", for_update=True) != "Draft":
			frappe.throw(_("This broadcast has already been queued."))

		event = queue_event("Broadcast", self.name)
		if not event:
			frappe.throw(_("Push notifications are disabled."))
		frappe.db.set_value(self.doctype, self.name, "status", "Queued")
		self.status = "Queued"
		frappe.msgprint(_("Broadcast queued. Reload this form to see the delivery results."))
		return {"status": "queued", "delivery": event, "broadcast": self.name}
