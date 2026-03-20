frappe.ui.form.on('FCM Config', {
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
