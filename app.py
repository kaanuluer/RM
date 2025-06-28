from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, User, Shift, Section, RestaurantTable, Printer, Category, MenuItem, Order, OrderItem, Seat, Payment
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, date, timedelta
from functools import wraps
from sqlalchemy import func

# --- APP CONFIGURATION ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_very_secret_key_that_you_should_change'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# --- LOGIN MANAGER SETUP ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- DECORATORS ---
def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'Manager':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('floor_plan'))
        return f(*args, **kwargs)
    return decorated_function

# --- HELPER FUNCTIONS ---
def create_initial_data():
    with app.app_context():
        if db.session.query(User).first() is None:
            print("--- Database is empty. Creating initial data... ---")
            manager = User(username='manager', password='password', role='Manager')
            waiter = User(username='waiter', password='password', role='Waiter')
            db.session.add_all([manager, waiter])
            kitchen_printer = Printer(name='Kitchen Printer'); bar_printer = Printer(name='Bar Printer')
            db.session.add_all([kitchen_printer, bar_printer]); db.session.commit()
            appetizers_cat = Category(name='1st Gear (Appetizers)', printer_id=kitchen_printer.id)
            main_courses_cat = Category(name='2nd & High Gear (Mains)', printer_id=kitchen_printer.id)
            db.session.add_all([appetizers_cat, main_courses_cat]); db.session.commit()
            main_dining_section = Section(name="Main Dining Room"); special_section = Section(name="Special")
            db.session.add_all([main_dining_section, special_section]); db.session.commit()
            menu_items = [MenuItem(name='Local Oysters', price=3.50, category_id=appetizers_cat.id), MenuItem(name='Red Ravioli', price=26.00, category_id=main_courses_cat.id)]
            db.session.bulk_save_objects(menu_items)
            for i in range(1, 11): db.session.add(RestaurantTable(name=f'T{i}', section_id=main_dining_section.id))
            db.session.add(RestaurantTable(name="Take-Out Orders", is_special=True, section_id=special_section.id))
            db.session.commit()
            print("--- Initial data creation complete. ---")

def get_order_totals(order_id):
    order = db.session.get(Order, order_id)
    if not order: return None
    unpaid_items = [item for item in order.order_items if not item.payment_id and not item.is_void]
    subtotal_due = sum(item.price_at_time_of_order * item.quantity for item in unpaid_items)
    total_due = subtotal_due * (1 + order.tax_rate)
    total_paid = sum(p.subtotal + p.tax_amount for p in order.payments)
    return {"order": order, "unpaid_items": unpaid_items, "total_due": total_due, "total_paid": total_paid, "remaining_balance": total_due}

def get_date_range_from_request():
    end_date_str = request.args.get('end_date', date.today().isoformat())
    start_date_str = request.args.get('start_date', (date.today() - timedelta(days=6)).isoformat())
    start_date = datetime.fromisoformat(start_date_str).replace(hour=0, minute=0, second=0)
    end_date = datetime.fromisoformat(end_date_str).replace(hour=23, minute=59, second=59)
    return start_date, end_date

# --- AUTH & MAIN ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and user.password == request.form.get('password'):
            login_user(user); flash('Logged in successfully!', 'success'); return redirect(url_for('floor_plan'))
        else: flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('login'))

@app.route('/')
@app.route('/floor')
@login_required
def floor_plan():
    return render_template('floor_plan.html', sections=Section.query.order_by(Section.name).all())

# --- ORDER MANAGEMENT ---
@app.route('/order/new/table/<int:table_id>')
@login_required
def new_order(table_id):
    table = db.session.get(RestaurantTable, table_id); order = Order(table_id=table.id, user_id=current_user.id, order_type='Dine-In')
    db.session.add(order); seat = Seat(order=order, seat_number=1); db.session.add(seat); table.status = 'Occupied'
    db.session.commit(); return redirect(url_for('view_order', order_id=order.id))

@app.route('/order/<int:order_id>')
@login_required
def view_order(order_id):
    order = db.session.get(Order, order_id)
    if not order or order.is_closed: flash('Order not found or is already closed.', 'warning'); return redirect(url_for('floor_plan'))
    totals = get_order_totals(order_id)
    return render_template('order.html', order=order, categories=Category.query.all(), menu_items=MenuItem.query.all(), total=totals['remaining_balance'])

@app.route('/order/<int:order_id>/add_table')
@app.route('/order/<int:order_id>/add_seat')
@login_required
def add_seat(order_id):
    order = db.session.get(Order, order_id); new_seat_number = (max(s.seat_number for s in order.seats) + 1) if order.seats else 1
    seat = Seat(order_id=order.id, seat_number=new_seat_number); db.session.add(seat); db.session.commit()
    return redirect(url_for('view_order', order_id=order.id))

@app.route('/order/<int:order_id>/add_item', methods=['POST'])
@login_required
def add_order_item(order_id):
    order = db.session.get(Order, order_id)
    menu_item = db.session.get(MenuItem, int(request.form['menu_item_id']))
    # Ürün her zaman 'Pending' durumuyla eklenir
    order_item = OrderItem(
        order_id=order.id, 
        menu_item_id=menu_item.id, 
        seat_id=request.form['seat_id'], 
        notes=request.form.get('notes'), 
        status='Pending', 
        price_at_time_of_order=menu_item.price
    )
    db.session.add(order_item)
    db.session.commit()
    flash(f'{menu_item.name} added to order (Pending).', 'info')
    return redirect(url_for('view_order', order_id=order_id))


# YENİ ROTA: Seçilen ürünleri mutfağa gönderir
@app.route('/order/<int:order_id>/send_selected', methods=['POST'])
@login_required
def send_selected_items(order_id):
    item_ids = request.form.getlist('item_ids')
    if not item_ids:
        flash("No items selected to send.", 'warning')
        return redirect(url_for('view_order', order_id=order_id))

    # Sadece 'Pending' durumundaki seçili ürünleri al ve durumlarını 'Sent' yap
    items_to_send = OrderItem.query.filter(OrderItem.id.in_(item_ids), OrderItem.status == 'Pending').all()
    
    if not items_to_send:
        flash("Selected items have already been sent or do not exist.", 'info')
        return redirect(url_for('view_order', order_id=order_id))

    for item in items_to_send:
        item.status = 'Sent'
    db.session.commit()

    flash(f"{len(items_to_send)} item(s) have been sent to the kitchen.", 'success')
    # Yazdırma işlemini tetikle
    return redirect(url_for('print_kitchen_slip', order_id=order_id))


# YENİ ROTA: Seçilen beklemedeki ürünleri siler
@app.route('/order/<int:order_id>/delete_pending', methods=['POST'])
@login_required
def delete_pending_items(order_id):
    item_ids = request.form.getlist('item_ids')
    if not item_ids:
        flash("No items selected to delete.", 'warning')
        return redirect(url_for('view_order', order_id=order_id))

    # Sadece 'Pending' durumundaki seçili ürünleri veritabanından sil
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
@manager_required
def void_item(item_id):
    item = db.session.get(OrderItem, item_id); item.is_void = True; db.session.commit()
    flash(f'Item "{item.menu_item.name}" has been voided.', 'warning'); return redirect(url_for('view_order', order_id=item.order_id))

# --- PAYMENT FLOW ROUTES ---
@app.route('/order/<int:order_id>/pay')
@login_required
def payment_screen(order_id):
    totals = get_order_totals(order_id)
    if not totals: flash("Order not found.", "danger"); return redirect(url_for('floor_plan'))
    return render_template('payment_screen.html', **totals)

@app.route('/order/<int:order_id>/process_transaction', methods=['POST'])
@login_required
def process_transaction(order_id):
    order = db.session.get(Order, order_id)
    item_ids_to_pay = request.form.getlist('item_ids[]')
    if not item_ids_to_pay: flash("No items selected for payment.", "warning"); return redirect(url_for('payment_screen', order_id=order_id))
    items_for_payment = db.session.query(OrderItem).filter(OrderItem.id.in_([int(i) for i in item_ids_to_pay])).all()
    subtotal = sum(item.price_at_time_of_order * item.quantity for item in items_for_payment)
    total_for_items = subtotal * (1 + order.tax_rate)
    amount_paid = float(request.form.get('amount_paid', 0))
    if amount_paid < total_for_items - 0.001: flash(f'Amount paid (${amount_paid:.2f}) is less than total (${total_for_items:.2f}).', 'danger'); return redirect(url_for('payment_screen', order_id=order_id))
    tip = amount_paid - total_for_items
    new_payment = Payment(order_id=order.id, payment_method=request.form.get('payment_method'), amount_paid=amount_paid, subtotal=subtotal, tax_amount=total_for_items - subtotal, tip_amount=tip)
    db.session.add(new_payment); db.session.commit()
    for item in items_for_payment: item.payment_id = new_payment.id
    db.session.commit()
    flash(f'Payment of ${total_for_items:.2f} processed (Tip: ${tip:.2f}).', 'success'); return redirect(url_for('payment_screen', order_id=order_id))

@app.route('/order/<int:order_id>/close')
@login_required
def close_order(order_id):
    totals = get_order_totals(order_id)
    if totals and totals['remaining_balance'] > 0.01: flash('Cannot close with a remaining balance.', 'danger'); return redirect(url_for('payment_screen', order_id=order_id))
    order = totals['order']; order.is_closed = True
    if order.table and order.order_type == 'Dine-In': order.table.status = 'Available'
    db.session.commit(); flash(f'Order #{order.id} has been closed.', 'success'); return redirect(url_for('floor_plan'))

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
        db.session.add(order); seat = Seat(order=order, seat_number=1); db.session.add(seat); db.session.commit()
        flash('New take-out order created.', 'success'); return redirect(url_for('view_order', order_id=order.id))
    return render_template('new_takeout_form.html')

# --- LAYOUT MANAGEMENT ---
@app.route('/management/layout', methods=['GET'])
@login_required
@manager_required
def layout_management():
    return render_template('management/sections_and_tables.html', sections=Section.query.order_by(Section.name).all())

@app.route('/management/section/add', methods=['POST'])
@login_required
@manager_required
def add_section():
    section_name = request.form.get('section_name')
    if section_name and not Section.query.filter_by(name=section_name).first():
        db.session.add(Section(name=section_name)); db.session.commit(); flash(f'Section "{section_name}" added.', 'success')
    else: flash(f'Section "{section_name}" already exists or name is invalid.', 'warning')
    return redirect(url_for('layout_management'))

@app.route('/management/table/add', methods=['POST'])
@login_required
@manager_required
def add_table():
    table_name = request.form.get('table_name'); section_id = request.form.get('section_id')
    if table_name and section_id:
        db.session.add(RestaurantTable(name=table_name, section_id=section_id)); db.session.commit(); flash(f'Table "{table_name}" added.', 'success')
    return redirect(url_for('layout_management'))
    
@app.route('/management/section/delete/<int:section_id>')
@login_required
@manager_required
def delete_section(section_id):
    section = db.session.get(Section, section_id)
    if section:
        if db.session.query(Order).join(RestaurantTable).filter(RestaurantTable.section_id == section_id, Order.is_closed == False).first():
            flash(f'Cannot delete section "{section.name}" because it has active orders.', 'danger')
        else: db.session.delete(section); db.session.commit(); flash(f'Section "{section.name}" deleted.', 'success')
    return redirect(url_for('layout_management'))

@app.route('/management/table/delete/<int:table_id>')
@login_required
@manager_required
def delete_table(table_id):
    table = db.session.get(RestaurantTable, table_id)
    if table:
        if any(not o.is_closed for o in table.orders): flash(f'Cannot delete table "{table.name}" because it has an active order.', 'danger')
        else: db.session.delete(table); db.session.commit(); flash(f'Table "{table.name}" deleted.', 'success')
    return redirect(url_for('layout_management'))

# --- OTHER MANAGEMENT ---
@app.route('/management/menu', methods=['GET', 'POST'])
@login_required
@manager_required
def menu_management():
    if request.method == 'POST':
        new_item = MenuItem(name=request.form['name'], price=float(request.form['price']), category_id=int(request.form['category_id']))
        db.session.add(new_item); db.session.commit(); flash(f'"{new_item.name}" added.', 'success'); return redirect(url_for('menu_management'))
    return render_template('management/menu.html', menu_items=MenuItem.query.all(), categories=Category.query.all())

@app.route('/management/menu/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
@manager_required
def edit_menu_item(item_id):
    item = db.session.get(MenuItem, item_id)
    if request.method == 'POST':
        item.name = request.form['name']; item.price = float(request.form['price']); item.category_id = int(request.form['category_id'])
        item.description = request.form.get('description'); item.allergens = request.form.get('allergens'); item.options = request.form.get('options')
        db.session.commit(); flash(f'Updated "{item.name}".', 'success'); return redirect(url_for('menu_management'))
    return render_template('management/edit_menu_item.html', item=item, categories=Category.query.all())

@app.route('/management/menu/delete/<int:item_id>')
@login_required
@manager_required
def delete_menu_item(item_id):
    item = db.session.get(MenuItem, item_id); db.session.delete(item); db.session.commit()
    flash(f'"{item.name}" deleted.', 'success'); return redirect(url_for('menu_management'))

@app.route('/management/staff', methods=['GET', 'POST'])
@login_required
@manager_required
def staff_management():
    if request.method == 'POST':
        new_user = User(username=request.form['username'], password=request.form['password'], role=request.form['role'])
        db.session.add(new_user); db.session.commit(); flash(f'Staff member "{new_user.username}" added.', 'success')
        return redirect(url_for('staff_management'))
    return render_template('management/staff.html', users=User.query.all())

@app.route('/management/staff/delete/<int:user_id>')
@login_required
@manager_required
def delete_user(user_id):
    if user_id == current_user.id: flash("You cannot delete your own account.", 'danger'); return redirect(url_for('staff_management'))
    user = db.session.get(User, user_id)
    if user: db.session.delete(user); db.session.commit(); flash(f'User "{user.username}" deleted.', 'success')
    return redirect(url_for('staff_management'))

# --- REPORTING ROUTES ---
@app.route('/reports')
@login_required
@manager_required
def reports_dashboard():
    return render_template('management/reports_dashboard.html')

@app.route('/reports/shifts')
@login_required
@manager_required
def report_shifts():
    start_date, end_date = get_date_range_from_request()
    shifts = Shift.query.filter(Shift.clock_in.between(start_date, end_date)).order_by(Shift.clock_in.desc()).all()
    for shift in shifts:
        if shift.clock_out: shift.total_hours = (shift.clock_out - shift.clock_in).total_seconds() / 3600
        else: shift.total_hours = 0
    return render_template('management/report_shifts.html', report_title="Shift Report", shifts=shifts, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

@app.route('/reports/sales_summary')
@login_required
@manager_required
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
@manager_required
def report_product_mix():
    start_date, end_date = get_date_range_from_request()
    product_mix = db.session.query(MenuItem.name, func.sum(OrderItem.quantity).label('quantity_sold'), func.sum(OrderItem.price_at_time_of_order * OrderItem.quantity).label('total_revenue')).join(OrderItem, MenuItem.id == OrderItem.menu_item_id).join(Payment, OrderItem.payment_id == Payment.id).filter(Payment.created_at.between(start_date, end_date)).group_by(MenuItem.name).order_by(func.sum(OrderItem.quantity).desc()).all()
    return render_template('management/report_product_mix.html', report_title="Product Mix Report", product_mix=product_mix, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

@app.route('/reports/employee_performance')
@login_required
@manager_required
def report_employee_performance():
    start_date, end_date = get_date_range_from_request()
    performance_data = db.session.query(User.username, func.sum(Payment.subtotal).label('net_sales'), func.sum(Payment.tip_amount).label('total_tips')).join(Order, User.id == Order.user_id).join(Payment, Order.id == Payment.order_id).filter(Payment.created_at.between(start_date, end_date)).group_by(User.username).order_by(func.sum(Payment.subtotal).desc()).all()
    return render_template('management/report_employee_performance.html', report_title="Employee Performance", performance_data=performance_data, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'))

# --- PRINTING ROUTES ---
@app.route('/print/kitchen/<int:order_id>')
@login_required
def print_kitchen_slip(order_id):
    order = db.session.get(Order, order_id)
    items_to_print = OrderItem.query.filter_by(order_id=order_id, status='Sent', printed_to_kitchen=False, is_void=False).all()
    if not items_to_print: flash('No new items to print.', 'info'); return redirect(url_for('view_order', order_id=order_id))
    slips = {}
    for item in items_to_print:
        printer_name = item.menu_item.category.printer.name
        if printer_name not in slips: slips[printer_name] = []
        slips[printer_name].append(item); item.printed_to_kitchen = True
    db.session.commit()
    first_printer_name = next(iter(slips), "Kitchen")
    return render_template('print/kitchen_slip.html', order=order, items_to_print=slips.get(first_printer_name, []), printer_name=first_printer_name, timestamp=datetime.now())

@app.route('/print/bill/<int:order_id>')
@login_required
def print_bill(order_id):
    totals = get_order_totals(order_id)
    if not totals: flash("Order not found.", "danger"); return redirect(url_for('floor_plan'))
    subtotal = totals['total_due'] / (1 + totals['order'].tax_rate); tax = totals['total_due'] - subtotal
    return render_template('print/bill.html', order=totals['order'], items=totals['unpaid_items'], subtotal=subtotal, tax=tax, total=totals['total_due'])

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_initial_data()
    app.run(host='0.0.0.0', port=5001, debug=True)