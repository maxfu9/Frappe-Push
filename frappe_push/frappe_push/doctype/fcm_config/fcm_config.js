frappe.ui.form.on('FCM Config', {
	refresh(frm) {
		frm.add_custom_button(__("Delivery health"), async () => {
			const r = await frappe.call("frappe_push.frappe_push.doctype.fcm_config.fcm_config.get_delivery_health");
			const stats = r.message;
			frappe.msgprint({
				title: __("Push delivery health"),
				indicator: stats.stalled || stats.credential_errors_today ? "orange" : "blue",
				message: [
					__("Queued: {0}", [Number(stats.queued)]),
					__("Waiting to retry: {0}", [Number(stats.retrying)]),
					__("Stalled: {0}", [Number(stats.stalled)]),
					__("Unknown outcomes in the past 24 hours: {0}", [Number(stats.unknown_today)]),
					__("Configuration or credential errors in the past 24 hours: {0}", [Number(stats.credential_errors_today)]),
				].join("<br>"),
			});
		});
		frm.add_custom_button(__("FCM Delivery"), () => frappe.set_route("List", "FCM Delivery"));
	},
	send_test_notification: function(frm) {
		frappe.call({
			method: "frappe_push.frappe_push.doctype.fcm_config.fcm_config.send_test_notification",
			callback: function(r) {
				if (r.message && r.message.success) {
					frappe.msgprint(r.message.message);
				} else if (r.message) {
					frappe.msgprint({
						title: __('Error'),
						indicator: 'red',
						message: r.message.message
					});
				}
			}
		});
	}
});
