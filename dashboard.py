"""Static prototype data for the management dashboard."""

import config
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from db import session_scope
from models import MenuCategory, MenuItem, Order, Payment


def _order_status(status):
    return {
        "pending": "new",
        "new": "new",
        "paid": "preparing",
        "preparing": "preparing",
        "ready": "ready",
        "collected": "completed",
        "completed": "completed",
    }.get((status or "").lower(), "new")


def _order_record(order):
    items = " · ".join(f"{item.item_name} × {item.quantity}" for item in order.items)
    return {
        "id": order.order_reference,
        "customer": order.customer.name or order.customer.phone,
        "phone": order.customer.phone,
        "items": items,
        "total": (order.total_kobo or 0) / 100,
        "status": _order_status(order.status),
        "time": order.created_at.strftime("%H:%M") if order.created_at else "",
        "eta": 0,
        "payment": "Paid" if order.payment_reference else "Pending",
    }


def _dashboard_data():
    with session_scope() as session:
        orders = session.execute(
            select(Order)
            .options(joinedload(Order.customer), joinedload(Order.items))
            .order_by(Order.created_at.desc())
        ).unique().scalars().all()
        items = session.execute(
            select(MenuItem).options(joinedload(MenuItem.category)).order_by(MenuItem.id)
        ).scalars().all()
        categories = session.execute(
            select(MenuCategory).options(joinedload(MenuCategory.items)).order_by(MenuCategory.sort_order, MenuCategory.id)
        ).unique().scalars().all()
        payments = session.execute(
            select(Payment)
            .options(joinedload(Payment.order).joinedload(Order.customer))
            .order_by(Payment.created_at.desc())
        ).scalars().all()

    products = [
        {
            "id": item.id,
            "name": item.name,
            "category": item.category.name,
            "price": (item.price_kobo or 0) / 100,
            "stock": 0,
            "active": bool(item.is_available),
            "initials": "".join(part[0] for part in item.name.split()[:2]).upper(),
            "tone": "sage",
        }
        for item in items
    ]
    category_rows = [
        {
            "name": category.name,
            "products": len(category.items),
            "sales": 0,
            "active": bool(category.is_active),
        }
        for category in categories
    ]
    transactions = [
        {
            "id": payment.provider_reference,
            "customer": payment.order.customer.name or payment.order.customer.phone,
            "order": payment.order.order_reference,
            "amount": (payment.amount_kobo or 0) / 100,
            "method": payment.provider.title(),
            "status": payment.status.title(),
            "date": payment.created_at.strftime("%b %-d, %H:%M") if payment.created_at else "",
        }
        for payment in payments
    ]
    return [_order_record(order) for order in orders], products, transactions, category_rows

NAV_ITEMS = [
    ("Operations", [("orders", "Orders", "inbox"), ("analytics", "Analytics", "chart")]),
    ("Organize", [("products", "Products", "box"), ("catalog", "Catalog", "grid"), ("payments", "Payments", "card")]),
    ("Engage", [("support", "Support", "help")]),
]

PAGE_TITLES = {
    "orders": ("Order command center", "Keep every WhatsApp order moving, from first message to pickup."),
    "analytics": ("Business pulse", "Revenue, demand and customer activity at a glance."),
    "products": ("Products", "Manage availability, pricing and inventory across your menu."),
    "catalog": ("Catalog", "Structure your WhatsApp menu and keep every category in sync."),
    "payments": ("Payments", "Track every transaction and resolve exceptions quickly."),
    "settings": ("System Configuration", "Control how your assistant receives and handles orders."),
    "templates": ("Message templates", "Create clear, consistent replies for every order moment."),
    "support": ("Support center", "Find answers and keep your ordering channel healthy."),
}


def dashboard_context(page, zernio_connection=None):
    orders, products, transactions, categories = _dashboard_data()
    return {
        "page": page,
        "page_title": PAGE_TITLES[page][0],
        "page_description": PAGE_TITLES[page][1],
        "orders": orders,
        "products": products,
        "transactions": transactions,
        "categories": categories,
        "nav_items": NAV_ITEMS,
        "zernio_connection": zernio_connection,
        "business_name": config.BUSINESS_NAME,
    }
