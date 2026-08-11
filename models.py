"""Relational models for restaurants, ordering, payments, and dashboard users."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class RestaurantSetting(Base):
    __tablename__ = "restaurant_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    __table_args__ = (UniqueConstraint("key", name="uq_restaurant_settings_key"),)


class MenuCategory(Base):
    __tablename__ = "menu_categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    items: Mapped[list["MenuItem"]] = relationship(back_populates="category")
    __table_args__ = (UniqueConstraint("name", name="uq_menu_categories_name"), Index("ix_menu_categories_active_order", "is_active", "sort_order"))


class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("menu_categories.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    category: Mapped[MenuCategory] = relationship(back_populates="items")
    image: Mapped["MenuItemImage | None"] = relationship(back_populates="menu_item", uselist=False, cascade="all, delete-orphan")
    __table_args__ = (Index("ix_menu_items_category_available", "category_id", "is_available"),)


class MenuItemImage(Base):
    __tablename__ = "menu_item_images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    menu_item: Mapped[MenuItem] = relationship(back_populates="image")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_reference: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    total_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conversation_id: Mapped[str | None] = mapped_column(String(160))
    fulfilment: Mapped[str | None] = mapped_column(String(32))
    payment_reference: Mapped[str | None] = mapped_column(String(160), unique=True)
    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="order")
    __table_args__ = (Index("ix_orders_customer_created", "customer_id", "created_at"), Index("ix_orders_status_created", "status", "created_at"))


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    menu_item_id: Mapped[int | None] = mapped_column(ForeignKey("menu_items.id", ondelete="SET NULL"))
    item_name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    order: Mapped[Order] = relationship(back_populates="items")
    __table_args__ = (Index("ix_order_items_order", "order_id"),)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="paystack")
    provider_reference: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    amount_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    order: Mapped[Order] = relationship(back_populates="payments")
    __table_args__ = (Index("ix_payments_order_status", "order_id", "status"),)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(254), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("ix_notification_deliveries_status", "status", "created_at"),)


class DashboardUser(Base):
    __tablename__ = "dashboard_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
