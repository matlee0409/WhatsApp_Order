"""Deterministic order parsing against the available menu."""

import re

_MAX_QTY_PER_ITEM = 50
_MAX_MESSAGE_CHARS = 500
_LOW = {"items": [], "total": 0, "confidence": "low", "unrecognized": []}


def _normalise(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def parse_order(message: str, available_menu):
    """Match menu item names and nearby quantities without external services."""
    if not available_menu:
        return _LOW

    text = (message or "")[:_MAX_MESSAGE_CHARS]
    normalised_text = _normalise(text)
    matches = []

    for menu_item in available_menu:
        item_name = menu_item["name"]
        normalised_name = _normalise(item_name)
        if not normalised_name:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(normalised_name)}(?![a-z0-9])"
        for match in re.finditer(pattern, normalised_text):
            matches.append((match.start(), match.end(), menu_item))

    if not matches:
        return _LOW

    matches.sort(key=lambda match: (match[0], -(match[1] - match[0])))
    selected = []
    occupied_until = -1
    for start, end, menu_item in matches:
        if start < occupied_until:
            continue
        selected.append((start, menu_item))
        occupied_until = end

    items = []
    total = 0.0
    for start, menu_item in selected:
        prefix = normalised_text[max(0, start - 12):start]
        quantities = re.findall(r"(?:^|\s)(\d{1,3})(?:\s*x)?\s*$", prefix)
        quantity = int(quantities[-1]) if quantities else 1
        if quantity < 1 or quantity > _MAX_QTY_PER_ITEM:
            return _LOW
        price = float(menu_item["price"])
        line_total = price * quantity
        items.append({
            "name": menu_item["name"],
            "quantity": quantity,
            "unit_price": price,
            "line_total": line_total,
        })
        total += line_total

    return {
        "items": items,
        "total": total,
        "confidence": "high",
        "unrecognized": [],
    }
