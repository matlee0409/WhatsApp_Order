"""Static prototype data for the management dashboard."""

import config


ORDERS = []
PRODUCTS = []
TRANSACTIONS = []
CATEGORIES = []

NAV_ITEMS = [
    ("Operations", [("orders", "Orders", "inbox"), ("analytics", "Analytics", "chart")]),
    ("Organize", [("products", "Products", "box"), ("catalog", "Catalog", "grid"), ("payments", "Payments", "card")]),
    ("Engage", [("templates", "Templates", "message"), ("support", "Support", "help")]),
]

PAGE_TITLES = {
    "orders": ("Order command center", "Keep every WhatsApp order moving, from first message to pickup."),
    "analytics": ("Business pulse", "Revenue, demand and customer activity at a glance."),
    "products": ("Products", "Manage availability, pricing and inventory across your menu."),
    "catalog": ("Catalog", "Structure your WhatsApp menu and keep every category in sync."),
    "payments": ("Payments", "Track every transaction and resolve exceptions quickly."),
    "settings": ("Bot configuration", "Control how your assistant receives and handles orders."),
    "templates": ("Message templates", "Create clear, consistent replies for every order moment."),
    "support": ("Support center", "Find answers and keep your ordering channel healthy."),
}


def dashboard_context(page, zernio_connection=None):
    return {
        "page": page,
        "page_title": PAGE_TITLES[page][0],
        "page_description": PAGE_TITLES[page][1],
        "orders": ORDERS,
        "products": PRODUCTS,
        "transactions": TRANSACTIONS,
        "categories": CATEGORIES,
        "nav_items": NAV_ITEMS,
        "zernio_connection": zernio_connection,
        "business_name": config.BUSINESS_NAME,
    }
