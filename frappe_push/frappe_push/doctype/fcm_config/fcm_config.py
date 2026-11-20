import json

import frappe
from frappe import _
from frappe.model.document import Document

from frappe_push.frappe_push.api import require_system_manager
from frappe_push.frappe_push.sending import TOKEN_FIELDS, send_to_tokens
from frappe_push.frappe_push.subscriptions import digest


class FCMConfig(Document):
	def validate(self):
		if self.prompt_delay is not None and not 0 <= frappe.utils.cint(self.prompt_delay) <= 300:
			frappe.throw(_("Prompt Delay must be between 0 and 300 seconds."))
		if self.enable:
			if not self.vapid_key:
				frappe.throw(_("A Web Push VAPID key is required."))
			account = self.fcm_service_account_json
			if account and set(account) == {"*"}:
				account = self.get_password("fcm_service_account_json")
			try:
				info = json.loads(account or "")
			except (TypeError, ValueError):
				frappe.throw(_("Invalid FCM Service Account JSON."))
			if not isinstance(info, dict) or info.get("type") != "service_account" or not info.get("private_key"):
				frappe.throw(_("Invalid FCM service account."))
			if info.get("project_id") != self.project_id:
				frappe.throw(_("The service account must belong to the configured Firebase project."))


@frappe.whitelist(methods=["POST"])
def send_test_notification():
	require_system_manager()
	config = frappe.get_single("FCM Config")
	if not config.enable:
		frappe.throw(_("Push notifications are disabled."))

	filters = {"token_hash": digest(config.test_token)} if config.test_token else {
		"user": frappe.session.user, "token_hash": ["is", "set"],
	}
	tokens = frappe.get_all("FCM Token", filters=filters, fields=TOKEN_FIELDS,
		order_by="last_used desc", limit=1)
	if not tokens:
		frappe.throw(_("Connect this device or enter an active registration token."))

	result = send_to_tokens(tokens, _("Test Notification"), _("If you can see this, FCM is working!"))
	success = bool(result["accepted"])
	return {
		"success": success,
		"message": _("Firebase accepted the test notification.") if success else _("Failed to send test notification."),
	}


@frappe.whitelist(methods=["POST"])
def get_delivery_health():
	from datetime import timedelta
	from frappe.utils import now_datetime

	require_system_manager()
	now = now_datetime()
	count = lambda **filters: frappe.db.count("FCM Delivery", filters=filters)
	return {
		"queued": count(status="Queued"),
		"retrying": count(status="Retry Scheduled"),
		"stalled": count(status="Queued", creation=["<", now - timedelta(minutes=5)])
			+ count(status="Retry Scheduled", retry_at=["<", now - timedelta(minutes=5)])
			+ count(status="Sending", modified=["<", now - timedelta(minutes=30)]),
		"unknown_today": count(status="Unknown", modified=[">=", now - timedelta(days=1)]),
		"credential_errors_today": count(modified=[">=", now - timedelta(days=1)],
			last_error=["like", "%Firebase credentials rejected%"])
			+ count(modified=[">=", now - timedelta(days=1)], last_error=["like", "%Firebase configuration unavailable%"]),
	}
