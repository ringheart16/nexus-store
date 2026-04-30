from flask import Flask, request, Response
from flask_cors import CORS
import xml.etree.ElementTree as ET
import requests
import time
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float
from sqlalchemy.orm import declarative_base, sessionmaker
import os

app = Flask(__name__)
CORS(app)

# ── Database Setup ──────────────────────────────────────────────────────────
DB_HOST     = os.environ.get("DB_HOST")
DB_USER     = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME     = os.environ.get("DB_NAME")

DATABASE_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:4000/{DB_NAME}"

engine = create_engine(DATABASE_URL)
Base   = declarative_base()

from flask import send_from_directory
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# ── Models ───────────────────────────────────────────────────────────────────

class InventoryItem(Base):
    __tablename__ = 'inventory'
    code     = Column(String(20),  primary_key=True)
    name     = Column(String(100))
    category = Column(String(50))
    stock    = Column(Integer)
    price    = Column(Float)


class Order(Base):
    __tablename__   = 'orders'
    transaction_id  = Column(String(20),  primary_key=True)
    timestamp       = Column(String(30))
    product_code    = Column(String(20))
    product         = Column(String(100))
    category        = Column(String(50))
    quantity        = Column(Integer)
    price_per_unit  = Column(Float)
    total_amount    = Column(Float)
    status          = Column(String(20))


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# ── Seed Data (laptop products) ──────────────────────────────────────────────
SEED_DATA = [
    InventoryItem(code="LAP-001", name="Dell XPS 15 Laptop",          category="LAPTOP",    stock=80,  price=1499.99),
    InventoryItem(code="LAP-002", name="Apple MacBook Pro 14-inch",    category="LAPTOP",    stock=60,  price=1999.00),
    InventoryItem(code="LAP-003", name="Lenovo ThinkPad X1 Carbon",    category="LAPTOP",    stock=75,  price=1349.00),
    InventoryItem(code="LAP-004", name="HP Spectre x360 13",           category="LAPTOP",    stock=50,  price=1249.99),
    InventoryItem(code="ACC-001", name="Laptop Cooling Pad",           category="COOLING",   stock=200, price=29.99),
    InventoryItem(code="ACC-002", name="USB-C Docking Station",        category="DOCK",      stock=150, price=89.99),
    InventoryItem(code="ACC-003", name="Laptop Backpack 15.6-inch",    category="BAG",       stock=300, price=45.00),
    InventoryItem(code="ACC-004", name="Wireless Bluetooth Mouse",     category="MOUSE",     stock=400, price=34.50),
    InventoryItem(code="ACC-005", name="Mechanical Keyboard TKL",      category="KEYBOARD",  stock=180, price=79.99),
    InventoryItem(code="ACC-006", name="27-inch 4K Monitor",           category="MONITOR",   stock=90,  price=399.00),
    InventoryItem(code="ACC-007", name="Laptop Privacy Screen Filter", category="SCREEN",    stock=250, price=22.00),
    InventoryItem(code="ACC-008", name="65W GaN USB-C Charger",        category="CHARGER",   stock=350, price=49.99),
    InventoryItem(code="ACC-009", name="16GB DDR5 RAM Module",         category="MEMORY",    stock=120, price=64.99),
    InventoryItem(code="ACC-010", name="1TB NVMe SSD",                 category="STORAGE",   stock=140, price=109.99),
]

with Session() as s:
    if s.query(InventoryItem).count() == 0:
        s.add_all(SEED_DATA)
        s.commit()

# ── Helper ───────────────────────────────────────────────────────────────────

def post_with_retry(url, data, retries=3, timeout=15):
    for attempt in range(retries):
        try:
            resp = requests.post(
                url, data=data,
                headers={'Content-Type': 'application/xml'},
                timeout=timeout
            )
            return resp
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                raise

# ═══════════════════════════════════════════════════════════════════════════════
# INVENTORY SERVICE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/inventory', methods=['GET'])
def get_inventory():
    """Return all inventory items as XML."""
    with Session() as s:
        items = s.query(InventoryItem).all()
        root  = ET.Element('Inventory')
        for item in items:
            el = ET.SubElement(root, 'Item')
            ET.SubElement(el, 'Code').text     = item.code
            ET.SubElement(el, 'Name').text     = item.name
            ET.SubElement(el, 'Category').text = item.category
            ET.SubElement(el, 'Stock').text    = str(item.stock)
            ET.SubElement(el, 'Price').text    = str(item.price)
        return Response(ET.tostring(root, encoding='unicode'), mimetype='application/xml')


@app.route('/update_inventory', methods=['POST'])
def update_inventory():
    """Deduct stock based on order quantity (called internally by place_order)."""
    root     = ET.fromstring(request.data)
    code     = root.find('ProductCode').text
    quantity = int(root.find('Quantity').text)

    response_el = ET.Element('InventoryResponse')
    with Session() as s:
        item = s.query(InventoryItem).filter_by(code=code).first()
        if item:
            if item.stock >= quantity:
                item.stock -= quantity
                s.commit()
                ET.SubElement(response_el, 'Status').text        = 'Success'
                ET.SubElement(response_el, 'RemainingStock').text = str(item.stock)
                ET.SubElement(response_el, 'Product').text       = item.name
                ET.SubElement(response_el, 'Category').text      = item.category
                ET.SubElement(response_el, 'Price').text         = str(item.price)
            else:
                ET.SubElement(response_el, 'Status').text  = 'Failed'
                ET.SubElement(response_el, 'Message').text = f"Insufficient stock. Available: {item.stock} units"
        else:
            ET.SubElement(response_el, 'Status').text  = 'Failed'
            ET.SubElement(response_el, 'Message').text = 'Product code not found in inventory'

    return Response(ET.tostring(response_el, encoding='unicode'), mimetype='application/xml')


@app.route('/add_item', methods=['POST'])
def add_item():
    """Add a new inventory item."""
    root     = ET.fromstring(request.data)
    code     = root.find('Code').text
    name     = root.find('Name').text
    category = root.find('Category').text
    stock    = int(root.find('Stock').text)
    price    = float(root.find('Price').text)

    response_el = ET.Element('InventoryResponse')
    with Session() as s:
        existing = s.query(InventoryItem).filter_by(code=code).first()
        if existing:
            ET.SubElement(response_el, 'Status').text  = 'Failed'
            ET.SubElement(response_el, 'Message').text = 'Product code already exists'
        else:
            s.add(InventoryItem(code=code, name=name, category=category, stock=stock, price=price))
            s.commit()
            ET.SubElement(response_el, 'Status').text  = 'Success'
            ET.SubElement(response_el, 'Message').text = f"Item '{name}' added successfully"

    return Response(ET.tostring(response_el, encoding='unicode'), mimetype='application/xml')


@app.route('/edit_item', methods=['POST'])
def edit_item():
    """Update an existing inventory item's name, price, or stock."""
    root = ET.fromstring(request.data)
    code = root.find('Code').text

    response_el = ET.Element('InventoryResponse')
    with Session() as s:
        item = s.query(InventoryItem).filter_by(code=code).first()
        if not item:
            ET.SubElement(response_el, 'Status').text  = 'Failed'
            ET.SubElement(response_el, 'Message').text = 'Product code not found'
        else:
            if root.find('Name')  is not None: item.name  = root.find('Name').text
            if root.find('Price') is not None: item.price = float(root.find('Price').text)
            if root.find('Stock') is not None: item.stock = int(root.find('Stock').text)
            s.commit()
            ET.SubElement(response_el, 'Status').text   = 'Success'
            ET.SubElement(response_el, 'Message').text  = f"Item '{item.name}' updated successfully"
            ET.SubElement(response_el, 'Code').text     = item.code
            ET.SubElement(response_el, 'Name').text     = item.name
            ET.SubElement(response_el, 'Price').text    = str(item.price)
            ET.SubElement(response_el, 'Stock').text    = str(item.stock)
            ET.SubElement(response_el, 'Category').text = item.category

    return Response(ET.tostring(response_el, encoding='unicode'), mimetype='application/xml')


@app.route('/delete_item', methods=['POST'])
def delete_item():
    """Delete an inventory item by code."""
    root = ET.fromstring(request.data)
    code = root.find('Code').text

    response_el = ET.Element('InventoryResponse')
    with Session() as s:
        item = s.query(InventoryItem).filter_by(code=code).first()
        if not item:
            ET.SubElement(response_el, 'Status').text  = 'Failed'
            ET.SubElement(response_el, 'Message').text = 'Product code not found'
        else:
            name = item.name
            s.delete(item)
            s.commit()
            ET.SubElement(response_el, 'Status').text  = 'Success'
            ET.SubElement(response_el, 'Message').text = f"Item '{name}' deleted successfully"

    return Response(ET.tostring(response_el, encoding='unicode'), mimetype='application/xml')


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT SERVICE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/process_payment', methods=['POST'])
def process_payment():
    """Process a payment and return a transaction ID."""
    root     = ET.fromstring(request.data)
    amount   = float(root.find('Amount').text)
    product  = root.find('Product').text
    quantity = int(root.find('Quantity').text)

    response_el = ET.Element('PaymentResponse')

    if amount > 0 and quantity > 0:
        txn_id = f"TXN-{abs(hash(f'{product}{amount}')) % 1000000:06d}"
        ET.SubElement(response_el, 'Status').text        = 'Success'
        ET.SubElement(response_el, 'TransactionID').text = txn_id
        ET.SubElement(response_el, 'Amount').text        = f"{amount:.2f}"
        ET.SubElement(response_el, 'Product').text       = product
        ET.SubElement(response_el, 'Quantity').text      = str(quantity)
        ET.SubElement(response_el, 'Message').text       = 'Payment processed successfully'
    else:
        ET.SubElement(response_el, 'Status').text  = 'Failed'
        ET.SubElement(response_el, 'Message').text = 'Invalid payment amount or quantity'

    return Response(ET.tostring(response_el, encoding='unicode'), mimetype='application/xml')


@app.route('/ping', methods=['GET'])
def ping():
    return Response('<status>ok</status>', mimetype='application/xml')


# ═══════════════════════════════════════════════════════════════════════════════
# ORDER SERVICE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

# Internal base URL — routes to the same Flask app
_BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")

@app.route('/place_order', methods=['POST'])
def place_order():
    """
    Full order pipeline:
      1. Reserve inventory  → POST /update_inventory (internal)
      2. Process payment    → POST /process_payment  (internal)
      3. Persist order to DB
    """
    root         = ET.fromstring(request.data)
    product_code = root.find('ProductCode').text
    quantity     = int(root.find('Quantity').text)

    # 1. Reserve inventory
    inv_resp = post_with_retry(f"{_BASE_URL}/update_inventory", data=request.data)
    inv_root = ET.fromstring(inv_resp.content)

    if inv_root.find('Status').text != 'Success':
        return Response(inv_resp.content, mimetype='application/xml')

    product        = inv_root.find('Product').text
    category       = inv_root.find('Category').text
    price_per_unit = float(inv_root.find('Price').text)
    total_amount   = quantity * price_per_unit

    # 2. Process payment
    pay_xml = ET.Element('Payment')
    ET.SubElement(pay_xml, 'Amount').text   = str(total_amount)
    ET.SubElement(pay_xml, 'Product').text  = product
    ET.SubElement(pay_xml, 'Quantity').text = str(quantity)

    pay_resp = post_with_retry(f"{_BASE_URL}/process_payment", data=ET.tostring(pay_xml))
    pay_root = ET.fromstring(pay_resp.content)

    if pay_root.find('Status').text != 'Success':
        return Response(pay_resp.content, mimetype='application/xml')

    transaction_id = pay_root.find('TransactionID').text

    # 3. Save order to DB
    with Session() as s:
        s.add(Order(
            transaction_id = transaction_id,
            timestamp      = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            product_code   = product_code,
            product        = product,
            category       = category,
            quantity       = quantity,
            price_per_unit = price_per_unit,
            total_amount   = total_amount,
            status         = 'Completed'
        ))
        s.commit()

    # 4. Build success response
    final = ET.Element('OrderResponse')
    ET.SubElement(final, 'Status').text         = 'Success'
    ET.SubElement(final, 'TransactionID').text  = transaction_id
    ET.SubElement(final, 'Product').text        = product
    ET.SubElement(final, 'Quantity').text       = str(quantity)
    ET.SubElement(final, 'PricePerUnit').text   = f"{price_per_unit:.2f}"
    ET.SubElement(final, 'TotalAmount').text    = f"{total_amount:.2f}"
    ET.SubElement(final, 'RemainingStock').text = inv_root.find('RemainingStock').text
    ET.SubElement(final, 'Message').text        = 'Order placed and payment processed successfully'

    return Response(ET.tostring(final, encoding='unicode'), mimetype='application/xml')


@app.route('/order_history', methods=['GET'])
def order_history():
    """Return all orders as XML."""
    with Session() as s:
        orders = s.query(Order).all()
        root   = ET.Element('Orders')
        for o in orders:
            el = ET.SubElement(root, 'Order')
            ET.SubElement(el, 'TransactionID').text = o.transaction_id
            ET.SubElement(el, 'Timestamp').text     = o.timestamp
            ET.SubElement(el, 'ProductCode').text   = o.product_code
            ET.SubElement(el, 'Product').text       = o.product
            ET.SubElement(el, 'Category').text      = o.category
            ET.SubElement(el, 'Quantity').text      = str(o.quantity)
            ET.SubElement(el, 'PricePerUnit').text  = f"{o.price_per_unit:.2f}"
            ET.SubElement(el, 'TotalAmount').text   = f"{o.total_amount:.2f}"
            ET.SubElement(el, 'Status').text        = o.status
        return Response(ET.tostring(root, encoding='unicode'), mimetype='application/xml')


@app.route('/update_order', methods=['POST'])
def update_order():
    """Update an order's status or quantity."""
    root   = ET.fromstring(request.data)
    txn_id = root.find('TransactionID').text

    response_el = ET.Element('OrderResponse')
    with Session() as s:
        order = s.query(Order).filter_by(transaction_id=txn_id).first()
        if not order:
            ET.SubElement(response_el, 'Status').text  = 'Failed'
            ET.SubElement(response_el, 'Message').text = 'Transaction not found'
        else:
            if root.find('Status')   is not None: order.status = root.find('Status').text
            if root.find('Quantity') is not None:
                order.quantity     = int(root.find('Quantity').text)
                order.total_amount = order.quantity * order.price_per_unit
            s.commit()
            ET.SubElement(response_el, 'Status').text        = 'Success'
            ET.SubElement(response_el, 'Message').text       = 'Order updated successfully'
            ET.SubElement(response_el, 'TransactionID').text = order.transaction_id
            ET.SubElement(response_el, 'NewStatus').text     = order.status
            ET.SubElement(response_el, 'Quantity').text      = str(order.quantity)
            ET.SubElement(response_el, 'TotalAmount').text   = f"{order.total_amount:.2f}"

    return Response(ET.tostring(response_el, encoding='unicode'), mimetype='application/xml')


@app.route('/delete_order', methods=['POST'])
def delete_order():
    """Delete an order by TransactionID."""
    root   = ET.fromstring(request.data)
    txn_id = root.find('TransactionID').text

    response_el = ET.Element('OrderResponse')
    with Session() as s:
        order = s.query(Order).filter_by(transaction_id=txn_id).first()
        if not order:
            ET.SubElement(response_el, 'Status').text  = 'Failed'
            ET.SubElement(response_el, 'Message').text = 'Transaction not found'
        else:
            s.delete(order)
            s.commit()
            ET.SubElement(response_el, 'Status').text  = 'Success'
            ET.SubElement(response_el, 'Message').text = f"Order {txn_id} deleted successfully"

    return Response(ET.tostring(response_el, encoding='unicode'), mimetype='application/xml')


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
