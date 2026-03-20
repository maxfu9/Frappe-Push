frappe.ui.form.on('FCM Broadcast', {
	refresh: function(frm) {
		if (frm.doc.status === 'Draft' && !frm.is_new()) {
			frm.add_custom_button(__('Send Broadcast'), function() {
				frappe.confirm(
					__('Are you sure you want to send this push notification to {0} subscribers?', [frm.doc.target]),
					function() {
						frm.call('send_broadcast').then(() => {
							frm.reload_doc();
						});
					}
				);
			}).addClass('btn-primary');
		}
	}
});
