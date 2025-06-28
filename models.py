from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='Waiter')

class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    clock_out = db.Column(db.DateTime, nullable=True)
    user = db.relationship('User', backref=db.backref('shifts', lazy=True))

class RestaurantTable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Available')
    is_special = db.Column(db.Boolean, default=False)
    section_id = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=False)

class Printer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    printer_id = db.Column(db.Integer, db.ForeignKey('printer.id'), nullable=False)
    printer = db.relationship('Printer', backref=db.backref('categories', lazy=True))

class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300))
    price = db.Column(db.Float, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    allergens = db.Column(db.String(200), nullable=True)
    options = db.Column(db.String(300), nullable=True)
    category = db.relationship('Category', backref=db.backref('menu_items', lazy=True))

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('restaurant_table.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_closed = db.Column(db.Boolean, default=False)
    tax_rate = db.Column(db.Float, default=0.13)
    order_type = db.Column(db.String(50), nullable=False, default='Dine-In')
    customer_name = db.Column(db.String(100), nullable=True)
    customer_phone = db.Column(db.String(20), nullable=True)
    pickup_time = db.Column(db.String(50), nullable=True) # "ASAP", "18:30", "Tomorrow 12:00" gibi esnek bir metin alanı
    table = db.relationship('RestaurantTable', backref=db.backref('orders', lazy=True))
    user = db.relationship('User', backref=db.backref('orders', lazy=True))

class Seat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    seat_number = db.Column(db.Integer, nullable=False)
    order = db.relationship('Order', backref=db.backref('seats', lazy=True, cascade="all, delete-orphan"))

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    tax_amount = db.Column(db.Float, nullable=False)
    tip_amount = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    order = db.relationship('Order', backref=db.backref('payments', lazy=True))

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_item.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.String(200))
    price_at_time_of_order = db.Column(db.Float, nullable=False)
    seat_id = db.Column(db.Integer, db.ForeignKey('seat.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='Holding')
    is_void = db.Column(db.Boolean, default=False)
    void_reason = db.Column(db.String(200), nullable=True)
    printed_to_kitchen = db.Column(db.Boolean, default=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=True)
    order = db.relationship('Order', backref=db.backref('order_items', lazy=True, cascade="all, delete-orphan"))
    menu_item = db.relationship('MenuItem')
    seat = db.relationship('Seat', backref=db.backref('order_items', lazy=True))
    payment = db.relationship('Payment', backref=db.backref('paid_items', lazy=True))

    # --- YENİ Section MODELİ ---
class Section(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # Bir bölümün birden fazla masası olabilir
    tables = db.relationship('RestaurantTable', backref='section', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Section {self.name}>'
