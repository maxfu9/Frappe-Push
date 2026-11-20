"""Browser subscriptions owned by a site-issued, HttpOnly cookie."""

import hashlib
import re
import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime

COOKIE = "__Host-frappe-push"
DISCONNECTED = "off"
MAX_AGE = 60 * 60 * 24 * 365
TOKEN_DOCTYPE = "FCM Token"


def digest(value):
	return hashlib.sha256(value.encode()).hexdigest()


def get_browser_key():
	request = getattr(frappe.local, "request", None)
	return request.cookies.get(COOKIE, "") if request is not None else ""


def set_browser_key(value):
	frappe.local.cookie_manager.set_cookie(
		COOKIE, value, secure=True, httponly=True, samesite="Lax", max_age=MAX_AGE
	)


def browser_subscription(for_update=False):
	key = get_browser_key()
	if not re.fullmatch(r"[A-Za-z0-9_-]{43}", key):
		return None

	return frappe.db.get_value(
		TOKEN_DOCTYPE,
		{"browser_key_hash": digest(key)},
		["name", "user", "token_hash"],
		as_dict=True,
		for_update=for_update,
	)


def current_owner():
	return None if frappe.session.user == "Guest" else frappe.session.user


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=60, seconds=60)
def subscribe(fcm_token: str, browser: str | None = None, reconnect: bool = False):
	if not frappe.utils.cint(frappe.db.get_single_value("FCM Config", "enable")):
		frappe.throw(_("Push notifications are disabled."))
	if not re.fullmatch(r"[A-Za-z0-9_:\-]{20,4096}", fcm_token):
		frappe.throw(_("The push registration is invalid."))
	if get_browser_key() == DISCONNECTED and not reconnect:
		return {"success": False}

	subscription = browser_subscription(for_update=True)
	token_hash = digest(fcm_token)
	registered = frappe.db.get_value(TOKEN_DOCTYPE, {"token_hash": token_hash}, "name", for_update=True)
	if registered and (not subscription or subscription.name != registered):
		return {"success": False, "reset_token": True}

	details = {
		"user": current_owner(),
		"fcm_token": fcm_token,
		"token_hash": token_hash,
		"browser": (browser or "")[:140],
		"last_used": now_datetime(),
	}
	if subscription and (subscription.user or None) == details["user"]:
		frappe.db.set_value(TOKEN_DOCTYPE, subscription.name, details)
		set_browser_key(get_browser_key())
	else:
		# A different account gets a new subscription ID so old order links stay detached.
		if subscription:
			frappe.db.delete(TOKEN_DOCTYPE, {"name": subscription.name})
		key = secrets.token_urlsafe(32)
		frappe.get_doc({
			"doctype": TOKEN_DOCTYPE,
			"browser_key_hash": digest(key),
			**details,
		}).insert(ignore_permissions=True)
		set_browser_key(key)
	return {"success": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=60)
def unsubscribe():
	subscription = browser_subscription(for_update=True)
	if subscription:
		frappe.db.delete(TOKEN_DOCTYPE, {"name": subscription.name})
	set_browser_key(DISCONNECTED)
	return {"success": True}


def disconnect_on_logout(login_manager=None):
	if not current_owner():
		return
	subscription = browser_subscription(for_update=True)
	if subscription and subscription.user == current_owner():
		frappe.db.delete(TOKEN_DOCTYPE, {"name": subscription.name})
		set_browser_key(DISCONNECTED)
