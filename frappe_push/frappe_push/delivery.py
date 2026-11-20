"""Durable event records and delivery after the originating transaction commits."""

from datetime import timedelta
from urllib.parse import quote

import frappe
from frappe.utils import cint, now_datetime, strip_html

from frappe_push.frappe_push.sending import TOKEN_FIELDS, audience_tokens, owned_tokens, send_to_tokens
from frappe_push.frappe_push.subscriptions import digest

DOCTYPE = "FCM Delivery"
WORKER = "frappe_push.frappe_push.delivery.dispatch"


def queue_event(kind, reference, *event_parts):
	if not cint(frappe.db.get_single_value("FCM Config", "enable")):
		return None

	name = digest("|".join(map(str, (kind, reference, *event_parts))))
	if frappe.db.exists(DOCTYPE, name):
		return name

	frappe.get_doc({
		"doctype": DOCTYPE,
		"event_key": name,
		"kind": kind,
		"reference_name": reference,
	}).insert(ignore_permissions=True, ignore_if_duplicate=True)
	frappe.db.after_commit.add(lambda: enqueue_delivery(name))
	return name


def enqueue_delivery(name):
	try:
		frappe.enqueue(WORKER, queue="long", job_id=f"frappe-push-{name}", deduplicate=True, name=name)
	except Exception:
		# The scheduler can enqueue the committed delivery if Redis was unavailable.
		frappe.logger("frappe_push").exception("Could not enqueue push delivery %s", name)


def deliver_due():
	for event in frappe.get_all(DOCTYPE, filters={"status": "Queued"}, limit=100, order_by="creation asc"):
		enqueue_delivery(event.name)

	# A worker can die after handing a message to FCM. Avoid sending it twice.
	cutoff = now_datetime() - timedelta(minutes=30)
	for event in frappe.get_all(DOCTYPE, filters={"status": "Sending", "modified": ["<", cutoff]},
			fields=["name", "kind", "reference_name"], limit=100):
		status = frappe.db.get_value(DOCTYPE, event.name, "status", for_update=True)
		if status == "Sending":
			finish(event, "Unknown", error="The worker stopped before recording the outcome.")


def dispatch(name):
	event = frappe.db.get_value(DOCTYPE, name, ["name", "kind", "reference_name", "status"],
		as_dict=True, for_update=True)
	if not event or event.status != "Queued":
		return
	frappe.db.set_value(DOCTYPE, name, "status", "Sending")
	frappe.db.commit()

	try:
		message = get_message(event)
		if not message:
			finish(event, "Skipped")
			return
		tokens, title, body, path = message
		if not tokens:
			finish(event, "Failed" if event.kind == "Broadcast" else "Skipped", error="No active subscribers.")
			return

		result = send_to_tokens(tokens, title, body, path, event_id=name)
		accepted, failed = result["accepted"], result["failed"]
		status = "Partial" if accepted and failed else "Sent" if accepted else "Failed"
		finish(event, status, accepted, failed, result["error"])
	except Exception:
		frappe.db.rollback()
		frappe.logger("frappe_push").exception("Push delivery failed: %s", name)
		finish(event, "Unknown", error="The worker could not record a definite outcome.")


def finish(event, status, accepted=0, failed=0, error=""):
	frappe.db.set_value(DOCTYPE, event.name, {
		"status": status, "accepted": accepted, "failed": failed, "last_error": error,
	})
	if event.kind == "Broadcast":
		frappe.db.set_value("FCM Broadcast", event.reference_name, {
			"status": status, "sent_count": accepted, "failed_count": failed, "last_error": error,
		})


def get_message(event):
	name = event.reference_name
	if event.kind == "Broadcast":
		doc = frappe.db.get_value("FCM Broadcast", name, ["target", "title", "message", "click_action"],
			as_dict=True)
		if doc:
			return audience_tokens(doc.target), doc.title, doc.message, doc.click_action
	elif event.kind == "Blog":
		doc = frappe.db.get_value("Blog Post", name, ["published", "title", "blog_intro", "content", "route"],
			as_dict=True)
		if doc and doc.published:
			return audience_tokens("Guests"), doc.title, strip_html(doc.blog_intro or doc.content or "")[:120], (
				"/" + (doc.route or f"blog/{name}").lstrip("/")
			)
	elif event.kind == "Notification":
		return notification_message(name)
	elif event.kind == "Order":
		return order_message(event)


def notification_message(name):
	meta = frappe.get_meta("Notification Log")
	title_field = "title" if meta.has_field("title") else "subject"
	body_field = "description" if meta.has_field("description") else "email_content"
	doc = frappe.db.get_value("Notification Log", name,
		["for_user", "from_user", title_field, body_field, "link", "document_type", "document_name"],
		as_dict=True)
	if not doc or not doc.for_user or doc.for_user == "Guest":
		return

	tokens = owned_tokens(doc.for_user)
	title = strip_html(doc.get(title_field) or doc.document_name or "New Alert")
	sender = frappe.db.get_value("User", doc.from_user, "full_name") if doc.from_user else None
	body = strip_html(doc.get(body_field) or "")
	if sender:
		body = f"From {sender}: {body}" if body else f"From {sender}"
	path = doc.link or "/app"
	if not doc.link and doc.document_type and doc.document_name:
		doctype = frappe.scrub(doc.document_type).replace("_", "-")
		path = f"/app/{doctype}/{quote(doc.document_name, safe='')}"
	return tokens, title, body[:120], path


def order_message(event):
	link = frappe.db.get_value("FCM Order Subscription", event.reference_name,
		["subscription", "latest_event", "last_state"], as_dict=True)
	if not link or link.latest_event != event.name:
		return

	token = frappe.db.get_value("FCM Token", link.subscription, TOKEN_FIELDS, as_dict=True)
	if not token or token.user or not token.token_hash:
		return

	docstatus, status, review = link.last_state.split("|", 2)
	if docstatus == "2":
		title, body = "Order cancelled", "Your order was cancelled."
	elif docstatus == "0":
		title, body = "Order received", "We received your order. You can track it from our website."
	else:
		title, body = "Order update", f"Order status: {status or review or 'Submitted'}."
	return [token], title, body, f"/track-order?id={quote(event.reference_name, safe='')}"
