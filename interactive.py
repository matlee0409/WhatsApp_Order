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


def catalog_product_list(catalog_id, categories):
    return {
        "type": "product_list",
        "header": {"type": "text", "text": "Our menu"},
        "body": {"text": "Tap View items to browse our products."},
        "action": {
            "catalog_id": catalog_id,
            "sections": [
                {
                    "title": category[:24],
                    "product_items": [
                        {"product_retailer_id": item["retailer_id"]}
                        for item in items[:30]
                    ],
                }
                for category, items in categories
                if items
            ],
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
            {"type": "reply", "reply": {"id": "MORE", "title": "Add more"}},
            {"type": "reply", "reply": {"id": "DONE", "title": "Checkout"}},
        ]},
    }


def confirmation_actions():
    return {
        "type": "button",
        "body": {"text": "Confirm your order?"},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": "YES", "title": "Confirm"}},
            {"type": "reply", "reply": {"id": "CANCEL", "title": "Cancel"}},
        ]},
    }


def fulfilment_actions():
    return {
        "type": "button",
        "body": {"text": "Choose the delivery option to continue."},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": "DELIVERY", "title": "Delivery"}},
            {"type": "reply", "reply": {"id": "PICKUP", "title": "Pick up"}},
        ]},
    }


def parse_reply(interaction):
    """Return a safe command from a Zernio interactive webhook payload."""
    if not isinstance(interaction, dict):
        return ""

    metadata = interaction.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    reply = (
        interaction.get("button_reply")
        or interaction.get("buttonReply")
        or interaction.get("list_reply")
        or interaction.get("listReply")
        or {}
    )
    if not isinstance(reply, dict):
        reply = {}

    return str(
        metadata.get("interactiveId")
        or interaction.get("interactiveId")
        or reply.get("id")
        or reply.get("payload")
        or reply.get("title")
        or ""
    ).strip()
