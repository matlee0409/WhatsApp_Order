"""Database repository preserving the historical Sheets module API."""
from datetime import datetime, timezone
import json

def _load_db():
    global select, func, joinedload, session_scope
    global Customer, MenuCategory, MenuItem, Order, OrderItem, Payment
    from sqlalchemy import select, func
    from sqlalchemy.orm import joinedload
    from db import session_scope
    from models import Customer, MenuCategory, MenuItem, Order, OrderItem, Payment

from logger import get_logger

log = get_logger("sheets")


def _now():
    return datetime.now(timezone.utc)


def _naira(kobo):
    return float(kobo or 0) / 100


def _menu_item(item):
    return {"category": item.category.name, "name": item.name,
            "description": item.description or "", "price": _naira(item.price_kobo),
            "available": bool(item.is_available), "retailer_id": f"menu-item-{item.id}"}


def get_menu():
    _load_db()
    with session_scope() as s:
        rows = s.execute(select(MenuItem).join(MenuCategory).order_by(MenuCategory.sort_order, MenuItem.id)).scalars().all()
        return [_menu_item(i) for i in rows]


def get_available_menu():
    return [i for i in get_menu() if i["available"]]


def get_categories():
    seen = []
    for item in get_available_menu():
        if item["category"] and item["category"] not in seen:
            seen.append(item["category"])
    return seen


def get_items_in_category(category):
    target = (category or "").strip().lower()
    return [i for i in get_available_menu() if i["category"].lower() == target]


def _record(order):
    items = [{"name": i.item_name, "quantity": i.quantity,
              "unit_price": _naira(i.unit_price_kobo),
              "line_total": _naira(i.line_total_kobo)} for i in order.items]
    payment = next((p for p in order.payments if p.status.lower() in ("success", "paid")), None)
    return {"order_ref": order.order_reference, "phone": order.customer.phone,
            "name": order.customer.name or "", "email": order.customer.email or "",
            "items": json.dumps(items), "total": _naira(order.total_kobo),
            "status": order.status.title(), "payment_ref": payment.provider_reference if payment else "",
            "created_at": order.created_at.isoformat() if order.created_at else "",
            "paid_at": order.paid_at.isoformat() if order.paid_at else "",
            "ready_at": order.ready_at.isoformat() if order.ready_at else "",
            "ready_notified": "Yes" if order.ready_notified else "No",
            "fulfilment": order.fulfilment or "", "conversation_id": order.conversation_id or ""}


def _find(s, ref):
    _load_db()
    return s.execute(select(Order).options(joinedload(Order.customer), joinedload(Order.items), joinedload(Order.payments)).where(Order.order_reference == str(ref).strip())).unique().scalar_one_or_none()


def order_ref_exists(order_ref):
    with session_scope() as s: return _find(s, order_ref) is not None


def find_order_by_ref(order_ref):
    with session_scope() as s:
        o = _find(s, order_ref)
        return (o.id, _record(o)) if o else (None, None)


def find_order_by_phone(phone):
    _load_db()
    with session_scope() as s:
        o = s.execute(select(Order).join(Customer).options(joinedload(Order.customer), joinedload(Order.items), joinedload(Order.payments)).where(Customer.phone == str(phone).strip()).order_by(Order.created_at.desc())).unique().scalars().first()
        return _record(o) if o else None


def find_order_by_payment_ref(payment_ref):
    _load_db()
    with session_scope() as s:
        p = s.execute(select(Payment).options(joinedload(Payment.order).joinedload(Order.customer), joinedload(Payment.order).joinedload(Order.items)).where(Payment.provider_reference == str(payment_ref).strip())).unique().scalar_one_or_none()
        return (p.order.id, _record(p.order)) if p else (None, None)


def payment_ref_processed(payment_ref):
    _, rec = find_order_by_payment_ref(payment_ref)
    return bool(rec and rec["status"].lower() in ("paid", "ready", "collected"))


def append_order(order_ref, phone, name, email, cart, total, conversation_id=None, fulfilment=None):
    _load_db()
    with session_scope() as s:
        customer = s.execute(select(Customer).where(Customer.phone == phone)).scalar_one_or_none()
        if customer is None:
            customer = Customer(phone=phone, name=name or None, email=email or None); s.add(customer); s.flush()
        else:
            customer.name = name or customer.name; customer.email = email or customer.email
        order = Order(order_reference=order_ref, customer=customer, total_kobo=int(round(total * 100)), fulfilment=fulfilment, conversation_id=conversation_id)
        for item in cart:
            order.items.append(OrderItem(item_name=item["name"], quantity=int(item["quantity"]), unit_price_kobo=int(round(item["unit_price"] * 100)), line_total_kobo=int(round(item["line_total"] * 100))))
        s.add(order)
    return order_ref


def mark_order_paid(order_ref, payment_ref, amount_kobo=None, metadata=None):
    _load_db()
    with session_scope() as s:
        o = _find(s, order_ref)
        if not o: return False
        if o.status.lower() in ("paid", "ready", "collected"): return o.payment_reference == payment_ref
        existing = s.execute(select(Payment).where(Payment.provider_reference == payment_ref)).scalar_one_or_none()
        if existing and existing.order_id != o.id: return False
        amount = o.total_kobo if amount_kobo is None else int(amount_kobo)
        if amount < o.total_kobo: return False
        o.status = "paid"; o.paid_at = _now(); o.payment_reference = payment_ref
        s.add(Payment(order=o, provider_reference=payment_ref, amount_kobo=amount, status="success", metadata_json=json.dumps(metadata or {})))
        return True


def get_ready_orders():
    _load_db()
    with session_scope() as s:
        rows = s.execute(select(Order).options(joinedload(Order.customer), joinedload(Order.items), joinedload(Order.payments)).where(func.lower(Order.status) == "ready", Order.ready_notified.is_(False))).unique().scalars().all()
        return [(o.id, _record(o)) for o in rows]


def set_ready_notified(order_ref, ready_at=None):
    with session_scope() as s:
        o = _find(s, order_ref)
        if not o: return False
        o.ready_notified = True; o.ready_at = ready_at or _now(); return True


def get_order_status(order_ref):
    _, rec = find_order_by_ref(order_ref)
    return rec["status"] if rec else None


def _now_iso():
    return _now().isoformat()
