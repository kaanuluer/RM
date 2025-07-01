from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, User, Shift, Section, RestaurantTable, Printer, Category, MenuItem, Order, OrderItem, Seat, Payment, RestaurantInfo, Log
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, date, timedelta
from functools import wraps
from sqlalchemy import func
from flask_migrate import Migrate 
from datetime import datetime
import pytz # <-- YENİ IMPORT
from escpos.printer import Network # <-- YENİ IMPORT
#import multiprocessing # <-- YENİ IMPORT
#from printer_server import start_printer_server # <-- YENİ IMPORT
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO # <-- YENİ IMPORT
from flask import jsonify
from PIL import Image

# --- APP CONFIGURATION ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_very_secret_key_that_you_should_change'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
socketio = SocketIO(app, async_mode='eventlet')
migrate = Migrate(app, db)

# --- LOGIN MANAGER SETUP ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'clock_in'

# --- JINJA CUSTOM FILTER FOR TIMEZONES ---
# app.py içindeki bu fonksiyonu değiştirin

@app.template_filter('localtz')
def local_time_filter(utc_dt):
    """Jinja2 filter to convert a UTC datetime to local time, correctly handling DST."""
    if not isinstance(utc_dt, datetime):
        return "" # Eğer gelen veri datetime değilse, boş döndür
    
    # Restoranınızın bulunduğu zaman dilimini buradan ayarlayın
    local_zone_name = "America/Halifax"
    
    try:
        # Zaman damgasını UTC olarak ayarla
        utc_dt = utc_dt.replace(tzinfo=pytz.utc)
        
        # Hedef zaman dilimini al
        local_tz = pytz.timezone(local_zone_name)
        
        # UTC zamanını hedef zaman dilimine dönüştür (Bu adım DST'yi otomatik olarak uygular)
        local_dt = utc_dt.astimezone(local_tz)
        
        # İstenen formatta döndür (%I: 12-saatlik, %p: AM/PM)
        return local_dt.strftime('%I:%M %p') # Saniyeyi kaldırdım, daha temiz bir görünüm için
    
    except Exception as e:
        print(f"Error in localtz filter: {e}")
        return "" # Hata durumunda boş döndür


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- DECORATORS ---
# Yüksek Yetki Grubu
HIGH_PRIVILEGE_ROLES = ['Manager', 'Chef', 'Sous Chef']
# Servis Grubu
SERVICE_ROLES = ['Waiter', 'Bartender', 'Host'] + HIGH_PRIVILEGE_ROLES
# Tüm roller (sisteme giriş yapabilen herkes)
ALL_ROLES = ['Line Cook', 'Prep', 'Server Support', 'Dish Pit'] + SERVICE_ROLES

def role_required(allowed_roles):
    """
    Kullanıcının belirtilen rollerden birine sahip olup olmadığını kontrol eden genel bir decorator.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in allowed_roles:
                flash('You do not have permission to access this page.', 'danger')
                # Yetkisi olmayan kullanıcıyı ana paneline yönlendir
                return redirect(url_for('landing_page'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Artık belirli roller için özel decorator'lar oluşturabiliriz:
manager_level_required = role_required(HIGH_PRIVILEGE_ROLES)
service_level_required = role_required(SERVICE_ROLES)

@app.route('/')
@login_required
def landing_page():
    """Kullanıcıyı rolüne göre doğru sayfaya yönlendirir."""
    if current_user.role in HIGH_PRIVILEGE_ROLES or current_user.role in ['Waiter', 'Bartender']:
        return redirect(url_for('floor_plan'))
    else:
        # Diğer tüm roller (Line Cook, Prep vs.) için basit bir karşılama sayfası
        return render_template('clocked_in.html')

# --- HELPER FUNCTIONS ---
# Mevcut create_initial_data fonksiyonunuzu silin ve bunu yapıştırın.
def create_initial_data():
    with app.app_context():
        if db.session.query(User).first() is None:
            print("--- Database is empty. Creating initial data... ---")
            
            # 1. KULLANICILARI VE RESTORAN BİLGİLERİNİ OLUŞTUR
            users = [
                User(full_name="Kaan Uluer", employee_number="1084", username="manager", password="password", role="Manager"),
                User(full_name="John Doe", employee_number="1085", username="waiter", password="password", role="Waiter")
            ]
            db.session.add_all(users)

            info_items = [
                RestaurantInfo(key='restaurant_name', value='The Bicycle Thief'),
                RestaurantInfo(key='address_line_1', value='1475 Lower Water Street'),
                RestaurantInfo(key='address_line_2', value='Halifax N.S. B3J 3Z2'),
                RestaurantInfo(key='phone_number', value='902-425-7993'),
                RestaurantInfo(key='hst_number', value='# 894360213RT0001')
            ]
            db.session.bulk_save_objects(info_items)

            # 2. YAZICILARI OLUŞTUR VE KAYDET (ID'leri almak için)
            kitchen_printer = Printer(name='Kitchen Printer', type='web')
            bar_printer = Printer(name='Bar Printer', type='web')
            receipt_printer = Printer(name='Receipt Printer', type='web')
            db.session.add_all([kitchen_printer, bar_printer, receipt_printer])
            db.session.commit()

            # 3. KATEGORİLERİ OLUŞTUR VE KAYDET (ID'leri almak için)
            appetizers_cat = Category(name='1st Gear (Appetizers)', printer_id=kitchen_printer.id)
            main_courses_cat = Category(name='2nd & High Gear (Mains)', printer_id=kitchen_printer.id)
            drinks_cat = Category(name='Drinks', printer_id=bar_printer.id)
            db.session.add_all([appetizers_cat, main_courses_cat, drinks_cat])
            db.session.commit()

            # 4. BÖLÜMLERİ OLUŞTUR VE KAYDET (ID'leri almak için)
            main_dining_section = Section(name="Main Dining Room", default_printer_id=kitchen_printer.id, receipt_printer_id=receipt_printer.id)
            special_section = Section(name="Special", default_printer_id=kitchen_printer.id, receipt_printer_id=receipt_printer.id)
            park_section = Section(name="Parked Tables", default_printer_id=kitchen_printer.id, receipt_printer_id=receipt_printer.id)
            db.session.add_all([main_dining_section, special_section, park_section])
            db.session.commit()

            # 5. MENÜ VE MASALARI OLUŞTUR (artık tüm ID'ler mevcut)
            menu_items = [
                MenuItem(name='Local Oysters', price=3.50, category_id=appetizers_cat.id),
                MenuItem(name='Flash fried Calamari', price=16.00, category_id=appetizers_cat.id),
                MenuItem(name='Red Ravioli', price=26.00, category_id=main_courses_cat.id)
            ]
            db.session.bulk_save_objects(menu_items)
            
            for i in range(1, 11): 
                db.session.add(RestaurantTable(name=f'T{i}', section_id=main_dining_section.id))
            
            for i in range(1, 26):
                db.session.add(RestaurantTable(name=f'P{i}', section_id=park_section.id))

            db.session.add(RestaurantTable(name="Take-Out Orders", is_special=True, section_id=special_section.id))
            
            # 6. TÜM DEĞİŞİKLİKLERİ SON KEZ KAYDET
            db.session.commit()
            print("--- Initial data creation complete. ---")

def update_table_on_all_screens(table_id):
    """Belirli bir masanın güncel HTML'ini render eder ve tüm istemcilere yayınlar."""
    with app.app_context(): # Socket.IO olayları için uygulama bağlamı gerekli olabilir
        table = db.session.get(RestaurantTable, table_id)
        if table:
            html = render_template('_table_card.html', table=table)
            socketio.emit('update_table_card', {'table_id': table_id, 'html': html})


def get_order_totals(order_id):
    order = db.session.get(Order, order_id)
    if not order: return None
    unpaid_items = [item for item in order.order_items if not item.payment_id and not item.is_void]
    subtotal_due = sum(item.price_at_time_of_order * item.quantity for item in unpaid_items)
    total_due = subtotal_due * (1 + order.tax_rate)
    total_paid = sum(p.subtotal + p.tax_amount for p in order.payments)
    remaining_balance = total_due - total_paid
    return {
        "order": order,
        "unpaid_items": unpaid_items,
        "total_due": total_due,
        "total_paid": total_paid,
        "remaining_balance": remaining_balance,
    }

def get_date_range_from_request():
    end_date_str = request.args.get('end_date', date.today().isoformat())
    start_date_str = request.args.get('start_date', (date.today() - timedelta(days=6)).isoformat())
    start_date = datetime.fromisoformat(start_date_str).replace(hour=0, minute=0, second=0)
    end_date = datetime.fromisoformat(end_date_str).replace(hour=23, minute=59, second=59)
    return start_date, end_date

def log_action(action, user_id=None):
    """Veritabanına bir log kaydı oluşturur."""
    if not user_id and current_user.is_authenticated:
        user_id = current_user.id
    
    if user_id:
        new_log = Log(user_id=user_id, action=action)
        db.session.add(new_log)
        db.session.commit()

# --- AUTH & MAIN ROUTES ---

@app.route('/')
def index():
    # Artık @login_required yok. Herkes bu sayfayı görebilir.
    return redirect(url_for('floor_plan'))

@app.route('/floor')
def floor_plan():
    # Artık @login_required yok.
    sections = Section.query.order_by(Section.name).all()
    return render_template('floor_plan.html', sections=sections)

@app.route('/clock-in', methods=['GET', 'POST'])
def clock_in():
    """
    Personelin kullanıcı adı ve şifresiyle vardiyasını başlatmasını sağlar (clock-in).
    """
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        
        # Kullanıcı var mı ve şifre doğru mu?
        if user and user.password == request.form.get('password'):
            # Kullanıcı zaten clock-in yapmış mı diye kontrol et
            active_shift = Shift.query.filter_by(user_id=user.id, clock_out=None).first()
            if active_shift:
                flash(f"{user.full_name} is already clocked in.", "warning")
                return redirect(url_for('clock_in'))

            # Yeni bir vardiya (shift) kaydı oluştur
            new_shift = Shift(user_id=user.id)
            db.session.add(new_shift)
            db.session.commit()
            
            log_action(f"User {user.full_name} clocked in.", user_id=user.id)
            flash(f"Welcome, {user.full_name}! You have been clocked in successfully.", "success")
            return redirect(url_for('floor_plan'))
        else:
            flash('Invalid username or password.', 'danger')
    
    # GET isteği için clock-in sayfasını göster
    return render_template('clock_in.html')

@app.route('/clock-out', methods=['GET', 'POST'])
def clock_out_list():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        
        user_to_logout = db.session.get(User, user_id)
        
        if user_to_logout and user_to_logout.password == password:
            last_shift = Shift.query.filter_by(user_id=user_id, clock_out=None).order_by(Shift.clock_in.desc()).first()
            if last_shift:
                last_shift.clock_out = datetime.utcnow()
                db.session.commit()
                flash(f"{user_to_logout.full_name} has been clocked out successfully.", "success")
                log_action(f"User {user_to_logout.full_name} clocked out.", user_id=user_to_logout.id)
            else:
                flash(f"{user_to_logout.full_name} was not clocked in.", "warning")
            return redirect(url_for('floor_plan'))
        else:
            flash("Invalid password.", "danger")
            # Hata durumunda aynı sayfaya geri yönlendir
            return redirect(url_for('clock_out_list'))

    # GET isteği: Vardiyası açık olan tüm kullanıcıları listele
    open_shifts = Shift.query.filter(Shift.clock_out == None).all()
    clocked_in_users = [shift.user for shift in open_shifts]
    return render_template('clock_out_list.html', users=clocked_in_users)

@app.route('/management/access', methods=['POST'])
def access_management():
    employee_number = request.form.get('employee_number')
    target_page = request.form.get('target_page', 'management_dashboard') # Varsayılan hedef
    
    user = User.query.filter_by(employee_number=employee_number).first()
    
    if user and user.role in HIGH_PRIVILEGE_ROLES:
        # Yönetim alanlarına erişim için kullanıcıyı geçici olarak login yap
        login_user(user)
        log_action(f"Manager {user.full_name} accessed management area.", user_id=user.id)
        
        # Hedef sayfanın geçerli bir yönetim sayfası olup olmadığını kontrol et
        allowed_pages = [
            'management_dashboard', 'layout_management', 'menu_management', 
            'category_management', 'staff_management', 'printer_management', 
            'reports_dashboard'
        ]
        
        if target_page in allowed_pages:
             return redirect(url_for(target_page))
        # Geçersiz bir hedef varsa, ana yönetim paneline yönlendir
        return redirect(url_for('management_dashboard'))
    else:
        flash("Access Denied. Invalid Employee Number or insufficient privileges.", "danger")
        return redirect(url_for('floor_plan'))

# --- ORDER MANAGEMENT ---
@app.route('/order/new/table/<int:table_id>')
@login_required
@service_level_required
def new_order(table_id):
    table = db.session.get(RestaurantTable, table_id)
    order = Order(table_id=table.id, user_id=current_user.id, order_type='Dine-In')
    db.session.add(order)
    seat = Seat(order=order, seat_number=1)
    db.session.add(seat)
    table.status = 'Occupied'
    db.session.commit()
    return redirect(url_for('view_order', order_id=order.id))

@app.route('/order_item/<int:order_id>/update_seats', methods=['POST'])
@login_required
def update_item_seats(order_id):
    """
    Sürükle-bırak sonrası koltuk düzenini veritabanında günceller.
    Gelen veri: {'item_id': new_seat_id, 'item_id_2': new_seat_id_2, ...}
    """
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data received'}), 400

    try:
        # Gelen tüm item ID'leri için tek bir sorgu yapalım
        items_to_update = db.session.query(OrderItem).filter(OrderItem.id.in_(data.keys())).all()
        
        item_map = {str(item.id): item for item in items_to_update}

        for item_id, new_seat_id in data.items():
            if item_id in item_map:
                item = item_map[item_id]
                # Sadece sipariş ID'si doğruysa ve koltuk değişmişse güncelle
                if item.order_id == order_id and item.seat_id != int(new_seat_id):
                    item.seat_id = int(new_seat_id)
                    log_action(f"Moved item '{item.menu_item.name}' to Seat ID {new_seat_id} in Order #{order_id}")
            
        db.session.commit()
        flash('Seat assignments have been updated successfully!', 'success')
        return jsonify({'status': 'success', 'message': 'Seat assignments updated.'})

    except Exception as e:
        db.session.rollback()
        print(f"Error updating seats: {e}")
        return jsonify({'status': 'error', 'message': 'An internal error occurred.'}), 500

@app.route('/table/<int:table_id>/access', methods=['POST'])
def access_table(table_id):
    employee_number = request.form.get('employee_number')
    user = User.query.filter_by(employee_number=employee_number).first()

    if not user:
        flash("Invalid Employee Number.", "danger")
        return redirect(url_for('floor_plan'))

    # --- YENİ VE DOĞRU KONTROL ---
    # Bu kullanıcı için henüz kapatılmamış bir vardiya (shift) var mı?
    active_shift = Shift.query.filter_by(user_id=user.id, clock_out=None).first()
    if not active_shift:
        flash(f"{user.full_name}, you are not clocked in. Please enter your password to start your shift.", "warning")
        # Kullanıcıyı, kullanıcı adını bildiğimiz clock-in sayfasına yönlendir
        # Bu, tekrar kullanıcı adı girmesini engeller (daha sonra eklenebilir bir özellik)
        return redirect(url_for('clock_in')) # <-- DÜZELTME: clock_in sayfasına yönlendir
    # --- KONTROL SONU ---

    is_manager = user.role in HIGH_PRIVILEGE_ROLES
    table = db.session.get(RestaurantTable, table_id)
    active_order = Order.query.filter_by(table_id=table.id, is_closed=False).first()

    if active_order:
        # Masa doluysa, sahiplik kontrolü yap
        if not is_manager and active_order.user_id != user.id:
            flash(f"Table is locked by {active_order.user.full_name}. Manager override required.", "warning")
            return redirect(url_for('floor_plan'))
        else:
            # Erişim izni verildi, logla ve yönlendir
            log_action(f"User {user.full_name} ({user.employee_number}) accessed Order #{active_order.id}", user_id=user.id)
            # Geçici login yaparak sipariş ekranındaki işlemleri yetkilendir
            login_user(user)
            return redirect(url_for('view_order', order_id=active_order.id))
    else:
        # Masa boşsa, yeni sipariş oluştur ve yönlendir
        new_order_obj = Order(table_id=table.id, user_id=user.id, order_type='Dine-In')
        db.session.add(new_order_obj)
        seat = Seat(order=new_order_obj, seat_number=1)
        db.session.add(seat)
        table.status = 'Occupied'
        db.session.commit()
        
        log_action(f"User {user.full_name} ({user.employee_number}) created Order #{new_order_obj.id}", user_id=user.id)

        socketio.emit('update_status', {
            'table_id': table.id, 
            'new_status': 'Occupied',
            'server_name': user.full_name,
            'order_id': new_order_obj.id
        })
        # Geçici login yap
        login_user(user)
        update_table_on_all_screens(table.id)
        return redirect(url_for('view_order', order_id=new_order_obj.id))

@app.route('/order/<int:order_id>/release')
@login_required # Bu işlemi sadece "geçici login" olmuş kullanıcı yapabilir
def release_table_lock(order_id):
    """Sipariş ekranından çıkıldığında masa kilidini kaldırır."""
    order = db.session.get(Order, order_id)
    if order and order.active_user_id == current_user.id:
        table_id_to_unlock = order.table_id
        order.active_user_id = None
        db.session.commit()
        # Diğer ekranlara kilidin kalktığını bildir
        socketio.emit('table_lock_status', {'table_id': table_id_to_unlock, 'locked': False})
        log_action(f"User {current_user.full_name} released lock on Order #{order.id}")
    
    # Geçici oturumu sonlandır ve ana ekrana dön
    logout_user() 
    return redirect(url_for('floor_plan'))

@app.route('/order/<int:order_id>')
@login_required
@service_level_required
def view_order(order_id):
    order = db.session.get(Order, order_id)
    if not order or order.is_closed:
        flash('Order not found or is already closed.', 'warning')
        return redirect(url_for('floor_plan'))

    # Table Lock/Ownership Check
    if current_user.role not in HIGH_PRIVILEGE_ROLES:
        # This logic should be here to prevent direct URL access
        if order.user_id != current_user.id and order.active_user_id != current_user.id:
            flash(f"This table is currently served by {order.user.full_name}. Manager access required.", 'danger')
            return redirect(url_for('floor_plan'))

    totals = get_order_totals(order_id)
    
    # --- THIS IS THE FIX ---
    # Find the "Parked Tables" section
    park_section = Section.query.filter_by(name="Parked Tables").first()
    # If the section exists, get its tables; otherwise, provide an empty list
    park_tables = park_section.tables if park_section else []
    # -----------------------
    
    return render_template('order.html', 
                           order=order, 
                           categories=Category.query.all(), 
                           menu_items=MenuItem.query.all(),
                           park_tables=park_tables, # <-- Pass the park tables to the template
                           total=totals['remaining_balance'])

@app.route('/order/<int:order_id>/park_items', methods=['POST'])
@login_required
@manager_level_required # Sadece yöneticiler park edebilir
def park_items(order_id):
    data = request.get_json()
    item_ids = data.get('item_ids')
    park_table_id = data.get('park_table_id')

    if not item_ids or not park_table_id:
        return jsonify({'status': 'error', 'message': 'Missing data'}), 400

    # Park masası için yeni bir sipariş oluştur veya mevcut olanı bul
    park_order = Order.query.filter_by(table_id=park_table_id, is_closed=False).first()
    if not park_order:
        park_order = Order(table_id=park_table_id, user_id=current_user.id)
        db.session.add(park_order)
        # Park siparişine de en az bir koltuk ekle
        seat = Seat(order=park_order, seat_number=1)
        db.session.add(seat)
        db.session.commit()
    
    park_seat_id = park_order.seats[0].id

    items_to_park = OrderItem.query.filter(OrderItem.id.in_(item_ids)).all()
    original_order_id = items_to_park[0].order_id if items_to_park else None
    
    for item in items_to_park:
        item.order_id = park_order.id
        item.seat_id = park_seat_id # Tümünü park masasındaki ilk koltuğa ata
    
    log_action(f"Parked {len(items_to_park)} items from Order #{original_order_id} to Order #{park_order.id}")
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Items parked successfully.'})

# 3. İndirim ve ikramları işleyecek yeni rota
@app.route('/order/<int:order_id>/apply_comp', methods=['POST'])
@login_required
@manager_level_required
def apply_comp(order_id):
    item_ids_str = request.form.get('item_ids')
    item_ids = [int(i) for i in item_ids_str.split(',')]
    comp_type = request.form.get('comp_type')
    comp_reason = request.form.get('comp_reason') if comp_type == 'Manager Comp' else comp_type

    items_to_comp = OrderItem.query.filter(OrderItem.id.in_(item_ids)).all()

    for item in items_to_comp:
        if comp_type in ["Manager Comp", "Manager Meal", "GC Comp"]:
            item.discount_amount = item.price_at_time_of_order * item.quantity
        elif comp_type == "Staff Discount":
            item.discount_amount = (item.price_at_time_of_order * item.quantity) * 0.20
        
        item.discount_reason = comp_reason
        log_action(f"Applied '{comp_reason}' to item '{item.menu_item.name}' (Value: ${item.discount_amount}) in Order #{order_id}")

    db.session.commit()
    flash(f"'{comp_type}' applied to {len(items_to_comp)} items.", 'success')
    return redirect(url_for('payment_screen', order_id=order_id))

@app.route('/order/<int:order_id>/add_item', methods=['POST'])
@login_required
def add_order_item(order_id):
    order = db.session.get(Order, order_id)
    seat_id = request.form.get('seat_id')
    menu_item_id = request.form.get('menu_item_id')
    
    # Formdan miktar bilgisini al, gelmezse varsayılan olarak 1 kullan
    quantity = int(request.form.get('quantity', 1))

    if not seat_id or not menu_item_id:
        flash("A seat and menu item must be selected.", "warning")
        return redirect(url_for('view_order', order_id=order_id))
    
    menu_item = db.session.get(MenuItem, int(menu_item_id))
    
    order_item = OrderItem(
        order_id=order.id, 
        menu_item_id=menu_item.id, 
        seat_id=seat_id, 
        notes=request.form.get('notes'), 
        status='Pending',
        quantity=quantity,  # Miktarı burada ata
        price_at_time_of_order=menu_item.price
    )
    db.session.add(order_item)
    
    # DÜZELTİLMİŞ LOGLAMA
    # Artık doğru değişken olan 'quantity' kullanılıyor
    log_action(f"Added {quantity}x '{menu_item.name}' to Order #{order_id}")
    
    db.session.commit()
    flash(f'{quantity}x {menu_item.name} added to order (Pending).', 'info')
    return redirect(url_for('view_order', order_id=order_id))

@app.route('/order/<int:order_id>/add_seat')
@login_required
def add_seat(order_id):
    order = db.session.get(Order, order_id)
    new_seat_number = (max(s.seat_number for s in order.seats) + 1) if order.seats else 1
    seat = Seat(order_id=order.id, seat_number=new_seat_number)
    db.session.add(seat)
    db.session.commit()
    return redirect(url_for('view_order', order_id=order.id))

@app.route('/order/<int:order_id>/send_selected', methods=['POST'])
@login_required
def send_selected_items(order_id):
    item_ids = request.form.getlist('item_ids')
    if not item_ids:
        flash("No items selected to send.", 'warning')
        return redirect(url_for('view_order', order_id=order_id))

    items_to_send = OrderItem.query.filter(OrderItem.id.in_(item_ids), OrderItem.status == 'Pending').all()
    
    if not items_to_send:
        flash("Selected items have already been sent or do not exist.", 'info')
        return redirect(url_for('view_order', order_id=order_id))

    # Her ürünün durumunu güncelle ve GÖNDERİLME ZAMANINI KAYDET
    for item in items_to_send:
        item.status = 'Sent'
        item.sent_at = datetime.utcnow() # <-- YENİ EKLENEN SATIR
        
    db.session.commit()

    flash(f"{len(items_to_send)} item(s) have been sent to the kitchen.", 'success')
    return redirect(url_for('print_kitchen_slip', order_id=order_id))

@app.route('/order/<int:order_id>/delete_pending', methods=['POST'])
@login_required
def delete_pending_items(order_id):
    item_ids = request.form.getlist('item_ids')
    if not item_ids:
        flash("No items selected to delete.", 'warning')
        return redirect(url_for('view_order', order_id=order_id))
    items_to_delete = OrderItem.query.filter(OrderItem.id.in_(item_ids), OrderItem.status == 'Pending').all()
    if not items_to_delete:
        flash("Only 'Pending' items can be deleted.", 'info')
        return redirect(url_for('view_order', order_id=order_id))
    count = len(items_to_delete)
    for item in items_to_delete:
        db.session.delete(item)
    db.session.commit()
    flash(f"{count} pending item(s) have been deleted.", 'success')
    return redirect(url_for('view_order', order_id=order_id))

@app.route('/order_item/<int:item_id>/void')
@login_required
@manager_level_required
def void_item(item_id):
    log_action(f"Voided item '{item.menu_item.name}' from Order #{item.order_id}")
    item = db.session.get(OrderItem, item_id)
    if not item.payment_id:
        item.is_void = True
        db.session.commit()
        flash(f'Item "{item.menu_item.name}" has been voided.', 'warning')
    else:
        flash("Cannot void an item that has already been paid.", "danger")
    return redirect(url_for('view_order', order_id=item.order_id))

# --- PAYMENT FLOW ROUTES ---
@app.route('/order/<int:order_id>/pay')
@login_required
def payment_screen(order_id):
    totals = get_order_totals(order_id)
    if not totals:
        flash("Order not found.", "danger")
        return redirect(url_for('floor_plan'))
    # --- YENİ VERİ YAPILANDIRMASI ---
    # Ödenmemiş ürünleri koltuklarına göre grupla
    seats_with_items_dict = {}
    for item in totals['unpaid_items']:
        seat = item.seat
        if seat.id not in seats_with_items_dict:
            seats_with_items_dict[seat.id] = {
                'id': seat.id,
                'number': seat.seat_number,
                'items': [],
                'total': 0.0
            }
        
        item_price = item.price_at_time_of_order * item.quantity
        seats_with_items_dict[seat.id]['items'].append(item)
        seats_with_items_dict[seat.id]['total'] += item_price * (1 + totals['order'].tax_rate)
    
    # Sözlüğü, koltuk numarasına göre sıralanmış bir listeye çevir
    seats_with_items_list = sorted(seats_with_items_dict.values(), key=lambda x: x['number'])
    
    # Ödenmiş ürünleri de şablona gönderelim
    paid_items = [item for item in totals['order'].order_items if item.payment_id and not item.is_void]

    return render_template(
        'payment_screen.html',
        order=totals['order'],
        unpaid_items=totals['unpaid_items'],
        paid_items=paid_items,
        seats_with_items=seats_with_items_list,
        remaining_balance=totals['remaining_balance']
    )

@app.route('/order/<int:order_id>/process_transaction', methods=['POST'])
@login_required
def process_transaction(order_id):
    order = db.session.get(Order, order_id)
    item_ids_to_pay = request.form.getlist('item_ids[]')
    
    if not item_ids_to_pay:
        flash("No items selected for payment.", "warning")
        return redirect(url_for('payment_screen', order_id=order_id))

    items_for_payment = db.session.query(OrderItem).filter(OrderItem.id.in_([int(i) for i in item_ids_to_pay])).all()
    
    # Hesaplamaları yap
    subtotal = sum(item.price_at_time_of_order * item.quantity for item in items_for_payment)
    total_for_items = subtotal * (1 + order.tax_rate)
    
    # Formdan gelen değeri al
    amount_paid_by_customer = float(request.form.get('amount_paid', 0))

    # --- BU KISIM EN ÖNEMLİ DÜZELTME ---
    # Karşılaştırma yapmadan önce her iki değeri de 2 ondalık basamağa yuvarla
    if round(amount_paid_by_customer, 2) < round(total_for_items, 2):
        flash(f'Amount paid (${amount_paid_by_customer:.2f}) is less than total (${total_for_items:.2f}).', 'danger')
        # Hata durumunda payment_screen'e geri yönlendirmek yerine,
        # ödeme formunu tekrar göstermek daha iyi bir kullanıcı deneyimi sunar.
        # Bu, process_payment.html şablonunu gerektirir. Şimdilik yönlendirmeye devam edelim.
        return redirect(url_for('payment_screen', order_id=order_id))
    # ------------------------------------

    # Bahşişi de yuvarlanmış değerler üzerinden hesapla
    tip = round(amount_paid_by_customer, 2) - round(total_for_items, 2)
    
    # Ödeme kaydını oluştur
    new_payment = Payment(
        order_id=order.id,
        payment_method=request.form.get('payment_method'),
        amount_paid=amount_paid_by_customer,
        subtotal=subtotal,
        tax_amount=total_for_items - subtotal,
        tip_amount=tip
    )
    db.session.add(new_payment)
    db.session.commit()

    # Ödenen ürünleri bu yeni ödemeye bağla
    for item in items_for_payment:
        item.payment_id = new_payment.id
    db.session.commit()

    flash(f'Payment of ${total_for_items:.2f} processed (Tip: ${tip:.2f}).', 'success')
    return redirect(url_for('payment_screen', order_id=order_id))

@app.route('/order/<int:order_id>/close')
@login_required
def close_order(order_id):
    totals = get_order_totals(order_id)
    if totals and totals['remaining_balance'] > 0.01:
        flash('Cannot close with a remaining balance.', 'danger')
        return redirect(url_for('payment_screen', order_id=order_id))
    order = totals['order']
    table_id_to_update = order.table_id
    order.is_closed = True
    order.bill_printed_at = None
    if order.table and order.order_type == 'Dine-In':
        order.table.status = 'Available'
    db.session.commit()
    if table_id_to_update:
        update_table_on_all_screens(table_id_to_update)
    socketio.emit('update_status', {
        'table_id': table_id_to_update,
        'new_status': 'Available'
    })

    flash(f'Order #{order.id} has been closed.', 'success')
    return redirect(url_for('floor_plan'))
    flash(f'Order #{order.id} has been closed.', 'success')
    return redirect(url_for('floor_plan'))
    
    if order.order_type == 'Take-Out':
        return redirect(url_for('takeout_list'))
    else:
        return redirect(url_for('floor_plan'))

# --- TAKE-OUT ROUTES ---
@app.route('/takeout')
@login_required
def takeout_list():
    orders = Order.query.filter_by(order_type='Take-Out', is_closed=False).order_by(Order.created_at.desc()).all()
    order_totals = {order.id: get_order_totals(order.id)['total_due'] for order in orders}
    return render_template('takeout_list.html', takeout_orders=orders, order_totals=order_totals)

@app.route('/takeout/new', methods=['GET', 'POST'])
@login_required
def new_takeout_order():
    if request.method == 'POST':
        takeout_table = RestaurantTable.query.filter_by(name="Take-Out Orders", is_special=True).first()
        order = Order(user_id=current_user.id, order_type='Take-Out', customer_name=request.form.get('customer_name'), customer_phone=request.form.get('customer_phone'), pickup_time=request.form.get('pickup_time', 'ASAP'), table_id=takeout_table.id)
        db.session.add(order)
        seat = Seat(order=order, seat_number=1)
        db.session.add(seat)
        db.session.commit()
        flash('New take-out order created.', 'success')
        return redirect(url_for('view_order', order_id=order.id))
    return render_template('new_takeout_form.html')

# --- LAYOUT MANAGEMENT ---


@app.route('/management/layout', methods=['GET'])
@login_required
@manager_level_required
def layout_management():
    """Bölüm ve masa yönetimi ana sayfasını gösterir."""
    sections = Section.query.order_by(Section.name).all()
    # YENİ EKLENEN SATIR: Veritabanındaki tüm yazıcıları al
    printers = Printer.query.order_by(Printer.name).all()
    
    # Şablona hem bölümleri hem de yazıcıları gönder
    return render_template('management/sections_and_tables.html', sections=sections, printers=printers)

@app.route('/management/dashboard')
@login_required # Bu geçici login sonrası erişimi korur
@manager_level_required # Sadece yüksek yetkili rollerin erişebildiğinden emin ol
def management_dashboard():
    """Tüm yönetim linklerini içeren ana paneli gösterir."""
    return render_template('management/management_dashboard.html')


@app.route('/management/section/add', methods=['POST'])
@login_required
@manager_level_required
def add_section():
    """Yeni bir bölüm ekler."""
    section_name = request.form.get('section_name')
    printer_id_str = request.form.get('default_printer_id')
    receipt_printer_id_str = request.form.get('receipt_printer_id')

    if section_name:
        # Aynı isimde bir bölüm olup olmadığını kontrol et
        if Section.query.filter_by(name=section_name).first():
            flash(f'A section with the name "{section_name}" already exists.', 'warning')
            return redirect(url_for('layout_management'))

        # Gelen ID string'lerini integer'a veya None'a çevir
        default_printer_id = int(printer_id_str) if printer_id_str else None
        receipt_printer_id = int(receipt_printer_id_str) if receipt_printer_id_str else None

        # Yeni Section nesnesini oluştur
        new_section = Section(
            name=section_name,
            default_printer_id=default_printer_id,
            receipt_printer_id=receipt_printer_id
        )
        db.session.add(new_section)
        db.session.commit()
        flash(f'Section "{section_name}" has been added successfully.', 'success')
    else:
        flash('Section name is required.', 'danger')
        
    return redirect(url_for('layout_management'))

@app.route('/management/table/add', methods=['POST'])
@login_required
@manager_level_required
def add_table():
    table_name = request.form.get('table_name')
    section_id = request.form.get('section_id')
    if table_name and section_id:
        db.session.add(RestaurantTable(name=table_name, section_id=section_id))
        db.session.commit()
        flash(f'Table "{table_name}" added.', 'success')
    return redirect(url_for('layout_management'))
    
@app.route('/management/section/delete/<int:section_id>')
@login_required
@manager_level_required
def delete_section(section_id):
    section = db.session.get(Section, section_id)
    if section:
        if db.session.query(Order).join(RestaurantTable).filter(RestaurantTable.section_id == section_id, Order.is_closed == False).first():
            flash(f'Cannot delete section "{section.name}" because it has active orders.', 'danger')
        else:
            db.session.delete(section)
            db.session.commit()
            flash(f'Section "{section.name}" and all its tables deleted.', 'success')
    return redirect(url_for('layout_management'))

@app.route('/management/table/delete/<int:table_id>')
@login_required
@manager_level_required
def delete_table(table_id):
    table = db.session.get(RestaurantTable, table_id)
    if table:
        if any(not o.is_closed for o in table.orders):
            flash(f'Cannot delete table "{table.name}" because it has an active order.', 'danger')
        else:
            db.session.delete(table)
            db.session.commit()
            flash(f'Table "{table.name}" deleted.', 'success')
    return redirect(url_for('layout_management'))

# --- OTHER MANAGEMENT ---
@app.route('/management/menu', methods=['GET', 'POST'])
@login_required
@manager_level_required
def menu_management():
    if request.method == 'POST':
        # ... (POST mantığı aynı kalıyor)
        new_item = MenuItem(name=request.form['name'], price=float(request.form['price']), category_id=int(request.form['category_id']))
        db.session.add(new_item)
        db.session.commit()
        flash(f'"{new_item.name}" added.', 'success')
        return redirect(url_for('menu_management'))
    
    # DÜZELTME: Şablona kategorileri ve yazıcıları da gönderiyoruz
    menu_items = MenuItem.query.order_by(MenuItem.name).all()
    categories = Category.query.order_by(Category.name).all()
    return render_template('management/menu.html', menu_items=menu_items, categories=categories)

@app.route('/management/menu/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
@manager_level_required
def edit_menu_item(item_id):
    item = db.session.get(MenuItem, item_id)
    if request.method == 'POST':
        item.name = request.form['name']; item.price = float(request.form['price']); item.category_id = int(request.form['category_id'])
        item.description = request.form.get('description'); item.allergens = request.form.get('allergens'); item.options = request.form.get('options')
        db.session.commit()
        flash(f'Updated "{item.name}".', 'success')
        return redirect(url_for('menu_management'))
    return render_template('management/edit_menu_item.html', item=item, categories=Category.query.all())

@app.route('/management/menu/delete/<int:item_id>')
@login_required
@manager_level_required
def delete_menu_item(item_id):
    item = db.session.get(MenuItem, item_id)
    db.session.delete(item)
    db.session.commit()
    flash(f'"{item.name}" deleted.', 'success')
    return redirect(url_for('menu_management'))

# app.py içindeki staff_management fonksiyonunu değiştirin

@app.route('/management/staff', methods=['GET', 'POST'])
@login_required
@manager_level_required
def staff_management():
    if request.method == 'POST':
        # Yeni alanları formdan al
        full_name = request.form.get('full_name')
        employee_number = request.form.get('employee_number')
        username = request.form.get('username')

        # Benzersiz olması gereken alanları kontrol et
        if User.query.filter_by(username=username).first():
            flash(f"Username '{username}' is already taken.", "danger")
            return redirect(url_for('staff_management'))
        if User.query.filter_by(employee_number=employee_number).first():
            flash(f"Employee Number '{employee_number}' is already in use.", "danger")
            return redirect(url_for('staff_management'))

        new_user = User(
            full_name=full_name,
            employee_number=employee_number,
            username=username,
            password=request.form.get('password'), # Gerçek uygulamada hash'lenmeli!
            role=request.form.get('role')
        )
        db.session.add(new_user)
        db.session.commit()
        flash(f'Staff member "{full_name}" has been added successfully.', 'success')
        return redirect(url_for('staff_management'))
    
    users = User.query.order_by(User.full_name).all()
    return render_template('management/staff.html', users=users)
@app.route('/management/staff/delete/<int:user_id>')
@login_required
@manager_level_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash("You cannot delete your own account.", 'danger')
        return redirect(url_for('staff_management'))
    user = db.session.get(User, user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash(f'User "{user.username}" deleted.', 'success')
    return redirect(url_for('staff_management'))

@app.route('/management/staff/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@manager_level_required
def edit_staff(user_id):
    """Mevcut bir personelin bilgilerini düzenler."""
    user_to_edit = db.session.get(User, user_id)
    if not user_to_edit:
        flash("User not found.", "danger")
        return redirect(url_for('staff_management'))

    if request.method == 'POST':
        # Formdan gelen yeni bilgileri al
        new_username = request.form.get('username')
        new_employee_number = request.form.get('employee_number')

        # Benzersiz olması gereken alanların başka bir kullanıcı tarafından kullanılıp kullanılmadığını kontrol et
        if User.query.filter(User.id != user_id, User.username == new_username).first():
            flash(f"Username '{new_username}' is already taken by another user.", "danger")
            return render_template('management/edit_staff.html', user=user_to_edit)
        
        if User.query.filter(User.id != user_id, User.employee_number == new_employee_number).first():
            flash(f"Employee Number '{new_employee_number}' is already used by another user.", "danger")
            return render_template('management/edit_staff.html', user=user_to_edit)

        # Bilgileri güncelle
        user_to_edit.full_name = request.form.get('full_name')
        user_to_edit.employee_number = new_employee_number
        user_to_edit.username = new_username
        user_to_edit.role = request.form.get('role')

        # Şifre alanı doluysa, şifreyi de güncelle
        new_password = request.form.get('password')
        if new_password:
            user_to_edit.password = new_password # Gerçek uygulamada hash'lenmeli!
            flash("User details and password have been updated.", "success")
        else:
            flash("User details have been updated (password unchanged).", "success")

        db.session.commit()
        return redirect(url_for('staff_management'))

    # GET isteği: Düzenleme formunu kullanıcının mevcut bilgileriyle doldurarak göster
    return render_template('management/edit_staff.html', user=user_to_edit)

@app.route('/management/categories', methods=['GET'])
@login_required
@manager_level_required
def category_management():
    """Kategori yönetim sayfasını gösterir."""
    categories = Category.query.order_by(Category.name).all()
    printers = Printer.query.all()
    return render_template('management/categories.html', categories=categories, printers=printers)

@app.route('/management/category/add', methods=['POST'])
@login_required
@manager_level_required
def add_category():
    """Yeni bir kategori ekler."""
    category_name = request.form.get('category_name')
    printer_id = request.form.get('printer_id')

    if category_name and printer_id:
        if not Category.query.filter_by(name=category_name).first():
            new_category = Category(name=category_name, printer_id=printer_id)
            db.session.add(new_category)
            db.session.commit()
            flash(f'Category "{category_name}" has been added.', 'success')
        else:
            flash(f'A category with the name "{category_name}" already exists.', 'warning')
    else:
        flash('Category Name and Printer are required.', 'danger')
        
    return redirect(url_for('category_management'))

@app.route('/management/category/delete/<int:category_id>')
@login_required
@manager_level_required
def delete_category(category_id):
    """Bir kategoriyi ve içindeki tüm ürünleri siler."""
    # cascade="all, delete-orphan" ilişkisi sayesinde, kategoriyi sildiğimizde
    # ona bağlı MenuItem'lar da otomatik olarak silinecektir.
    category_to_delete = db.session.get(Category, category_id)
    if category_to_delete:
        category_name = category_to_delete.name
        db.session.delete(category_to_delete)
        db.session.commit()
        flash(f'Category "{category_name}" and all its items have been deleted.', 'success')
    else:
        flash('Category not found.', 'danger')
        
    return redirect(url_for('category_management'))

# --- REPORTING ROUTES ---
@app.route('/reports')
@login_required
@manager_level_required
def reports_dashboard():
    return render_template('management/reports_dashboard.html')

# app.py içindeki report_shifts fonksiyonunu güncelle
@app.route('/reports/shifts')
@login_required
@manager_level_required
def report_shifts():
    # ... (kodun başı aynı)
    # Rapor çıktısında artık tam isim ve personel numarası da olacak
    return render_template('management/report_shifts.html', ...)


@app.route('/reports/sales_summary')
@login_required
@manager_level_required
def report_sales_summary():
    start_date, end_date = get_date_range_from_request()
    payments = Payment.query.filter(Payment.created_at.between(start_date, end_date)).all()
    summary = {'net_sales': sum(p.subtotal for p in payments), 'total_tax': sum(p.tax_amount for p in payments), 'total_tips': sum(p.tip_amount for p in payments)}
    summary['gross_sales'] = summary['net_sales'] + summary['total_tax']
    payment_methods = {}
    for p in payments:
        if p.payment_method not in payment_methods: payment_methods[p.payment_method] = 0
        payment_methods[p.payment_method] += p.subtotal + p.tax_amount
    return render_template('management/report_sales_summary.html', report_title="Sales Summary", summary=summary, payment_methods=payment_methods, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

@app.route('/reports/product_mix')
@login_required
@manager_level_required
def report_product_mix():
    start_date, end_date = get_date_range_from_request()
    product_mix = db.session.query(
        MenuItem.name,
        func.sum(OrderItem.quantity).label('quantity_sold'),
        func.sum(OrderItem.price_at_time_of_order * OrderItem.quantity).label('total_revenue')
    ).join(OrderItem, MenuItem.id == OrderItem.menu_item_id)\
     .join(Payment, OrderItem.payment_id == Payment.id)\
     .filter(Payment.created_at.between(start_date, end_date))\
     .group_by(MenuItem.name)\
     .order_by(func.sum(OrderItem.quantity).desc())\
     .all()
    return render_template('management/report_product_mix.html', report_title="Product Mix Report", product_mix=product_mix, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

@app.route('/reports/employee_performance')
@login_required
@manager_level_required
def report_employee_performance():
    """Personel satış ve bahşiş performansını gösteren rapor."""
    start_date, end_date = get_date_range_from_request()
    
    performance_data = (
        db.session.query(
            User.full_name,
            User.employee_number,
            func.sum(Payment.subtotal).label('net_sales'),
            func.sum(Payment.tip_amount).label('total_tips')
        )
        .join(Order, User.id == Order.user_id)
        .join(Payment, Order.id == Payment.order_id)
        .filter(Payment.created_at.between(start_date, end_date))
        .group_by(User.full_name, User.employee_number)
        .order_by(func.sum(Payment.subtotal).desc())
        .all()
    )

    return render_template('management/report_employee_performance.html',
                           report_title="Employee Performance",
                           performance_data=performance_data,
                           start_date=start_date.strftime('%Y-%m-%d'),
                           end_date=end_date.strftime('%Y-%m-%d'))

# --- PRINTING ROUTES ---

@app.route('/print/kitchen/<int:order_id>')
@login_required
def print_kitchen_slip(order_id):
    order = db.session.get(Order, order_id)
    items_to_process = OrderItem.query.filter_by(order_id=order_id, status='Sent', printed_to_kitchen=False, is_void=False).all()
    
    if not items_to_process:
        flash('No new items to print.', 'info')
        return redirect(url_for('view_order', order_id=order_id))

    slips = {}
    for item in items_to_process:
        printer = item.menu_item.category.printer
        if not printer: printer = item.order.table.section.printer if item.order.table else None
        if not printer: continue
        if printer.id not in slips: slips[printer.id] = {"printer_obj": printer, "items": []}
        slips[printer.id]["items"].append(item)

    web_print_data = None
    
    for printer_id, slip_data in slips.items():
        printer = slip_data['printer_obj']
        items = slip_data['items']

        if printer.type == 'escpos':
            try:
                ip, port = printer.network_path.split(':')
                p = Network(ip, port=int(port), timeout=5)

                # --- FORMATLAMA (p.set) KALDIRILDI, p.cut() KORUNDU ---
                
                # Başlık ve bilgiler, ortalama olmadan, sola dayalı olarak yazdırılır.
                p.text(f"** {printer.name} **\n")
                p.text("================================\n")
                
                if order.order_type == 'Take-Out':
                    p.text(f"TAKE-OUT: {order.customer_name}\n")
                    p.text(f"PICKUP: {order.pickup_time}\n")
                else:
                    p.text(f"Table: {order.table.name}\n")
                
                p.text(f"Order #{order.id} / by: {order.user.username}\n")
                p.text(f"Time: {datetime.now(pytz.timezone('America/Halifax')).strftime('%I:%M %p')}\n")
                p.text("--------------------------------\n")

                # Ürün Listesi
                for item in items:
                    p.text(f"{item.quantity}x {item.menu_item.name}\n")
                    if order.order_type == 'Dine-In':
                        p.text(f"   Seat: {item.seat.seat_number}\n")
                    if item.notes:
                        p.text(f"   *** {item.notes.upper()} ***\n")
                    p.text("\n")
                
                # Fişin sonunda boşluk bırak ve kağıdı kes
                p.text("\n\n")
                p.cut() # <-- BU KOMUT KORUNDU
                
                flash(f'Slip successfully sent to network printer: {printer.name}.', 'success')
            
            except Exception as e:
                print(f"ERROR: Could not print to {printer.name}. Reason: {e}")
                flash(f'Error connecting to network printer "{printer.name}".', 'danger')
        
        else: # printer.type == 'web'
            web_print_data = {"order": order, "items_to_print": items, "printer_name": printer.name, "timestamp": datetime.now()}
            break 

    for item in items_to_process:
        item.printed_to_kitchen = True
    db.session.commit()

    if web_print_data:
        return render_template('print/kitchen_slip.html', **web_print_data)
    else:
        return redirect(url_for('view_order', order_id=order_id))

@app.route('/print/bill/<int:order_id>')
@login_required
def print_bill(order_id):
    split_by = request.args.get('split_by', 'full')
    order = db.session.get(Order, order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for('floor_plan'))

    if not order.bill_printed_at:
        order.bill_printed_at = datetime.utcnow()
        db.session.commit()
        update_table_on_all_screens(order.table_id)

    info_query = RestaurantInfo.query.all()
    restaurant_info = {info.key: info.value for info in info_query}
    unpaid_items = [item for item in order.order_items if not item.payment_id and not item.is_void]
    
    bills_to_process = []
    if split_by == 'seat':
        seats_with_items = {}
        for item in unpaid_items:
            if item.seat.id not in seats_with_items:
                seats_with_items[item.seat.id] = {'seat_number': item.seat.seat_number, 'items': []}
            seats_with_items[item.seat.id]['items'].append(item)
        for seat_id, seat_data in seats_with_items.items():
            sub_total = sum(i.price_at_time_of_order * i.quantity for i in seat_data['items'])
            total_discount = sum(i.discount_amount or 0 for i in seat_data['items'])
            pre_tax_total = sub_total - total_discount
            tax_amount = pre_tax_total * order.tax_rate
            total_due = pre_tax_total + tax_amount
            bills_to_process.append({'title': f"Bill for Seat #{seat_data['seat_number']}", 'items': seat_data['items'], 'subtotal': sub_total, 'total_discount': total_discount, 'tax': tax_amount, 'total': total_due})
    else: # 'full'
        sub_total = sum(item.price_at_time_of_order * item.quantity for item in unpaid_items)
        total_discount = sum(item.discount_amount or 0 for item in unpaid_items)
        pre_tax_total = sub_total - total_discount
        tax_amount = pre_tax_total * order.tax_rate
        total_due = pre_tax_total + tax_amount
        bills_to_process.append({'title': 'Full Bill', 'items': unpaid_items, 'subtotal': sub_total, 'total_discount': total_discount, 'tax': tax_amount, 'total': total_due})
    
    receipt_printer = order.table.section.receipt_printer if order.table and order.table.section.receipt_printer else Printer.query.filter_by(name="Receipt Printer").first()

    if receipt_printer and receipt_printer.type == 'escpos':
        try:
            ip, port = receipt_printer.network_path.split(':')
            p = Network(ip, port=int(port), timeout=5)

            for bill in bills_to_process:
                p.set(align='center')
                try: p.image("static/images/bt.png", impl='bitImageRaster')
                except Exception: p.text(f"{restaurant_info.get('restaurant_name', '')}\n")
                
                p.text(f"{restaurant_info.get('address_line_1', '')}\n{restaurant_info.get('address_line_2', '')}\nTel. {restaurant_info.get('phone_number', '')}\n")
                p.text("*"*32 + "\n")
                
                p.set(align='left')
                p.text(f"{datetime.now(pytz.timezone('America/Halifax')).strftime('%m/%d/%y %I:%M %p')}\n")
                p.text(f"Table {order.table.name} / Order #{order.id}\n")
                if bill['title'] != 'Full Bill': p.text(f"{bill['title']}\n")
                p.text(f"Server: {order.user.full_name}\n")
                p.text("*"*32 + "\n")

                for item in bill['items']:
                    price_str = f"{item.price_at_time_of_order * item.quantity:.2f}"
                    item_name = item.menu_item.name[:20]
                    p.text(f"{item.quantity} {item_name.ljust(24-len(price_str))}{price_str}\n")
                
                p.text("-"*32 + "\n")
                p.text(f"Sub-total{'${:,.2f}'.format(bill['subtotal']).rjust(22)}\n")
                if bill['total_discount'] > 0: p.text(f"Discounts{'${:,.2f}'.format(-bill['total_discount']).rjust(22)}\n")
                p.text(f"H.S.T.{'${:,.2f}'.format(bill['tax']).rjust(26)}\n")
                p.text("-"*32 + "\n")

                p.set(align='center', double_height=True, double_width=True)
                p.text(f"Total: ${bill['total']:.2f}\n")
                p.set(double_height=False, double_width=False)
                p.text("\n\n\n"); p.cut()

            flash(f'Receipt(s) sent to {receipt_printer.name}.', 'success')
            return redirect(url_for('payment_screen', order_id=order_id))

        except Exception as e:
            print(f"ERROR printing receipt: {e}")
            flash(f"Could not print receipt to {receipt_printer.name}. Falling back to PDF.", "danger")
    
    return render_template('print/bill.html', 
                           order=order, bills=bills_to_process,
                           restaurant_info=restaurant_info, timestamp=datetime.now())


# --- PRINTER MANAGEMENT ---
@app.route('/management/printers', methods=['GET'])
@app.route('/management/printers/edit/<int:edit_id>', methods=['GET']) # Edit için GET rotası
@login_required
@manager_level_required
def printer_management(edit_id=None):
    """Yazıcı yönetim sayfasını gösterir ve düzenleme modunu destekler."""
    printers = Printer.query.order_by(Printer.name).all()
    printer_to_edit = None
    if edit_id:
        printer_to_edit = db.session.get(Printer, edit_id)
    return render_template('management/printers.html', printers=printers, printer_to_edit=printer_to_edit)

@app.route('/management/printer/add', methods=['POST'])
@login_required
@manager_level_required
def add_printer():
    """Yeni bir yazıcı ekler."""
    printer_name = request.form.get('printer_name')
    printer_type = request.form.get('printer_type')
    network_path = request.form.get('network_path')

    if printer_name and printer_type:
        if printer_type == 'escpos' and not network_path:
            flash("Network Address is required for Network/Thermal printers.", "danger")
            return redirect(url_for('printer_management'))
            
        if not Printer.query.filter_by(name=printer_name).first():
            new_printer = Printer(
                name=printer_name,
                type=printer_type,
                network_path=network_path
            )
            db.session.add(new_printer)
            db.session.commit()
            flash(f'Printer "{printer_name}" has been added.', 'success')
        else:
            flash(f'A printer with the name "{printer_name}" already exists.', 'warning')
    else:
        flash('Printer Name and Type are required.', 'danger')
        
    return redirect(url_for('printer_management'))

@app.route('/management/printer/delete/<int:printer_id>')
@login_required
@manager_level_required
def delete_printer(printer_id):
    """Bir yazıcıyı siler."""
    printer_to_delete = db.session.get(Printer, printer_id)
    if printer_to_delete:
        # Bu yazıcıya atanmış kategori var mı diye kontrol et
        assigned_categories = Category.query.filter_by(printer_id=printer_id).first()
        if assigned_categories:
            flash(f'Cannot delete printer "{printer_to_delete.name}" because it is assigned to one or more categories. Please re-assign those categories first.', 'danger')
        else:
            printer_name = printer_to_delete.name
            db.session.delete(printer_to_delete)
            db.session.commit()
            flash(f'Printer "{printer_name}" has been deleted.', 'success')
    else:
        flash('Printer not found.', 'danger')
        
    return redirect(url_for('printer_management'))

@app.route('/management/printer/edit/<int:printer_id>', methods=['POST'])
@login_required
@manager_level_required
def edit_printer(printer_id):
    """Mevcut bir yazıcının bilgilerini günceller."""
    printer_to_edit = db.session.get(Printer, printer_id)
    if not printer_to_edit:
        flash("Printer not found.", "danger")
        return redirect(url_for('printer_management'))
    
    printer_name = request.form.get('printer_name')
    printer_type = request.form.get('printer_type')
    network_path = request.form.get('network_path')

    # Diğer validasyonlar...
    
    printer_to_edit.name = printer_name
    printer_to_edit.type = printer_type
    printer_to_edit.network_path = network_path
    
    db.session.commit()
    flash(f'Printer "{printer_name}" has been updated.', 'success')
    return redirect(url_for('printer_management'))

# app.py dosyasının uygun bir yerine bu fonksiyonu ekleyin

@app.after_request
def add_header(response):
    """
    Tüm yanıtlara cache kontrol başlıkları ekleyerek tarayıcının
    sayfaları önbelleğe almasını engeller. Bu, "geri" butonu
    güvenlik açığını kapatır.
    """
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response
   
@app.route('/management/exit')
@login_required
def exit_management():
    """Yönetici oturumunu sonlandırır."""
    logout_user()
    flash("You have exited the management area.", "info")
    return redirect(url_for('floor_plan'))

# --- MAIN EXECUTION ---

# app.py dosyasının en altındaki __main__ bloğunu bununla değiştirin

if __name__ == '__main__':
    # Flask uygulamasını ana işlemde başlat
    with app.app_context():
        db.create_all()
        create_initial_data()
    
    # Sunucuyu SocketIO ile çalıştır, reloader kapalı kalsın
    print("--- Starting Flask-SocketIO server (reloader is OFF) ---")
    print("--- To start the virtual printer, run 'python printer_server.py' in a SEPARATE terminal. ---")
    socketio.run(app, host='0.0.0.0', port=5001, debug=True, use_reloader=False)