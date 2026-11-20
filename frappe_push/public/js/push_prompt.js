/* A single invitation per site/browser; subscription state remains browser-owned. */
frappe.provide("frappe_push");

frappe_push.prompt = {
	storage_key: "frappe_push_prompt_seen_v1",
	started_at: Date.now(),

	setup(config, enable, disconnect) {
		if (this.config) return;
		this.config = config.prompt || {};
		this.enable = enable;
		this.disconnect = disconnect;
		this.connected = Boolean(config.connected);
		this.is_desk = /^\/(app|desk)(\/|$)/.test(location.pathname);
		this.install_controls();
		this.storage_handler = (event) => {
			if (event.key === this.storage_key && event.newValue && !this.manual) this.close();
		};
		window.addEventListener("storage", this.storage_handler);
		const settings = this.config;
		if (config.disconnected || settings.enabled === false || (this.is_desk ? settings.desk === false : settings.website === false)) return;
		const seconds = Number(settings.delay);
		const delay = Number.isFinite(seconds) ? Math.max(0, Math.min(300, seconds)) : 10;
		this.timer = setTimeout(() => this.try_auto(), Math.max(0, delay * 1000 - (Date.now() - this.started_at)));
	},

	seen() {
		try { return !!localStorage.getItem(this.storage_key); }
		catch (_) { return true; } // With no durable storage, keep the manual control only.
	},

	remember() {
		try { localStorage.setItem(this.storage_key, String(Date.now())); return true; }
		catch (_) { return false; }
	},

	busy() {
		const active = document.activeElement;
		if (document.hidden || active?.matches("input, textarea, select, [contenteditable]:not([contenteditable='false'])")) return true;
		return [...document.querySelectorAll('.modal.show, .modal.in, dialog[open], [aria-modal="true"], .ws-drawer.is-open, .sf-header-search-panel:not([hidden]), .sf-navigation.is-open, [role="menu"]')]
			.some((element) => element.getClientRects().length > 0);
	},

	try_auto() {
		if (Notification.permission !== "default" || this.seen()) return;
		// Avoid checkout, sign-in and payment workflows altogether.
		if (/^\/(checkout|cart|login|payment|payments)(\/|$)/.test(location.pathname) || this.busy()) {
			this.timer = setTimeout(() => this.try_auto(), 2000);
			return;
		}
		const show_once = () => {
			if (Notification.permission !== "default" || this.seen() || this.busy()) return;
			if (this.remember()) this.show(false);
		};
		// Serialize simultaneous first visits in tabs where Web Locks is available.
		if (navigator.locks?.request) navigator.locks.request(this.storage_key, show_once).catch(() => {});
		else show_once();
	},

	install_controls() {
		// Frappe v16 renders user menus on demand through the Dropdown API.
		// Extend only menus containing both Settings and Logout; leave core files intact.
		const dropdown = frappe.ui?.Dropdown?.prototype;
		if (this.is_desk && dropdown && !dropdown.frappe_push_extended) {
			const open = dropdown.open;
			dropdown.open = function (...args) {
				const items = Array.isArray(this.options) ? this.options.flatMap(group => group.options || [group]) : [];
				if (items.some(item => item.name === "settings") && items.some(item => item.name === "logout") && !items.some(item => item.name === "frappe-push-settings")) {
					this.set_options([{group: "", options: [{name: "frappe-push-settings", label: __("Push notifications"), icon: "bell", onclick: () => setTimeout(() => frappe_push.prompt.show(true), 0)}]}, ...this.options]);
				}
				return open.apply(this, args);
			};
			dropdown.frappe_push_extended = true;
			return;
		}
		const add = () => {
			if (document.getElementById("frappe-push-settings")) return true;
			const host = this.is_desk
				? document.querySelector('.dropdown-navbar-user .dropdown-menu, .navbar .dropdown-user .dropdown-menu')
				: (document.querySelector('.sf-footer nav[aria-label="Customer care"]')
					|| document.querySelector('.sf-footer .sf-footer-column')
					|| document.querySelector('footer:not(.ws-drawer-footer) .footer-links')
					|| document.querySelector('footer:not(.ws-drawer-footer)'));
			if (!host) return false;
			const button = document.createElement("button");
			button.id = "frappe-push-settings";
			button.type = "button";
			button.className = this.is_desk ? "dropdown-item" : "frappe-push-settings-link";
			button.textContent = __("Push notifications");
			button.onclick = () => this.show(true);
			host.append(button);
			return true;
		};
		if (!add()) {
			const observer = new MutationObserver(() => { if (add()) observer.disconnect(); });
			observer.observe(document.body, {childList: true, subtree: true});
			setTimeout(() => observer.disconnect(), 30000);
		}
	},

	show(manual = false) {
		if (document.getElementById("frappe-push-banner")) return;
		clearTimeout(this.timer);
		this.manual = manual;
		if (manual) this.remember();
		const permission = Notification.permission;
		const card = document.createElement("section");
		card.id = "frappe-push-banner";
		card.className = "frappe-push-prompt";
		card.dataset.position = this.config.position === "Bottom Right" ? "right" : "left";
		card.setAttribute("aria-labelledby", "frappe-push-title");
		// A region, not a modal: no overlay, scroll lock or focus trap.
		card.innerHTML = `<div class="frappe-push-heading"><span class="frappe-push-symbol" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg></span><h2 id="frappe-push-title"></h2><button type="button" class="frappe-push-close">×</button></div><p class="frappe-push-copy"></p><p class="frappe-push-feedback" role="status" aria-live="polite" hidden></p><div class="frappe-push-actions"><button type="button" class="frappe-push-enable"></button><button type="button" class="frappe-push-disconnect" hidden></button><button type="button" class="frappe-push-dismiss"></button></div>`;
		const title = card.querySelector("h2");
		const copy = card.querySelector(".frappe-push-copy");
		const action = card.querySelector(".frappe-push-enable");
		const disconnect = card.querySelector(".frappe-push-disconnect");
		const dismiss = card.querySelector(".frappe-push-dismiss");
		const close = card.querySelector(".frappe-push-close");
		close.setAttribute("aria-label", __("Dismiss notification prompt"));
		title.textContent = __("Stay in the loop");
		copy.textContent = this.is_desk
			? __("Get alerts for assignments, mentions and activity. You can enable them anytime from your user menu.")
			: __("Get order updates and news from EUROPLAST. You can enable notifications anytime from the footer.");
		action.textContent = __("Enable notifications");
		dismiss.textContent = __("Dismiss");
		disconnect.textContent = __("Disconnect this device");
		disconnect.hidden = !this.connected || !this.disconnect;
		if (permission === "denied") {
			title.textContent = __("Notifications are blocked");
			copy.textContent = __("To enable notifications, allow them in your browser’s site settings, then reload this page.");
			action.hidden = true;
		} else if (permission === "granted") {
			title.textContent = __("Push notifications");
			copy.textContent = __("Your browser allows notifications. Connect or disconnect this device below.");
			action.textContent = __("Reconnect this device");
		}
		close.onclick = dismiss.onclick = () => this.close();
		const status = card.querySelector(".frappe-push-feedback");
		disconnect.onclick = async () => {
			action.disabled = disconnect.disabled = true;
			status.hidden = false;
			status.textContent = __("Disconnecting notifications…");
			try {
				await this.disconnect();
				this.connected = false;
				status.textContent = __("Notifications were disconnected on this device.");
				disconnect.hidden = true;
				action.hidden = Notification.permission === "denied";
			} catch (_) {
				status.textContent = __("We couldn’t disconnect notifications. Please try again.");
			} finally { action.disabled = disconnect.disabled = false; }
		};
		action.onclick = async () => {
			action.disabled = disconnect.disabled = true;
			status.hidden = false;
			status.textContent = __("Connecting notifications…");
			try {
				const result = await this.enable();
				if (result === "granted") {
					status.textContent = __("Notifications enabled on this device.");
					disconnect.hidden = !this.disconnect;
					action.hidden = true;
					dismiss.textContent = __("Done");
				} else {
					status.textContent = result === "denied"
						? __("Notifications are blocked. You can change this in your browser’s site settings.")
						: __("No changes made. You can enable notifications later.");
					if (result === "denied") action.hidden = true;
				}
			} catch (_) {
				status.textContent = __("We couldn’t connect notifications. Please try again later.");
			} finally { action.disabled = disconnect.disabled = false; }
		};
		card.addEventListener("keydown", (event) => { if (event.key === "Escape") { event.stopPropagation(); this.close(); } });
		document.body.append(card);
		if (manual) { this.previous_focus = document.activeElement; close.focus(); }
	},

	close() {
		const card = document.getElementById("frappe-push-banner");
		const restore = card?.contains(document.activeElement);
		card?.remove();
		if (restore && this.previous_focus?.isConnected) this.previous_focus.focus();
		this.previous_focus = null;
	}
};
