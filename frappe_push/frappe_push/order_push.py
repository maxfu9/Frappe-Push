"""Associate a guest Webshop order only with the browser placing that order."""

import frappe

from frappe_push.frappe_push.api import safe_hook
from frappe_push.frappe_push.delivery import queue_event
from frappe_push.frappe_push.subscriptions import browser_subscription

DOCTYPE = "FCM Order Subscription"


@safe_hook
def link_guest_order(doc, method=None):
	if frappe.session.user != "Guest" or "webshop" not in frappe.get_installed_apps():
		return
	quotation = frappe.cache().get_value(f"checkout_quotation_{frappe.session.id}")
	if not quotation or not doc.items or any(item.prevdoc_docname != quotation for item in doc.items):
		return
	subscription = browser_subscription()
	if not subscription or subscription.user:
		return
	frappe.get_doc({
		"doctype": DOCTYPE,
		"sales_order": doc.name,
		"subscription": subscription.name,
	}).insert(ignore_permissions=True)
	track_order_status(doc)


@safe_hook
def track_order_status(doc, method=None):
	if not doc.name:
		return
	link = frappe.db.get_value(DOCTYPE, doc.name, ["name", "last_state"], as_dict=True, for_update=True)
	if not link:
		return
	# Use the persisted state, including changes from ERPNext's db_set flow.
	state = frappe.db.get_value("Sales Order", doc.name, ["docstatus", "status", "payment_review_status"],
		as_dict=True) if doc.meta.has_field("payment_review_status") else frappe.db.get_value(
		"Sales Order", doc.name, ["docstatus", "status"], as_dict=True)
	if not state:
		return
	value = f"{state.docstatus}|{state.status or ''}|{state.get('payment_review_status') or ''}"
	if value == link.last_state:
		return

	event_id = queue_event("Order", doc.name, value, frappe.generate_hash(length=16))
	frappe.db.set_value(DOCTYPE, link.name, {"last_state": value, "latest_event": event_id})
