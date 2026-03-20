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
	
	# De-duplicate: Remove old tokens for this user and browser
	frappe.db.delete("FCM Token", {"user": user, "browser": browser})
	
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
		message = messaging.Message(
			notification=messaging.Notification(
				title=title,
				body=body,
			),
			data=data or {},
			token=token,
		)
		response = messaging.send(message, app=app)
		return True
	except Exception as e:
		frappe.log_error(f"FCM Send Error: {str(e)}", "Frappe Push")
		return False

@frappe.whitelist()
def send_notification_to_user(user, title, body, data=None):
	# Get all tokens for the user, ordered by last used
	tokens = frappe.get_all("FCM Token", 
		filters={"user": user}, 
		fields=["fcm_token", "browser"],
		order_by="last_used desc"
	)
	
	# De-duplicate by browser in memory to be extra safe
	unique_tokens = []
	seen_browsers = set()
	
	for t in tokens:
		# If browser is unknown, treat it as unique
		browser_key = t.browser or t.fcm_token
		if browser_key not in seen_browsers:
			unique_tokens.append(t.fcm_token)
			seen_browsers.add(browser_key)
	
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

		# De-duplicate: Assignment notifications are handled by trigger_todo_notification_push
		if doc.type == "Assignment" or doc.document_type == "ToDo":
			return
		
		# Enqueue the push to avoid blocking the main thread
		frappe.enqueue(
			"frappe_push.frappe_push.api.send_notification_to_user",
			user=doc.for_user,
			title=doc.subject or "New Notification",
			body=frappe.utils.strip_html(doc.email_content or doc.subject or "New Notification"),
			data={
				"document_type": doc.document_type,
				"document_name": doc.document_name,
				"type": doc.type,
				"click_action": doc.link or (f"/app/{frappe.scrub(doc.document_type)}/{doc.document_name}" if doc.document_type and doc.document_name else "/app")
			},
			now=frappe.flags.in_test
		)
	except Exception as e:
		# Don't break the original notification system if push fails
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
		
		# Build a nice message
		title = "New Assignment"
		body = f"A new task has been assigned to you: {doc.description or 'No description'}"
		if doc.reference_type and doc.reference_name:
			title = f"New {doc.reference_type} Assignment"
			body = f"{doc.reference_type} {doc.reference_name} has been assigned to you."
		
		# Enqueue the push
		frappe.enqueue(
			"frappe_push.frappe_push.api.send_notification_to_user",
			user=doc.allocated_to,
			title=title,
			body=frappe.utils.strip_html(body),
			data={
				"document_type": doc.reference_type,
				"document_name": doc.reference_name,
				"type": "Assignment",
				"click_action": f"/app/{frappe.scrub(doc.reference_type)}/{doc.reference_name}" if doc.reference_type and doc.reference_name else "/app/todo"
			},
			now=frappe.flags.in_test
		)
	except Exception as e:
		frappe.log_error(f"ToDo FCM Hook Error: {str(e)}", "Frappe Push Hook Error")
