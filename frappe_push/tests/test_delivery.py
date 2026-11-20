"""Focused tests for delivery decisions without contacting Firebase."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from frappe_push.frappe_push import api, delivery, order_push, sending, subscriptions


class TestDelivery(TestCase):
	def test_all_failed_broadcast_reports_failure(self):
		event = frappe._dict(name="event", kind="Broadcast", status="Queued")
		with (patch.object(delivery, "frappe") as framework,
			patch.object(delivery, "get_message", return_value=([object()], "Title", "Body", "/")),
			patch.object(delivery, "send_to_tokens", return_value={"accepted": 0, "failed": 1, "error": ""}),
			patch.object(delivery, "finish") as finish):
			framework.db.get_value.return_value = event
			delivery.dispatch("event")
			framework.db.commit.assert_called_once()
			finish.assert_called_once_with(event, "Failed", 0, 1, "")

	def test_duplicate_delivery_leaves_completed_events_alone(self):
		with patch.object(delivery, "frappe") as framework, patch.object(delivery, "get_message") as get_message:
			framework.db.get_value.return_value = frappe._dict(status="Sent")
			delivery.dispatch("event")
			get_message.assert_not_called()

	def test_publication_is_queued_only_on_transition(self):
		doc = Mock(published=1, modified="now")
		doc.name = "post"
		with patch.object(delivery, "queue_event") as enqueue:
			doc.get_value_before_save.return_value = 1
			api.trigger_blog_post_push(doc)
			enqueue.assert_not_called()
			doc.get_value_before_save.return_value = None
			api.trigger_blog_post_push(doc)
			enqueue.assert_called_once_with("Blog", "post", "now")

	def test_guest_order_uses_tracking_page(self):
		event = frappe._dict(name="event", reference_name="ORDER-1")
		token = frappe._dict(token_hash="hash", user=None)
		with patch.object(delivery, "frappe") as framework:
			framework.db.get_value.side_effect = [
				frappe._dict(subscription="device", latest_event="event", last_state="0|Draft|"),
				token,
			]
			self.assertEqual(delivery.order_message(event), (
				[token], "Order received", "We received your order. You can track it from our website.",
				"/track-order?id=ORDER-1",
			))

	def test_guest_order_requires_its_checkout_quotation(self):
		doc = SimpleNamespace(name="ORDER-1", items=[frappe._dict(prevdoc_docname="OTHER")])
		with patch.object(order_push, "frappe") as framework, patch.object(order_push, "browser_subscription") as browser:
			framework.session.user = "Guest"
			framework.get_installed_apps.return_value = ["webshop"]
			framework.cache.return_value.get_value.return_value = "CHECKOUT"
			order_push.link_guest_order(doc)
			browser.assert_not_called()

	def test_disabled_configuration_skips_firebase(self):
		with patch.object(sending, "frappe") as framework, patch.object(sending, "firebase_admin") as firebase:
			framework.utils.cint.return_value = 0
			self.assertIsNone(sending.get_fcm_app())
			firebase.get_app.assert_not_called()

	def test_clicks_are_restricted_to_the_site(self):
		with patch.object(sending, "frappe") as framework:
			framework.utils.get_url.return_value = "https://example.test"
			self.assertEqual(sending.click_path("https://example.test/track-order?id=ORDER"), "/track-order?id=ORDER")
			self.assertEqual(sending.click_path("https://other.test/order"), "/app")

	def test_logout_revokes_the_current_browser_subscription(self):
		with (patch.object(subscriptions, "frappe") as framework,
			patch.object(subscriptions, "browser_subscription", return_value=frappe._dict(name="current", user="owner")),
			patch.object(subscriptions, "set_browser_key") as set_key):
			framework.session.user = "owner"
			subscriptions.disconnect_on_logout()
			framework.db.delete.assert_called_once_with("FCM Token", {"name": "current"})
			set_key.assert_called_once_with(subscriptions.DISCONNECTED)

	def test_test_sender_requires_system_manager(self):
		with patch.object(api, "frappe") as framework, patch.object(api, "_", side_effect=lambda value: value):
			framework.session.user = "employee"
			framework.get_roles.return_value = ["Employee"]
			framework.PermissionError = frappe.PermissionError
			framework.throw.side_effect = frappe.PermissionError
			with self.assertRaises(frappe.PermissionError):
				api.require_system_manager()
