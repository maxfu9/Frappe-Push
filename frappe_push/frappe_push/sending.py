"""FCM configuration and result handling shared by all delivery paths."""

import hashlib
import json
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

import firebase_admin
from firebase_admin import credentials, messaging

import frappe

TOKEN_FIELDS = ["name", "user", "fcm_token", "token_hash"]
_app_lock = Lock()


def click_path(value, default="/app"):
	value = value or default
	if not isinstance(value, str) or any(char in value for char in ("\\", "\r", "\n", "\t")):
		return default
	try:
		url = urlsplit(value)
		site = urlsplit(frappe.utils.get_url())
	except ValueError:
		return default
	if url.scheme or url.netloc:
		if (url.scheme, url.netloc) != (site.scheme, site.netloc):
			return default
	if not url.path.startswith("/") or url.path.startswith("//"):
		return default
	return urlunsplit(("", "", url.path, url.query, url.fragment))


def get_fcm_app():
	config = frappe.get_single("FCM Config")
	if not frappe.utils.cint(config.enable):
		return None
	try:
		account = config.get_password("fcm_service_account_json")
		name = "frappe_push_" + hashlib.sha256(frappe.local.site.encode()).hexdigest()
		fingerprint = hashlib.sha256((config.project_id + "\0" + account).encode()).hexdigest()
		with _app_lock:
			try:
				app = firebase_admin.get_app(name)
			except ValueError:
				app = None
			if app is not None and app.frappe_push_fingerprint == fingerprint:
				return app

			info = json.loads(account)
			if info.get("project_id") != config.project_id:
				frappe.logger("frappe_push").error("FCM credential project does not match FCM Config")
				return None
			credential = credentials.Certificate(info)
			if app is not None:
				firebase_admin.delete_app(app)
			app = firebase_admin.initialize_app(credential, name=name)
			app.frappe_push_fingerprint = fingerprint
			return app
	except Exception:
		frappe.logger("frappe_push").exception("Could not initialize Firebase for this site")
		return None


def send_to_tokens(tokens, title, body, route="/app", *, event_id=""):
	"""Return counts of accepted and failed sends. Firebase acceptance is not device delivery."""
	result = {"accepted": 0, "failed": 0, "error": ""}
	if not tokens:
		return result
	app = get_fcm_app()
	if not app:
		return {"accepted": 0, "failed": len(tokens), "error": "FCM is disabled or misconfigured."}

	icon = frappe.db.get_single_value("Website Settings", "app_logo") or "/assets/frappe/images/frappe-favicon.png"
	data = {
		"title": str(title or "New Notification")[:160],
		"body": str(body or "")[:480],
		"url": click_path(route),
		"icon": click_path(icon, "/assets/frappe/images/frappe-favicon.png"),
		"event_id": event_id,
	}
	for start in range(0, len(tokens), 500):
		batch = tokens[start:start + 500]
		# Resolve the current row immediately before sending. Logout, disconnect, and
		# account changes can revoke a token after the audience is selected.
		active = {
			row.name: row
			for row in frappe.get_all("FCM Token", filters={"name": ["in", [t.name for t in batch]]},
				fields=TOKEN_FIELDS)
		}
		batch = [t for t in batch if t.name in active and t.token_hash == active[t.name].token_hash
			and t.user == active[t.name].user]
		if not batch:
			continue

		try:
			response = messaging.send_each_for_multicast(messaging.MulticastMessage(
				tokens=[t.fcm_token for t in batch],
				data=data,
				webpush=messaging.WebpushConfig(headers={"TTL": "86400", "Urgency": "high"}),
			), app=app)
		except Exception as error:
			result["failed"] += len(batch)
			result["error"] = type(error).__name__
			frappe.logger("frappe_push").warning("FCM batch failed (%s)", type(error).__name__)
			continue

		result["accepted"] += response.success_count
		result["failed"] += response.failure_count
		for token, outcome in zip(batch, response.responses, strict=True):
			if isinstance(outcome.exception, messaging.UnregisteredError):
				frappe.db.delete("FCM Token", {"name": token.name, "token_hash": token.token_hash})
			elif outcome.exception:
				frappe.logger("frappe_push").warning("FCM rejected a message (%s)", type(outcome.exception).__name__)
	return result


def owned_tokens(user):
	return frappe.get_all("FCM Token", filters={"user": user, "token_hash": ["is", "set"]},
		fields=TOKEN_FIELDS)


def audience_tokens(target):
	if target == "Guests":
		return frappe.get_all("FCM Token", filters={"user": ["is", "not set"], "token_hash": ["is", "set"]},
			fields=TOKEN_FIELDS)
	if target == "Both":
		return frappe.get_all("FCM Token", filters={"token_hash": ["is", "set"]}, fields=TOKEN_FIELDS)
	if target == "Staff":
		tokens = frappe.qb.DocType("FCM Token")
		users = frappe.qb.DocType("User")
		return (frappe.qb.from_(tokens).join(users).on(tokens.user == users.name)
			.select(tokens.name, tokens.user, tokens.fcm_token, tokens.token_hash)
			.where((users.user_type == "System User") & (users.enabled == 1) & tokens.token_hash.isnotnull())
			.run(as_dict=True))
	raise ValueError("Unknown notification audience")
