import frappe
import json
from frappe import _

@frappe.whitelist()
def send_promo_broadcast(title, message, click_action="/app", target="Both"):
	"""
	Sends a push notification to ALL or specific groups of subscribers from the UI.
	target: "Both", "Guests", or "Staff"
	"""
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not authorized to send broadcasts."))

	return _send_promo_broadcast(title, message, click_action, target)

def _send_promo_broadcast(title, message, click_action="/app", target="Both"):
	"""
	Internal broadcasting engine without permission checks.
	"""
	import firebase_admin
	from firebase_admin import messaging
	
	app = get_fcm_app()
	if not app:
		return {"status": "error", "message": _("FCM is not configured or enabled.")}

	# Build filters based on target
	filters = {}
	if target in ["Guest", "Guests"]:
		filters["user"] = ["in", ["Guest", None, ""]]
	elif target == "Staff":
		filters["user"] = ["not in", ["Guest", None, ""]]
	
	# Fetch unique tokens matching the filter
	tokens = frappe.db.get_all("FCM Token", filters=filters, fields=["fcm_token"])
	token_list = list(set([t.fcm_token for t in tokens if t.fcm_token]))

	if not token_list:
		return {"status": "error", "message": f"No {target} subscribers found."}

	# FCM Multicast Limit: 500 tokens per batch
	success_count = 0
	for i in range(0, len(token_list), 500):
		batch = token_list[i:i + 500]
		
		site_logo = frappe.db.get_single_value("Website Settings", "app_logo") or "/assets/frappe/images/frappe-favicon.png"
		icon_url = frappe.utils.get_url(site_logo)

		multicast_message = messaging.MulticastMessage(
			notification=messaging.Notification(
				title=str(title),
				body=str(message),
			),
			webpush=messaging.WebpushConfig(
				notification=messaging.WebpushNotification(
					icon=icon_url,
					badge=icon_url
				),
				fcm_options=messaging.WebpushFCMOptions(
					link=frappe.utils.get_url(click_action)
				)
			),
			tokens=batch,
		)
		
		response = messaging.send_each_for_multicast(multicast_message, app=app)
		success_count += response.success_count

	return {"status": "success", "sent_count": success_count, "target": target}

def get_fcm_app():
	import firebase_admin
	from firebase_admin import credentials
	
	try:
		return firebase_admin.get_app("frappe_push")
	except ValueError:
		config = frappe.get_single("FCM Config")
		if not config.enable:
			return None
		
		# Load service account from JSON field
		try:
			service_account_info = json.loads(config.get_password("fcm_service_account_json"))
			cred = credentials.Certificate(service_account_info)
			return firebase_admin.initialize_app(cred, name="frappe_push")
		except Exception as e:
			frappe.log_error(title="FCM Initialization Error", message=str(e))
			return None

@frappe.whitelist(allow_guest=True)
def get_public_config():
	config = frappe.get_single("FCM Config")
	if not str(config.enable) == "1":
		return None
	
	# Fetch site logo for branding
	site_logo = frappe.db.get_single_value("Website Settings", "app_logo") or "/assets/frappe/images/frappe-favicon.png"
	
	res = {
		"apiKey": config.api_key,
		"projectId": config.project_id,
		"messagingSenderId": str(config.messaging_sender_id) if config.messaging_sender_id else None,
		"appId": config.app_id,
		"vapidKey": config.vapid_key,
		"siteLogo": frappe.utils.get_url(site_logo)
	}
	
	# LOG EXACT OUTPUT FOR DEBUGGING
	return res

@frappe.whitelist(allow_guest=True)
def subscribe(fcm_token, browser=None, device_id=None):
	user = frappe.session.user
	if user == "Guest":
		user = None
	
	# De-duplicate: If this token OR device_id already exists, remove old ones
	# We prioritize keeping the newest subscription for a device
	if device_id:
		frappe.db.delete("FCM Token", {"device_id": device_id})
	
	# Special case: delete exact same token if it exists elsewhere
	frappe.db.delete("FCM Token", {"fcm_token": fcm_token})
	
	# Insert new token
	doc = frappe.get_doc({
		"doctype": "FCM Token",
		"user": user,
		"fcm_token": fcm_token,
		"browser": browser,
		"device_id": device_id,
		"last_used": frappe.utils.now_datetime()
	})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	
	return {"success": True}

@frappe.whitelist()
def unsubscribe(fcm_token):
	frappe.db.delete("FCM Token", {"fcm_token": fcm_token})
	return {"success": True}

def send_push_notification(token, title, body, data=None):
	from firebase_admin import messaging
	app = get_fcm_app()
	if not app:
		return False
	
	try:
		# FCM requirements: All keys and values in 'data' must be STRINGS.
		clean_data = {}
		if data:
			for k, v in data.items():
				clean_data[str(k)] = str(v) if v is not None else ""
		
		# Fetch icon for notification
		icon = data.get("notification_icon") if data else None
		if not icon:
			site_logo = frappe.db.get_single_value("Website Settings", "app_logo") or "/assets/frappe/images/frappe-favicon.png"
			icon = frappe.utils.get_url(site_logo)

		# Hybrid payload for maximum reliability
		# Adding 'click_action' to both notification and data for broad compatibility
		click_action_url = frappe.utils.get_url(clean_data.get("click_action", "/app"))
		
		# Ensure clean_data also has the full URL for the Service Worker
		clean_data["click_action_url"] = click_action_url
		
		message = messaging.Message(
			notification=messaging.Notification(
				title=str(title or "New Notification"),
				body=str(body or ""),
				image=icon if icon.startswith("http") else None
			),
			# Platform-specific options for better reliability
			webpush=messaging.WebpushConfig(
				headers={
					"Urgency": "high"  # Ensures the notification is delivered immediately even if browser is closed
				},
				notification=messaging.WebpushNotification(
					icon=icon,
					badge=icon,
					tag=f"{frappe.generate_hash(token, 6)}-{str(clean_data.get('document_name') or frappe.generate_hash(length=8))}", # Profile-specific unique tag
					renotify=True,      # Wakes the device for subsequent notifications
					vibrate=[200, 100, 200],  # Standard vibration pattern
					require_interaction=True, # Keeps the notification until dismissed
					data=clean_data # This makes data available in SW event.notification.data
				),
				fcm_options=messaging.WebpushFCMOptions(
					link=click_action_url
				)
			),
			data=clean_data,
			token=str(token),
		)
		
		response = messaging.send(message, app=app)
		return True
	except Exception as e:
		error_str = str(e)
		# Token cleanup: If FCM says the token is invalid or expired, delete it!
		if "NotRegistered" in error_str or "unregistered" in error_str.lower():
			frappe.db.delete("FCM Token", {"fcm_token": token})
			frappe.db.commit()
			return False
		
		# Log other significant errors
		frappe.log_error(
			title="FCM Send Error",
			message=f"Error: {error_str}\n\nToken: {token}\nData: {json.dumps(data, indent=2)}"
		)
		return False

def get_device_signature(ua):
	if not ua:
		return "unknown"
	ua = ua.lower()
	if "iphone" in ua or "ipad" in ua or "ipod" in ua:
		return "ios"
	if "android" in ua:
		return "android"
	if "macintosh" in ua or "mac os x" in ua:
		return "macos"
	if "windows" in ua:
		return "windows"
	if "linux" in ua:
		return "linux"
	return ua[:50]

@frappe.whitelist(allow_guest=True)
def trigger_guest_order_push(doc, method=None):
	"""
	Hook to notify guest customers about their order status.
	Requires fcm_device_id to be stored on the Sales Order.
	"""
	if not hasattr(doc, "fcm_device_id") or not doc.fcm_device_id:
		return
	
	import firebase_admin
	from firebase_admin import messaging
	
	# Find token for this device_id
	token = frappe.db.get_value("FCM Token", {"device_id": doc.fcm_device_id}, "fcm_token")
	if not token:
		return
	
	title = f"Order {doc.name} Update"
	body = f"Your order has been updated. Status: {doc.status}"
	
	if method == "on_submit":
		title = f"Order {doc.name} Confirmed! 🎉"
		body = f"Thank you! Your order {doc.name} has been confirmed and is being processed."

	send_push_notification(
		token=token,
		title=title,
		body=body,
		data={
			"document_type": "Sales Order",
			"document_name": doc.name,
			"click_action": f"/app/sales-order/{doc.name}"
		}
	)

@frappe.whitelist()
def send_notification_to_user(user, title, body, data=None):

	# De-duplication Debounce: Prevent identical notifications in a 5-second window
	# This handles situations where multiple hooks fire for the same event
	doc_name = data.get("document_name") if data else ""
	doc_type = data.get("document_type") if data else ""
	debounce_key = f"frappe_push_debounce:{user}:{frappe.scrub(title)}:{doc_type}:{doc_name}"
	
	if frappe.cache().get_value(debounce_key):
		return False
	
	# Set debounce for 2 seconds (Reduced from 5s for better responsiveness)
	frappe.cache().set_value(debounce_key, 1, expires_in_sec=2)

	# Normalize 'Guest' user ID
	search_user = user
	if user == "Guest":
		search_user = None
		
	# Get all tokens for the user, ordered by last used
	tokens = frappe.get_all("FCM Token", 
		filters={"user": ["in", [search_user, "Guest", ""] if search_user is None else [search_user]]}, 
		fields=["fcm_token", "browser", "device_id"],
		order_by="last_used desc"
	)
	
	if not tokens:
		return False

	# Aggressive de-duplication by OS/Device type
	unique_tokens = []
	seen_signatures = set()
	
	for t in tokens:
		# Priority 1: Device ID (if available from new bundle.js)
		# Priority 2: OS Signature (ios, android, macos, etc.)
		sig = t.device_id or get_device_signature(t.browser)
		
		if sig not in seen_signatures:
			unique_tokens.append(t.fcm_token)
			seen_signatures.add(sig)
	
	success_count = 0
	for token in unique_tokens:
		if send_push_notification(token, title, body, data):
			success_count += 1
	
	return success_count > 0


@frappe.whitelist(allow_guest=True)
def get_service_worker():
	from werkzeug.wrappers import Response
	
	config = frappe.get_single("FCM Config")
	sw_path = frappe.get_app_path("frappe_push", "public", "js", "firebase-messaging-sw.js")
	with open(sw_path, "r") as f:
		js_content = f.read()
	
	# Template the config
	firebase_config = {
		"apiKey": config.api_key,
		"projectId": config.project_id,
		"messagingSenderId": config.messaging_sender_id,
		"appId": config.app_id
	}
	
	# Inject into JS
	template = f"const firebaseConfig = {json.dumps(firebase_config)};"
	js_content = js_content.replace("const firebaseConfig = {};", template)
	
	response = Response(js_content, mimetype="application/javascript")
	response.headers["Service-Worker-Allowed"] = "/"
	return response

def trigger_notification_log_push(doc, method=None):
	"""Hook for Notification Log after_insert"""
	try:
		# If user is None or Guest, we handle it as a broadcast/guest target
		is_guest_target = not doc.for_user or doc.for_user == "Guest"
		
		# Skip if FCM is disabled
		config = frappe.get_single("FCM Config")
		if not config.enable:
			return

		# Inclusive logic: Handle all Notification Logs
		# NATIVE REFINE: 
		# Title: Subject (e.g. "New Customer assigned to you")
		# Body: From [User] + Message Content
		# STRIP HTML from title to prevent <strong> tags seen in desk
		title = frappe.utils.strip_html(doc.subject or doc.document_name or "New Alert")
		
		from_user_name = frappe.db.get_value("User", doc.from_user, "full_name") or doc.from_user
		
		# Build body: Sender + Content
		content = frappe.utils.strip_html(doc.email_content or "")
		body = f"From {from_user_name}"
		if content:
			body = f"From {from_user_name}: {content}"
		elif doc.document_name:
			body = f"From {from_user_name} regarding {doc.document_name}"
		
		if len(body) > 120:
			body = body[:117] + "..."
		
		# ROBUST LINK GENERATION:
		# If doc.document_type and doc.document_name are present, use them!
		click_action = doc.link or "/app"
		if doc.document_type and doc.document_name:
			# Use the standard /app/doctype/name format
			# URLs use kebab-case (hyphens), not snake_case (underscores)
			scrubbed_doctype = frappe.scrub(doc.document_type).replace("_", "-")
			click_action = f"/app/{scrubbed_doctype}/{doc.document_name}"
		
		if is_guest_target:
			# If it's for Guests, we broadcast to all guests
			_send_promo_broadcast(
				title=title,
				message=body,
				click_action=click_action,
				target="Guests"
			)
		else:
			send_notification_to_user(
				user=doc.for_user,
				title=title,
				body=body,
				data={
					"document_type": getattr(doc, "document_type", ""),
					"document_name": getattr(doc, "document_name", ""),
					"type": getattr(doc, "type", ""),
					"click_action": click_action
				}
			)
	except Exception as e:
		frappe.log_error(title="Frappe Push Hook Error", message=str(e))

def trigger_blog_post_push(doc, method=None):
	"""Hook for Blog Post after_insert / on_update"""
	try:
		if not doc.published:
			return
		
		# Prevent duplicate notifications on every edit after publishing
		if method == "on_update":
			previous_doc = doc.get_doc_before_save()
			if previous_doc and previous_doc.published:
				return

		# Skip if FCM is disabled
		config = frappe.get_single("FCM Config")
		if not config.enable:
			return

		title = doc.title
		body = frappe.utils.strip_html(doc.blog_intro or doc.content or "")[:120]
		if len(body) >= 120:
			body = body[:117] + "..."
		
		# Relative URL for blog
		click_action = f"/{doc.route}" if doc.route else f"/blog/{doc.name}"

		_send_promo_broadcast(
			title=title,
			message=body,
			click_action=click_action,
			target="Guests"
		)
	except Exception as e:
		frappe.log_error(title="Frappe Push Blog Error", message=str(e))

def trigger_todo_notification_push(doc, method=None):
	"""Placeholder to prevent AttributeError after hook removal until cache is cleared"""
	pass
