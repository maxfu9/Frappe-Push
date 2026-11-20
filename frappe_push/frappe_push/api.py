import json
from functools import wraps

import frappe
from frappe import _
from frappe.utils import cint

from frappe_push.frappe_push.subscriptions import (
	DISCONNECTED,
	browser_subscription,
	current_owner,
	get_browser_key,
	subscribe,
	unsubscribe,
)


def require_system_manager():
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Managers can send push notifications."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def send_promo_broadcast(title, message, click_action="/app", target="Both"):
	require_system_manager()
	broadcast = frappe.get_doc({
		"doctype": "FCM Broadcast",
		"title": title,
		"message": message,
		"click_action": click_action,
		"target": target,
	}).insert()
	return broadcast.send_broadcast()


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_public_config():
	config = frappe.get_single("FCM Config")
	if not cint(config.enable):
		return None

	subscription = browser_subscription()
	settings = config.get
	return {
		"apiKey": config.api_key,
		"projectId": config.project_id,
		"messagingSenderId": str(config.messaging_sender_id or ""),
		"appId": config.app_id,
		"vapidKey": config.vapid_key,
		"disconnected": get_browser_key() == DISCONNECTED,
		"connected": bool(subscription and (subscription.user or None) == current_owner()),
		"prompt": {
			"enabled": bool(cint(settings("prompt_enabled", default=1))),
			"website": bool(cint(settings("prompt_on_website", default=1))),
			"desk": bool(cint(settings("prompt_on_desk", default=1))),
			"position": settings("prompt_position") or "Bottom Left",
			"delay": max(0, min(300, cint(settings("prompt_delay", default=10)))),
		},
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_service_worker():
	from werkzeug.wrappers import Response

	config = frappe.get_single("FCM Config")
	public_config = {}
	if cint(config.enable):
		public_config = {
			"apiKey": config.api_key,
			"projectId": config.project_id,
			"messagingSenderId": str(config.messaging_sender_id or ""),
			"appId": config.app_id,
		}
	path = frappe.get_app_path("frappe_push", "public", "js", "firebase-messaging-sw.js")
	with open(path, encoding="utf-8") as script:
		content = script.read().replace("const firebaseConfig = {};", f"const firebaseConfig = {json.dumps(public_config)};")
	response = Response(content, mimetype="application/javascript")
	response.headers["Service-Worker-Allowed"] = "/frappe-push/"
	response.headers["Cache-Control"] = "no-cache"
	return response


def safe_hook(fn):
	"""Push failures must not block document operations such as placing an order."""
	@wraps(fn)
	def hook(*args, **kwargs):
		try:
			return fn(*args, **kwargs)
		except Exception:
			frappe.logger("frappe_push").exception("Push hook failed: %s", fn.__name__)
	return hook


@safe_hook
def trigger_notification_log_push(doc, method=None):
	if doc.for_user and doc.for_user != "Guest":
		from frappe_push.frappe_push.delivery import queue_event

		queue_event("Notification", doc.name)


@safe_hook
def trigger_blog_post_push(doc, method=None):
	if doc.published and not doc.get_value_before_save("published"):
		from frappe_push.frappe_push.delivery import queue_event

		queue_event("Blog", doc.name, doc.modified)


def trigger_guest_order_push(doc, method=None):
	"""Compatibility for workers with cached hooks during an upgrade."""
	from frappe_push.frappe_push.order_push import track_order_status

	return track_order_status(doc, method)


def trigger_todo_notification_push(doc, method=None):
	"""Compatibility for workers with cached hooks during an upgrade."""
