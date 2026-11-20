"""Durable event records and delivery after the originating transaction commits."""

from collections import Counter
from datetime import timedelta
import json
from random import randint
from urllib.parse import quote

import frappe
from frappe.utils import cint, get_datetime, now_datetime, strip_html

from frappe_push.frappe_push.sending import TOKEN_FIELDS, audience_tokens, owned_tokens, send_to_tokens
from frappe_push.frappe_push.subscriptions import digest

DOCTYPE = "FCM Delivery"
WORKER = "frappe_push.frappe_push.delivery.dispatch"
MAX_ATTEMPTS = 3
LIFETIME = {"Notification": 300, "Order": 1800, "Device Test": 120}
DELIVERY_FIELDS = [
	"name", "kind", "reference_name", "status", "creation", "attempts", "accepted", "failed",
	"unknown_count", "retry_at", "retry_targets", "failure_summary",
]


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
	for status, filters in (("Queued", {}), ("Retry Scheduled", {"retry_at": ["<=", now_datetime()]})):
		for event in frappe.get_all(DOCTYPE, filters={"status": status, **filters},
				limit=100, order_by="modified asc"):
			enqueue_delivery(event.name)

	cutoff = now_datetime() - timedelta(minutes=30)
	for row in frappe.get_all(DOCTYPE, filters={"status": "Sending", "modified": ["<", cutoff]}, limit=100):
		event = frappe.db.get_value(DOCTYPE, row.name, DELIVERY_FIELDS, as_dict=True, for_update=True)
		if event and event.status == "Sending":
			finish(event, "Unknown", error="The worker stopped before recording the outcome.")


def dispatch(name):
	event = frappe.db.get_value(DOCTYPE, name, DELIVERY_FIELDS, as_dict=True, for_update=True)
	if not event or event.status not in ("Queued", "Retry Scheduled"):
		return
	current = now_datetime()
	if event.retry_at and current < get_datetime(event.retry_at):
		return

	pending = json.loads(event.retry_targets or "{}")
	deadline = get_datetime(event.creation) + timedelta(seconds=LIFETIME.get(event.kind, 86400))
	if current >= deadline:
		event.failed = cint(event.failed) + len(pending)
		finish(event, outcome_status(event, fallback="Skipped"), error="The notification expired.")
		return

	event.attempts = cint(event.attempts) + 1
	frappe.db.set_value(DOCTYPE, name, {"status": "Sending", "attempts": event.attempts})
	frappe.db.commit()

	try:
		message = get_message(event)
		tokens, title, body, route = message or ([], "", "", "")
		if pending:
			tokens = [t for t in tokens if pending.get(t.name) == t.token_hash]
			event.failed = cint(event.failed) + len(pending) - len(tokens)
		if not tokens:
			fallback = "Failed" if event.kind == "Broadcast" else "Skipped"
			finish(event, outcome_status(event, fallback=fallback), error="No eligible recipients remain.")
			return

		result = send_to_tokens(tokens, title, body, route, event_id=name,
			ttl=max(0, int((deadline - now_datetime()).total_seconds())),
			group=digest("order:" + event.reference_name)[:32] if event.kind == "Order" else "",
			device_test=event.kind == "Device Test")
		handle_result(event, result, deadline)
	except Exception:
		frappe.db.rollback()
		frappe.logger("frappe_push").exception("Push delivery failed: %s", name)
		finish(event, "Unknown", error="The worker could not record a definite outcome.")


def handle_result(event, result, deadline):
	event.accepted = cint(event.accepted) + result["accepted"]
	event.failed = cint(event.failed) + result["failed"]
	event.unknown_count = cint(event.unknown_count) + result["unknown"]
	reasons = Counter(json.loads(event.failure_summary or "{}"))
	reasons.update(result["reasons"])
	event.failure_summary = json.dumps(reasons, sort_keys=True) if reasons else ""

	if result["reasons"].keys() & {"Firebase credentials rejected", "Firebase configuration unavailable"}:
		flag_configuration_error(event.name)

	pending = result["retry"]
	if pending:
		delay = max(result["delay"], 30 * (2 ** (event.attempts - 1))) + randint(0, 10)
		next_attempt = now_datetime() + timedelta(seconds=delay)
		if event.attempts < MAX_ATTEMPTS and next_attempt < deadline:
			finish(event, "Retry Scheduled", retry_at=next_attempt, pending=pending)
			return
		event.failed += len(pending)
		reasons["Retry limit or notification lifetime reached"] += len(pending)
		event.failure_summary = json.dumps(reasons, sort_keys=True)

	error = ", ".join(sorted(reasons)) if reasons else ""
	finish(event, outcome_status(event), error=error)


def flag_configuration_error(event_id):
	key = "frappe_push_configuration_error"
	if not frappe.cache().get_value(key):
		frappe.cache().set_value(key, 1, expires_in_sec=3600)
		frappe.log_error(title="Frappe Push Firebase configuration", message=f"Check FCM Config. Delivery: {event_id}")


def outcome_status(event, fallback="Failed"):
	if event.unknown_count:
		return "Unknown"
	if event.accepted:
		return "Partial" if event.failed else "Sent"
	return "Failed" if event.failed else fallback


def finish(event, status, *, error="", retry_at=None, pending=None):
	frappe.db.set_value(DOCTYPE, event.name, {
		"status": status, "accepted": cint(event.accepted), "failed": cint(event.failed),
		"unknown_count": cint(event.unknown_count), "failure_summary": event.failure_summary,
		"last_error": error, "retry_at": retry_at, "retry_targets": json.dumps(pending) if pending else None,
	})
	if event.kind == "Broadcast":
		frappe.db.set_value("FCM Broadcast", event.reference_name, {
			"status": status, "sent_count": cint(event.accepted), "failed_count": cint(event.failed),
			"last_error": error,
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
	elif event.kind == "Device Test":
		token = frappe.db.get_value("FCM Token", name, TOKEN_FIELDS, as_dict=True)
		if token and token.token_hash:
			return [token], "Frappe Push test", "This device received a test notification.", "/"


def notification_message(name):
	doc = frappe.db.get_value("Notification Log", name,
		["for_user", "type", "link", "document_type", "document_name"], as_dict=True)
	if not doc or not doc.for_user or doc.for_user == "Guest":
		return

	tokens = owned_tokens(doc.for_user)
	title = {"Assignment": "New assignment", "Mention": "New mention"}.get(doc.type, "New Desk notification")
	body = "Open Desk to view the details."
	path = doc.link or "/app"
	if not doc.link and doc.document_type and doc.document_name:
		doctype = frappe.scrub(doc.document_type).replace("_", "-")
		path = f"/app/{doctype}/{quote(doc.document_name, safe='')}"
	return tokens, title, body, path


def order_message(event):
	link = frappe.db.get_value("FCM Order Subscription", event.reference_name,
		["subscription", "latest_event", "last_state"], as_dict=True)
	if not link or link.latest_event != event.name:
		return

	token = frappe.db.get_value("FCM Token", link.subscription, TOKEN_FIELDS, as_dict=True)
	if not token or token.user or not token.token_hash:
		return

	return [token], "Order update", "Open order tracking to view the latest status.", f"/track-order?id={quote(event.reference_name, safe='')}"
