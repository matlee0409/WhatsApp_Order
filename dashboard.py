"""Static prototype data for the management dashboard."""

ORDERS = [
    {"id": "WA-1048", "customer": "Maya Chen", "phone": "+1 202 555 0142", "items": "Truffle mushroom pizza × 1", "total": 28.50, "status": "new", "time": "10:42", "eta": 18, "payment": "Paid"},
    {"id": "WA-1047", "customer": "Noah Williams", "phone": "+1 202 555 0188", "items": "Smash burger × 2 · Fries × 1", "total": 37.00, "status": "new", "time": "10:36", "eta": 22, "payment": "Pay on pickup"},
    {"id": "WA-1046", "customer": "Ava Patel", "phone": "+1 202 555 0164", "items": "Chicken shawarma × 2", "total": 24.00, "status": "preparing", "time": "10:28", "eta": 9, "payment": "Paid"},
    {"id": "WA-1045", "customer": "Liam Jones", "phone": "+1 202 555 0109", "items": "Margherita pizza × 1 · Cola × 2", "total": 23.50, "status": "preparing", "time": "10:14", "eta": 5, "payment": "Paid"},
    {"id": "WA-1044", "customer": "Sophia Garcia", "phone": "+1 202 555 0171", "items": "Paneer curry × 1 · Naan × 2", "total": 26.00, "status": "ready", "time": "09:58", "eta": 0, "payment": "Paid"},
    {"id": "WA-1043", "customer": "Ethan Brown", "phone": "+1 202 555 0133", "items": "Chicken burger × 1", "total": 14.00, "status": "completed", "time": "09:41", "eta": 0, "payment": "Paid"},
]

PRODUCTS = [
    {"id": 1, "name": "Truffle Mushroom Pizza", "category": "Pizza", "price": 28.50, "stock": 18, "active": True, "initials": "TM", "tone": "sage"},
    {"id": 2, "name": "Chicken Shawarma", "category": "Wraps", "price": 12.00, "stock": 24, "active": True, "initials": "CS", "tone": "amber"},
    {"id": 3, "name": "Classic Smash Burger", "category": "Burgers", "price": 15.00, "stock": 11, "active": True, "initials": "SB", "tone": "coral"},
    {"id": 4, "name": "Paneer Curry", "category": "Mains", "price": 18.00, "stock": 8, "active": True, "initials": "PC", "tone": "violet"},
    {"id": 5, "name": "Garlic Naan", "category": "Sides", "price": 4.00, "stock": 32, "active": True, "initials": "GN", "tone": "blue"},
    {"id": 6, "name": "Blood Orange Soda", "category": "Drinks", "price": 5.50, "stock": 4, "active": False, "initials": "BO", "tone": "rose"},
]

TRANSACTIONS = [
    {"id": "TX-90831", "customer": "Maya Chen", "order": "WA-1048", "amount": 28.50, "method": "Card", "status": "Successful", "date": "Aug 9, 10:42"},
    {"id": "TX-90830", "customer": "Ava Patel", "order": "WA-1046", "amount": 24.00, "method": "WhatsApp Pay", "status": "Successful", "date": "Aug 9, 10:28"},
    {"id": "TX-90829", "customer": "Liam Jones", "order": "WA-1045", "amount": 23.50, "method": "Card", "status": "Successful", "date": "Aug 9, 10:14"},
    {"id": "TX-90828", "customer": "Olivia Smith", "order": "WA-1042", "amount": 19.00, "method": "Card", "status": "Refunded", "date": "Aug 9, 09:32"},
    {"id": "TX-90827", "customer": "Lucas Martin", "order": "WA-1041", "amount": 42.00, "method": "Bank transfer", "status": "Pending", "date": "Aug 9, 09:18"},
]

CATEGORIES = [
    {"name": "Pizza", "products": 8, "sales": 184, "active": True},
    {"name": "Burgers", "products": 6, "sales": 132, "active": True},
    {"name": "Wraps", "products": 5, "sales": 97, "active": True},
    {"name": "Mains", "products": 9, "sales": 86, "active": True},
    {"name": "Drinks", "products": 12, "sales": 211, "active": True},
]

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


def dashboard_context(page):
    return {
        "page": page,
        "page_title": PAGE_TITLES[page][0],
        "page_description": PAGE_TITLES[page][1],
        "orders": ORDERS,
        "products": PRODUCTS,
        "transactions": TRANSACTIONS,
        "categories": CATEGORIES,
        "nav_items": NAV_ITEMS,
    }
