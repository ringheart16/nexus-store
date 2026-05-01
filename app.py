from flask import Flask, request, Response, send_from_directory
from flask_cors import CORS
import xml.etree.ElementTree as ET
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float
from sqlalchemy.orm import declarative_base, sessionmaker
import os
import uuid

app = Flask(__name__, static_folder="static")
CORS(app)

# ── Database Setup ───────────────────────────────────────────────────────────
# For Render + Railway MySQL:
# Put your Railway MySQL URL in Render Environment Variables:
# DATABASE_URL=mysql://root:YOUR_PASSWORD@switchyard.proxy.rlwy.net:18132/railway
#
# The code below automatically converts mysql:// to mysql+pymysql://

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)
else:
    # Local fallback for XAMPP
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "3306")
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_NAME = os.environ.get("DB_NAME", "orm_inventory_db")

    DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=280
)

Base = declarative_base()
Session = sessionmaker(bind=engine)


# ── Frontend Route ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Models ───────────────────────────────────────────────────────────────────
class InventoryItem(Base):
    __tablename__ = "inventory"

    code = Column(String(20), primary_key=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    stock = Column(Integer, nullable=False, default=0)
    price = Column(Float, nullable=False, default=0)


class Order(Base):
    __tablename__ = "orders"

    transaction_id = Column(String(20), primary_key=True)
    timestamp = Column(String(30))
    product_code = Column(String(20))
    product = Column(String(100))
    category = Column(String(50))
    quantity = Column(Integer)
    price_per_unit = Column(Float)
    total_amount = Column(Float)
    status = Column(String(20))


# Automatically creates tables if they do not exist yet.
Base.metadata.create_all(engine)


# ── Helpers ──────────────────────────────────────────────────────────────────
def xml_response(element):
    return Response(
        ET.tostring(element, encoding="unicode"),
        mimetype="application/xml"
    )


def error_response(root_name, message):
    root = ET.Element(root_name)
    ET.SubElement(root, "Status").text = "Failed"
    ET.SubElement(root, "Message").text = message
    return xml_response(root)


def get_text(root, tag, required=True, default=None):
    element = root.find(tag)

    if element is None or element.text is None or element.text.strip() == "":
        if required:
            raise ValueError(f"{tag} is required")
        return default

    return element.text.strip()


def generate_transaction_id():
    return f"TXN-{uuid.uuid4().hex[:12].upper()}"


# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY SERVICE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/inventory", methods=["GET"])
def get_inventory():
    """Return all inventory items as XML."""
    try:
        with Session() as session:
            items = session.query(InventoryItem).all()

            root = ET.Element("Inventory")

            for item in items:
                item_el = ET.SubElement(root, "Item")
                ET.SubElement(item_el, "Code").text = item.code
                ET.SubElement(item_el, "Name").text = item.name
                ET.SubElement(item_el, "Category").text = item.category
                ET.SubElement(item_el, "Stock").text = str(item.stock)
                ET.SubElement(item_el, "Price").text = f"{item.price:.2f}"

            return xml_response(root)

    except Exception as e:
        return error_response("InventoryResponse", str(e))


@app.route("/add_item", methods=["POST"])
def add_item():
    """Add a new inventory item."""
    try:
        root = ET.fromstring(request.data)

        code = get_text(root, "Code")
        name = get_text(root, "Name")
        category = get_text(root, "Category")
        stock = int(get_text(root, "Stock"))
        price = float(get_text(root, "Price"))

        if stock < 0:
            return error_response("InventoryResponse", "Stock cannot be negative")

        if price < 0:
            return error_response("InventoryResponse", "Price cannot be negative")

        response_el = ET.Element("InventoryResponse")

        with Session() as session:
            existing_item = session.query(InventoryItem).filter_by(code=code).first()

            if existing_item:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = "Product code already exists"
            else:
                new_item = InventoryItem(
                    code=code,
                    name=name,
                    category=category,
                    stock=stock,
                    price=price
                )

                session.add(new_item)
                session.commit()

                ET.SubElement(response_el, "Status").text = "Success"
                ET.SubElement(response_el, "Message").text = f"Item '{name}' added successfully"

        return xml_response(response_el)

    except Exception as e:
        return error_response("InventoryResponse", str(e))


@app.route("/edit_item", methods=["POST"])
def edit_item():
    """Update an existing inventory item's name, category, price, or stock."""
    try:
        root = ET.fromstring(request.data)
        code = get_text(root, "Code")

        response_el = ET.Element("InventoryResponse")

        with Session() as session:
            item = session.query(InventoryItem).filter_by(code=code).first()

            if not item:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = "Product code not found"
            else:
                name = get_text(root, "Name", required=False)
                category = get_text(root, "Category", required=False)
                stock = get_text(root, "Stock", required=False)
                price = get_text(root, "Price", required=False)

                if name is not None:
                    item.name = name

                if category is not None:
                    item.category = category

                if stock is not None:
                    stock_value = int(stock)
                    if stock_value < 0:
                        return error_response("InventoryResponse", "Stock cannot be negative")
                    item.stock = stock_value

                if price is not None:
                    price_value = float(price)
                    if price_value < 0:
                        return error_response("InventoryResponse", "Price cannot be negative")
                    item.price = price_value

                session.commit()

                ET.SubElement(response_el, "Status").text = "Success"
                ET.SubElement(response_el, "Message").text = f"Item '{item.name}' updated successfully"
                ET.SubElement(response_el, "Code").text = item.code
                ET.SubElement(response_el, "Name").text = item.name
                ET.SubElement(response_el, "Category").text = item.category
                ET.SubElement(response_el, "Stock").text = str(item.stock)
                ET.SubElement(response_el, "Price").text = f"{item.price:.2f}"

        return xml_response(response_el)

    except Exception as e:
        return error_response("InventoryResponse", str(e))


@app.route("/delete_item", methods=["POST"])
def delete_item():
    """Delete an inventory item by product code."""
    try:
        root = ET.fromstring(request.data)
        code = get_text(root, "Code")

        response_el = ET.Element("InventoryResponse")

        with Session() as session:
            item = session.query(InventoryItem).filter_by(code=code).first()

            if not item:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = "Product code not found"
            else:
                item_name = item.name
                session.delete(item)
                session.commit()

                ET.SubElement(response_el, "Status").text = "Success"
                ET.SubElement(response_el, "Message").text = f"Item '{item_name}' deleted successfully"

        return xml_response(response_el)

    except Exception as e:
        return error_response("InventoryResponse", str(e))


@app.route("/update_inventory", methods=["POST"])
def update_inventory():
    """Deduct stock based on order quantity."""
    try:
        root = ET.fromstring(request.data)

        code = get_text(root, "ProductCode")
        quantity = int(get_text(root, "Quantity"))

        response_el = ET.Element("InventoryResponse")

        with Session() as session:
            item = session.query(InventoryItem).filter_by(code=code).first()

            if not item:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = "Product code not found in inventory"
            elif quantity <= 0:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = "Quantity must be greater than zero"
            elif item.stock < quantity:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = f"Insufficient stock. Available: {item.stock} units"
            else:
                item.stock -= quantity
                session.commit()

                ET.SubElement(response_el, "Status").text = "Success"
                ET.SubElement(response_el, "RemainingStock").text = str(item.stock)
                ET.SubElement(response_el, "Product").text = item.name
                ET.SubElement(response_el, "Category").text = item.category
                ET.SubElement(response_el, "Price").text = f"{item.price:.2f}"

        return xml_response(response_el)

    except Exception as e:
        return error_response("InventoryResponse", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT SERVICE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/process_payment", methods=["POST"])
def process_payment():
    """Process a payment and return a transaction ID."""
    try:
        root = ET.fromstring(request.data)

        amount = float(get_text(root, "Amount"))
        product = get_text(root, "Product")
        quantity = int(get_text(root, "Quantity"))

        response_el = ET.Element("PaymentResponse")

        if amount > 0 and quantity > 0:
            transaction_id = generate_transaction_id()

            ET.SubElement(response_el, "Status").text = "Success"
            ET.SubElement(response_el, "TransactionID").text = transaction_id
            ET.SubElement(response_el, "Amount").text = f"{amount:.2f}"
            ET.SubElement(response_el, "Product").text = product
            ET.SubElement(response_el, "Quantity").text = str(quantity)
            ET.SubElement(response_el, "Message").text = "Payment processed successfully"
        else:
            ET.SubElement(response_el, "Status").text = "Failed"
            ET.SubElement(response_el, "Message").text = "Invalid payment amount or quantity"

        return xml_response(response_el)

    except Exception as e:
        return error_response("PaymentResponse", str(e))


@app.route("/ping", methods=["GET"])
def ping():
    root = ET.Element("status")
    root.text = "ok"
    return xml_response(root)


# ══════════════════════════════════════════════════════════════════════════════
# ORDER SERVICE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/place_order", methods=["POST"])
def place_order():
    """
    Full order pipeline without localhost/internal HTTP request:
    1. Find product from database
    2. Check and deduct stock
    3. Generate payment transaction
    4. Save order using ORM
    """
    try:
        root = ET.fromstring(request.data)

        product_code = get_text(root, "ProductCode")
        quantity = int(get_text(root, "Quantity"))

        if quantity <= 0:
            return error_response("OrderResponse", "Quantity must be greater than zero")

        response_el = ET.Element("OrderResponse")

        with Session() as session:
            item = session.query(InventoryItem).filter_by(code=product_code).first()

            if not item:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = "Product code not found in inventory"
                return xml_response(response_el)

            if item.stock < quantity:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = f"Insufficient stock. Available: {item.stock} units"
                return xml_response(response_el)

            product = item.name
            category = item.category
            price_per_unit = item.price
            total_amount = quantity * price_per_unit
            transaction_id = generate_transaction_id()

            # Deduct inventory stock
            item.stock -= quantity
            remaining_stock = item.stock

            # Save order
            new_order = Order(
                transaction_id=transaction_id,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                product_code=product_code,
                product=product,
                category=category,
                quantity=quantity,
                price_per_unit=price_per_unit,
                total_amount=total_amount,
                status="Completed"
            )

            session.add(new_order)
            session.commit()

            ET.SubElement(response_el, "Status").text = "Success"
            ET.SubElement(response_el, "TransactionID").text = transaction_id
            ET.SubElement(response_el, "ProductCode").text = product_code
            ET.SubElement(response_el, "Product").text = product
            ET.SubElement(response_el, "Category").text = category
            ET.SubElement(response_el, "Quantity").text = str(quantity)
            ET.SubElement(response_el, "PricePerUnit").text = f"{price_per_unit:.2f}"
            ET.SubElement(response_el, "TotalAmount").text = f"{total_amount:.2f}"
            ET.SubElement(response_el, "RemainingStock").text = str(remaining_stock)
            ET.SubElement(response_el, "Message").text = "Order placed and payment processed successfully"

        return xml_response(response_el)

    except Exception as e:
        return error_response("OrderResponse", str(e))


@app.route("/order_history", methods=["GET"])
def order_history():
    """Return all orders as XML."""
    try:
        with Session() as session:
            orders = session.query(Order).all()

            root = ET.Element("Orders")

            for order in orders:
                order_el = ET.SubElement(root, "Order")
                ET.SubElement(order_el, "TransactionID").text = order.transaction_id
                ET.SubElement(order_el, "Timestamp").text = order.timestamp
                ET.SubElement(order_el, "ProductCode").text = order.product_code
                ET.SubElement(order_el, "Product").text = order.product
                ET.SubElement(order_el, "Category").text = order.category
                ET.SubElement(order_el, "Quantity").text = str(order.quantity)
                ET.SubElement(order_el, "PricePerUnit").text = f"{order.price_per_unit:.2f}"
                ET.SubElement(order_el, "TotalAmount").text = f"{order.total_amount:.2f}"
                ET.SubElement(order_el, "Status").text = order.status

            return xml_response(root)

    except Exception as e:
        return error_response("OrderResponse", str(e))


@app.route("/update_order", methods=["POST"])
def update_order():
    """Update an order's status or quantity."""
    try:
        root = ET.fromstring(request.data)

        transaction_id = get_text(root, "TransactionID")

        response_el = ET.Element("OrderResponse")

        with Session() as session:
            order = session.query(Order).filter_by(transaction_id=transaction_id).first()

            if not order:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = "Transaction not found"
            else:
                status = get_text(root, "Status", required=False)
                quantity = get_text(root, "Quantity", required=False)

                if status is not None:
                    order.status = status

                if quantity is not None:
                    quantity_value = int(quantity)

                    if quantity_value <= 0:
                        return error_response("OrderResponse", "Quantity must be greater than zero")

                    order.quantity = quantity_value
                    order.total_amount = order.quantity * order.price_per_unit

                session.commit()

                ET.SubElement(response_el, "Status").text = "Success"
                ET.SubElement(response_el, "Message").text = "Order updated successfully"
                ET.SubElement(response_el, "TransactionID").text = order.transaction_id
                ET.SubElement(response_el, "NewStatus").text = order.status
                ET.SubElement(response_el, "Quantity").text = str(order.quantity)
                ET.SubElement(response_el, "TotalAmount").text = f"{order.total_amount:.2f}"

        return xml_response(response_el)

    except Exception as e:
        return error_response("OrderResponse", str(e))


@app.route("/delete_order", methods=["POST"])
def delete_order():
    """Delete an order by transaction ID."""
    try:
        root = ET.fromstring(request.data)

        transaction_id = get_text(root, "TransactionID")

        response_el = ET.Element("OrderResponse")

        with Session() as session:
            order = session.query(Order).filter_by(transaction_id=transaction_id).first()

            if not order:
                ET.SubElement(response_el, "Status").text = "Failed"
                ET.SubElement(response_el, "Message").text = "Transaction not found"
            else:
                session.delete(order)
                session.commit()

                ET.SubElement(response_el, "Status").text = "Success"
                ET.SubElement(response_el, "Message").text = f"Order {transaction_id} deleted successfully"

        return xml_response(response_el)

    except Exception as e:
        return error_response("OrderResponse", str(e))


# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)