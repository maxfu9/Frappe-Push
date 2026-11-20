"""FCM configuration and result handling shared by all delivery paths."""

from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

import firebase_admin
from firebase_admin import credentials, exceptions, messaging

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


TEMPORARY = (exceptions.UnavailableError, exceptions.InternalError, exceptions.ResourceExhaustedError)
CREDENTIAL_ERRORS = (
	exceptions.UnauthenticatedError, exceptions.PermissionDeniedError,
	messaging.SenderIdMismatchError, messaging.ThirdPartyAuthError,
)


def retry_after(error):
	response = error.http_response
	value = response.headers.get("Retry-After") if response is not None else None
	if not value:
		return 0
	try:
		return max(0, int(value))
	except ValueError:
		try:
			seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
			return max(0, int(seconds) + 1)
		except (ValueError, TypeError, OverflowError):
			return 0


def send_to_tokens(tokens, title, body, route="/app", *, event_id="", ttl=86400, group="", device_test=False):
	"""Return known outcomes and identify only explicitly rejected temporary failures."""
	reasons = Counter()
	result = {"accepted": 0, "failed": 0, "unknown": 0, "retry": {}, "delay": 0, "reasons": reasons}
	if not tokens:
		return result

	app = get_fcm_app()
	if not app:
		enabled = frappe.utils.cint(frappe.db.get_single_value("FCM Config", "enable"))
		problem = "Firebase configuration unavailable" if enabled else "Push disabled"
		reasons[problem] = len(tokens)
		result["failed"] = len(tokens)
		return result

	icon = frappe.db.get_single_value("Website Settings", "app_logo") or "/assets/frappe/images/frappe-favicon.png"
	data = {
		"title": str(title or "New Notification")[:160],
		"body": str(body or "")[:480],
		"url": click_path(route),
		"icon": click_path(icon, "/assets/frappe/images/frappe-favicon.png"),
		"event_id": event_id,
		"tag": group or event_id,
	}
	if device_test:
		data["device_test"] = "1"
	headers = {"TTL": str(ttl), "Urgency": "high"}
	if group:
		headers["Topic"] = group

	for start in range(0, len(tokens), 100):
		selected = tokens[start:start + 100]
		active = {
			row.name: row
			for row in frappe.get_all("FCM Token", filters={"name": ["in", [t.name for t in selected]]},
				fields=TOKEN_FIELDS)
		}
		batch = [t for t in selected if t.name in active and t.token_hash == active[t.name].token_hash
			and t.user == active[t.name].user]
		revoked = len(selected) - len(batch)
		if revoked:
			result["failed"] += revoked
			reasons["Subscription changed"] += revoked
		if not batch:
			continue

		try:
			response = messaging.send_each_for_multicast(messaging.MulticastMessage(
				tokens=[t.fcm_token for t in batch], data=data,
				webpush=messaging.WebpushConfig(headers=headers),
			), app=app)
		except Exception as error:
			# Batch-level exceptions do not tell us which sends were accepted.
			result["unknown"] += len(batch)
			reasons[f"Unknown batch outcome ({type(error).__name__})"] += len(batch)
			continue

		for token, outcome in zip(batch, response.responses, strict=True):
			error = outcome.exception
			if not error:
				result["accepted"] += 1
				continue

			reason = "Firebase credentials rejected" if isinstance(error, CREDENTIAL_ERRORS) else type(error).__name__
			reasons[reason] += 1
			if isinstance(error, TEMPORARY) and getattr(error.http_response, "status_code", None) in (429, 500, 503):
				result["retry"][token.name] = token.token_hash
				minimum = 60 if isinstance(error, exceptions.ResourceExhaustedError) else 15
				result["delay"] = max(result["delay"], minimum, retry_after(error))
				continue

			result["failed"] += 1
			if isinstance(error, messaging.UnregisteredError):
				frappe.db.delete("FCM Token", {"name": token.name, "token_hash": token.token_hash})
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
