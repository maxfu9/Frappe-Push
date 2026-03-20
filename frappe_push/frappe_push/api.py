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
	
	return {
		"apiKey": config.api_key,
		"projectId": config.project_id,
		"messagingSenderId": config.messaging_sender_id,
		"appId": config.app_id,
		"vapidKey": config.vapid_key
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
		
		# Hybrid payload for maximum reliability
		# Adding 'click_action' to both notification and data for broad compatibility
		click_action = clean_data.get("click_action", "/app")
		
		message = messaging.Message(
			notification=messaging.Notification(
				title=str(title or "New Notification"),
				body=str(body or ""),
			),
			# Platform-specific options for better reliability
			webpush=messaging.WebpushConfig(
				fcm_options=messaging.WebpushFCMOptions(
					link=click_action
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

	# De-duplicate by device_id and browser
	unique_tokens = []
	seen_keys = set()
	
	for t in tokens:
		# Priority Key: Device ID > Browser > Token
		key = t.device_id or t.browser or t.fcm_token
		if key not in seen_keys:
			unique_tokens.append(t.fcm_token)
			seen_keys.add(key)
	
	frappe.log_error(f"Found {len(unique_tokens)} unique tokens for user {user}", "Frappe Push Dispatch")
	
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
		# This is our main reliable trigger
		frappe.log_error(f"Notification Log Hook Triggered for {doc.for_user}", "Frappe Push Hook")
		
		send_notification_to_user(
			user=doc.for_user,
			title=doc.subject or "New Notification",
			body=frappe.utils.strip_html(doc.email_content or doc.subject or "New Notification"),
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

		# Build a nice message
		title = "New Assignment"
		body = f"A new task has been assigned to you: {doc.description or 'No description'}"
		if doc.reference_type and doc.reference_name:
			title = f"New {doc.reference_type} Assignment"
			body = f"{doc.reference_type} {doc.reference_name} has been assigned to you."
		
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
