"""WhatsApp interactive message payloads and reply parsing."""


def category_list(categories):
    return {
        "type": "list",
        "body": {"text": "Browse our menu and choose a category."},
        "action": {
            "button": "View menu",
            "sections": [{
                "title": "Categories",
                "rows": [
                    {"id": f"category:{category}", "title": category[:24]}
                    for category in categories[:10]
                ],
            }],
        },
    }


def product_list(category, items):
    return {
        "type": "list",
        "body": {"text": f"Choose an item from {category}."},
        "action": {
            "button": "View items",
            "sections": [{
                "title": category[:24],
                "rows": [
                    {
                        "id": f"item:{item['name']}",
                        "title": item["name"][:24],
                        "description": f"N{int(round(item['price'])):,}",
                    }
                    for item in items[:10]
                ],
            }],
        },
    }


def cart_actions():
    return {
        "type": "button",
        "body": {"text": "What would you like to do next?"},
        "action": {"buttons": [
            {"title": "Add more", "payload": "MORE"},
            {"title": "Checkout", "payload": "DONE"},
        ]},
    }


def confirmation_actions():
    return {
        "type": "button",
        "body": {"text": "Confirm your order?"},
        "action": {"buttons": [
            {"title": "Confirm", "payload": "YES"},
            {"title": "Cancel", "payload": "CANCEL"},
        ]},
    }


def fulfilment_actions():
    return {
        "type": "button",
        "body": {"text": "Choose the delivery option to continue."},
        "action": {"buttons": [
            {"title": "Delivery", "payload": "DELIVERY"},
            {"title": "Pick up", "payload": "PICKUP"},
        ]},
    }


def parse_reply(interaction):
    """Return a safe text command from a Zernio interactive webhook item."""
    if not isinstance(interaction, dict):
        return ""
    reply = interaction.get("button_reply") or interaction.get("list_reply") or {}
    return str(reply.get("id") or reply.get("payload") or reply.get("title") or "").strip()
