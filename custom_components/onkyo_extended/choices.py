"""Shared choice lists for selectors, configuration and dashboard checkboxes.

Visibility is a presentation preference. We keep the complete entity option
list so scenes/scripts can still select an option hidden on the dashboard.
"""
from .const import SERVICES, INPUT_BY_ID, CONF_VISIBLE_SERVICES
from .receiver_data import LISTENING_MODES

CATEGORIES = {
    "services": ("Show Network Services", CONF_VISIBLE_SERVICES),
    "inputs": ("Show Input Selection", "shown_inputs"),
    "modes": ("Show Listening Modes", "shown_modes"),
}


def catalog(runtime, entry, category):
    if category == "services":
        return {name: name for name in SERVICES}
    if category == "inputs":
        names = entry.options.get("input_names", {})
        return {code: names.get(code, INPUT_BY_ID.get(code, item["name"]))
                for code, item in runtime["capabilities"]["inputs"].items()
                if item["zone"] & 1}
    if category == "modes":
        # Owner-defined labels can refine the verified/model default table.
        modes = entry.options.get("listening_modes") or LISTENING_MODES
        # Protocol aliases sometimes share names. Unique labels ensure that
        # selecting a label always refers to one unambiguous command.
        counts = {name: list(modes.values()).count(name) for name in modes.values()}
        return {code: f"{name} ({code})" if counts[name] > 1 else name
                for code, name in modes.items()}
    raise ValueError("Unknown visibility category")


def shown_keys(runtime, entry, category):
    available = catalog(runtime, entry, category)
    if category == "services":
        return [key for key in available if runtime["visible_services"].get(key, False)]
    key = CATEGORIES[category][1]
    return [item for item in entry.options.get(key, list(available)) if item in available]


def attributes(runtime, entry, category):
    available = catalog(runtime, entry, category)
    shown = shown_keys(runtime, entry, category)
    return {"config_entry_id": entry.entry_id, "visibility_category": category,
            "all_choices": available, "shown_choices": shown,
            "visible_options": [available[key] for key in shown]}


async def set_visibility(hass, entry, category, choices):
    """Save checkbox choices without contacting or reloading the receiver."""
    from .const import DOMAIN, CONF_SHOW_HIDDEN
    runtime = hass.data[DOMAIN][entry.entry_id]
    available = catalog(runtime, entry, category)
    if not isinstance(choices, list) or any(key not in available for key in choices):
        raise ValueError("Visibility choices must belong to this receiver's list")
    if category == "services":
        visible = {key: key in choices for key in available}
        runtime["visible_services"] = visible
        updates = {CONF_VISIBLE_SERVICES: visible, CONF_SHOW_HIDDEN: all(visible.values())}
    else:
        updates = {CATEGORIES[category][1]: list(dict.fromkeys(choices))}
    hass.config_entries.async_update_entry(entry, options={**entry.options, **updates})
    for entity in runtime["select_entities"]:
        entity.async_write_ha_state()
