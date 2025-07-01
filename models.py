from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# models.py içindeki User sınıfını değiştirin

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True) # Dahili, benzersiz anahtar (değişmez)
    
    # --- YENİ EKLENEN VE GÜNCELLENEN ALANLAR ---
    full_name = db.Column(db.String(120), nullable=False) # Personelin tam adı (örn: "John Smith")
    employee_number = db.Column(db.String(20), unique=True, nullable=False) # Benzersiz personel numarası (örn: "1084")
    
    username = db.Column(db.String(80), unique=True, nullable=False) # Sisteme giriş için kullanıcı adı
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='Waiter')
    phone_number = db.Column(db.String(20), nullable=True)

class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    clock_out = db.Column(db.DateTime, nullable=True)
    user = db.relationship('User', backref=db.backref('shifts', lazy=True))


# models.py içindeki Section sınıfının doğru hali

class Section(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    default_printer_id = db.Column(db.Integer, db.ForeignKey('printer.id'), nullable=True)
    printer = db.relationship('Printer', foreign_keys=[default_printer_id], backref='default_for_sections')

    receipt_printer_id = db.Column(db.Integer, db.ForeignKey('printer.id', name='fk_section_receipt_printer'), nullable=True)
    receipt_printer = db.relationship('Printer', foreign_keys=[receipt_printer_id], backref='receipt_for_sections')

    tables = db.relationship('RestaurantTable', backref='section', lazy=True, cascade="all, delete-orphan")


class RestaurantTable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Available')
    is_special = db.Column(db.Boolean, default=False)
    section_id = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=False)

class Printer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    # --- YENİ EKLENEN ALANLAR ---
    # Printer'ın türünü belirtir
    # 'web': Tarayıcı üzerinden PDF çıktısı
    # 'escpos': Ağdaki termal yazıcı (ESC/POS komutları ile)
    type = db.Column(db.String(20), nullable=False, default='web')
    
    # Ağdaki yazıcının IP adresi veya özel yolu (örn: 192.168.1.100 veya /dev/usb/lp0)
    network_path = db.Column(db.String(100), nullable=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    printer_id = db.Column(db.Integer, db.ForeignKey('printer.id'), nullable=False)
    printer = db.relationship('Printer', backref=db.backref('categories', lazy=True))
    menu_items = db.relationship('MenuItem', backref='category', lazy=True, cascade="all, delete-orphan")

class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300))
    price = db.Column(db.Float, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    allergens = db.Column(db.String(200), nullable=True)
    options = db.Column(db.String(300), nullable=True)
    

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('restaurant_table.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_closed = db.Column(db.Boolean, default=False)
    tax_rate = db.Column(db.Float, default=0.13)
    order_type = db.Column(db.String(50), nullable=False, default='Dine-In')
    customer_name = db.Column(db.String(100), nullable=True)
    customer_phone = db.Column(db.String(20), nullable=True)
    pickup_time = db.Column(db.String(50), nullable=True)
    bill_printed_at = db.Column(db.DateTime, nullable=True)
    table = db.relationship('RestaurantTable', backref=db.backref('orders', lazy=True))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', foreign_keys=[user_id], backref='orders')
    active_user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_order_active_user'), nullable=True)
    active_user = db.relationship('User', foreign_keys=[active_user_id], backref='active_orders')

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
    status = db.Column(db.String(50), nullable=False, default='Pending')
    sent_at = db.Column(db.DateTime, nullable=True)
    is_void = db.Column(db.Boolean, default=False)
    discount_amount = db.Column(db.Float, default=0.0)
    discount_reason = db.Column(db.String(100), nullable=True) # örn: "Manager Comp", "Birthday"
    void_reason = db.Column(db.String(200), nullable=True)
    printed_to_kitchen = db.Column(db.Boolean, default=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=True)
    order = db.relationship('Order', backref=db.backref('order_items', lazy=True, cascade="all, delete-orphan"))
    menu_item = db.relationship('MenuItem')
    seat = db.relationship('Seat', backref=db.backref('order_items', lazy=True))
    payment = db.relationship('Payment', backref=db.backref('paid_items', lazy=True))

class RestaurantInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=True)



class Log(db.Model):
    """
    Sistemdeki önemli olayları kaydetmek için kullanılır (denetim izi).
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    action = db.Column(db.String(255), nullable=False) # örn: "Added 'Red Ravioli' to Order #5"
    
    user = db.relationship('User', backref=db.backref('logs', lazy=True))    