"""Initialize prompt controls without overwriting existing administrator choices."""
import frappe


def execute():
    defaults = {
        "prompt_enabled": 1,
        "prompt_on_website": 1,
        "prompt_on_desk": 1,
        "prompt_position": "Bottom Left",
        "prompt_delay": 10,
    }
    existing = frappe.db.get_singles_dict("FCM Config")
    for field, value in defaults.items():
        if field not in existing:
            frappe.db.set_single_value("FCM Config", field, value)
