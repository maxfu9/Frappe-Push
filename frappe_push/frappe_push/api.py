import frappe
import json
from frappe import _

@frappe.whitelist()
def send_promo_broadcast(title, message, click_action="/app"):
	"""
	Sends a push notification to ALL subscribers in the database.
	Used for marketing and flash sales.
	Only Administrators and System Managers can call this.
	"""
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not authorized to send broadcasts."))

	import firebase_admin
	from firebase_admin import messaging
	
	app = get_fcm_app()
	if not app:
		frappe.throw(_("FCM is not configured or enabled."))

	# Fetch all unique tokens
	tokens = frappe.db.get_all("FCM Token", fields=["fcm_token"])
	token_list = [t.fcm_token for t in tokens if t.fcm_token]

	if not token_list:
		return {"status": "error", "message": "No subscribers found."}

	# FCM Multicast Limit: 500 tokens per batch
	success_count = 0
	for i in range(0, len(token_list), 500):
		batch = token_list[i:i + 500]
		
		# Build a simple notification
		# Using Website icon for branding
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

	return {"status": "success", "sent_count": success_count}

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
			frappe.log_error(f"FCM Initialization Error: {str(e)}", "Frappe Push")
			return None

@frappe.whitelist()
def get_public_config():
	config = frappe.get_single("FCM Config")
	if not config.enable:
		return None
	
	# Fetch site logo for branding
	site_logo = frappe.db.get_single_value("Website Settings", "app_logo") or "/assets/frappe/images/frappe-favicon.png"
	
	return {
		"apiKey": config.api_key,
		"projectId": config.project_id,
		"messagingSenderId": config.messaging_sender_id,
		"appId": config.app_id,
		"vapidKey": config.vapid_key,
		"siteLogo": frappe.utils.get_url(site_logo)
	}

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
				notification=messaging.WebpushNotification(
					icon=icon,
					badge=icon,
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
	# DEBUG
	frappe.log_error(f"Attempting to send notification to user {user}", "Frappe Push Dispatch")

	# De-duplication Debounce: Prevent identical notifications in a 5-second window
	# This handles situations where multiple hooks fire for the same event
	doc_name = data.get("document_name") if data else ""
	doc_type = data.get("document_type") if data else ""
	debounce_key = f"frappe_push_debounce:{user}:{frappe.scrub(title)}:{doc_type}:{doc_name}"
	
	if frappe.cache().get_value(debounce_key):
		frappe.log_error(f"Debouncing duplicate notification for user {user}: {title}", "Frappe Push Debounce")
		return False
	
	# Set debounce for 5 seconds
	frappe.cache().set_value(debounce_key, 1, expires_in_sec=5)

	# Get all tokens for the user, ordered by last used
	tokens = frappe.get_all("FCM Token", 
		filters={"user": user}, 
		fields=["fcm_token", "browser"],
		order_by="last_used desc"
	)
	
	if not tokens:
		frappe.log_error(f"No FCM tokens found for user {user}. Open the app in browser to register.", "Frappe Push Dispatch")
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
	
	frappe.log_error(f"Found {len(unique_tokens)} unique device targets for user {user} (after OS filtering)", "Frappe Push Dispatch")
	
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
		if not doc.for_user:
			return
		
		# Skip if FCM is disabled
		config = frappe.get_single("FCM Config")
		if not config.enable:
			return

		# Inclusive logic: Handle all Notification Logs
		frappe.log_error(f"Notification Log Hook Triggered for {doc.for_user}", "Frappe Push Hook")
		
		# NATIVE REFINE: 
		# Title: Subject (e.g. "New Customer assigned to you")
		# Body: From [User] + Message Content
		title = doc.subject or doc.document_name or "New Alert"
		
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
		frappe.log_error(f"FCM Push Hook Error: {str(e)}", "Frappe Push Hook Error")

def trigger_todo_notification_push(doc, method=None):
	"""Hook for ToDo after_insert (Assignments)"""
	try:
		if not doc.allocated_to:
			return
		
		# Skip if FCM is disabled
		config = frappe.get_single("FCM Config")
		if not config.enable:
			return
		
		frappe.log_error(f"ToDo Hook Triggered for {doc.allocated_to}", "Frappe Push Hook")

		# NATIVE REFINE:
		# Title: Document ID
		# Body: Assigned by [User]
		title = doc.name
		
		assigned_by = frappe.db.get_value("User", doc.owner, "full_name") or doc.owner
		body = f"Assigned by {assigned_by}"
		
		if doc.reference_type and doc.reference_name:
			title = doc.reference_name
			body = f"New {doc.reference_type} assigned by {assigned_by}"
		
		if doc.description:
			body += f": {doc.description}"

		# Keep it concise
		if len(body) > 120:
			body = body[:117] + "..."
		
		send_notification_to_user(
			user=doc.allocated_to,
			title=title,
			body=frappe.utils.strip_html(body),
			data={
				"document_type": doc.reference_type,
				"document_name": doc.reference_name,
				"type": "Assignment",
				"click_action": f"/app/{frappe.scrub(doc.reference_type).replace('_', '-')}/{doc.reference_name}" if doc.reference_type and doc.reference_name else "/app/todo"
			}
		)
	except Exception as e:
		frappe.log_error(f"ToDo FCM Hook Error: {str(e)}", "Frappe Push Hook Error")
