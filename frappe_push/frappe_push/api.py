import frappe
import json

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

@frappe.whitelist()
def subscribe(fcm_token, browser=None, device_id=None):
	user = frappe.session.user
	if user == "Guest":
		return {"success": False, "message": "Not logged in"}
	
	# De-duplicate by both browser AND device_id if available
	if device_id:
		frappe.db.delete("FCM Token", {"user": user, "device_id": device_id})
	
	if browser:
		frappe.db.delete("FCM Token", {"user": user, "browser": browser})
	
	# Special case: delete exact same token
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
		# Only log non-transient errors (NotRegistered is common if users clear browser data)
		if "NotRegistered" not in str(e):
			frappe.log_error(
				title="FCM Send Error",
				message=f"Error: {str(e)}\n\nToken: {token}\nData: {json.dumps(data, indent=2)}"
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
		# Title: Just the document ID or subject
		# Body: Who assigned what
		title = doc.document_name or doc.subject or "New Alert"
		
		from_user_name = frappe.db.get_value("User", doc.from_user, "full_name") or doc.from_user
		body = f"Assigned by {from_user_name}"
		if doc.subject and not doc.document_name:
			body = f"{doc.subject} (from {from_user_name})"
		elif doc.email_content:
			# If there's long content, prepend the sender
			body = f"{from_user_name}: {frappe.utils.strip_html(doc.email_content)}"
		
		# Keep it concise for mobile
		if len(body) > 120:
			body = body[:117] + "..."
		
		send_notification_to_user(
			user=doc.for_user,
			title=title,
			body=body,
			data={
				"document_type": getattr(doc, "document_type", ""),
				"document_name": getattr(doc, "document_name", ""),
				"type": getattr(doc, "type", ""),
				"click_action": doc.link or "/app"
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
				"click_action": f"/app/{frappe.scrub(doc.reference_type)}/{doc.reference_name}" if doc.reference_type and doc.reference_name else "/app/todo"
			}
		)
	except Exception as e:
		frappe.log_error(f"ToDo FCM Hook Error: {str(e)}", "Frappe Push Hook Error")
