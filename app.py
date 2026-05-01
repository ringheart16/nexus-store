from flask import Flask, request, Response, send_from_directory
from flask_cors import CORS
import xml.etree.ElementTree as ET
import requests
import time
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float
from sqlalchemy.orm import declarative_base, sessionmaker
import os

app = Flask(__name__, static_folder="static")
CORS(app)

# ── Database Setup for XAMPP MySQL ───────────────────────────────────────────
# XAMPP default:
# DB_HOST = localhost
# DB_PORT = 3306
# DB_USER = root
# DB_PASSWORD = empty
# DB_NAME = orm_inventory_db


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


# This creates tables automatically if they do not exist yet.
# Still recommended to create database first in phpMyAdmin.
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


def post_with_retry(url, data, retries=3, timeout=15):
    for attempt in range(retries):
        try:
            response = requests.post(
                url,
                data=data,
                headers={"Content-Type": "application/xml"},
                timeout=timeout
            )
            return response
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                raise


# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY SERVICE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/inventory", methods=["GET"])
def get_inventory():
    """Return all inventory items as XML."""
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
                    item.stock = int(stock)

                if price is not None:
                    item.price = float(price)

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
            unique_value = f"{product}{amount}{quantity}{datetime.now().timestamp()}"
            transaction_id = f"TXN-{abs(hash(unique_value)) % 1000000:06d}"

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

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")


@app.route("/place_order", methods=["POST"])
def place_order():
    """
    Full order pipeline:
    1. Deduct stock using /update_inventory
    2. Process payment using /process_payment
    3. Save order using ORM
    """
    try:
        root = ET.fromstring(request.data)

        product_code = get_text(root, "ProductCode")
        quantity = int(get_text(root, "Quantity"))

        if quantity <= 0:
            return error_response("OrderResponse", "Quantity must be greater than zero")

        # 1. Deduct inventory
        inventory_response = post_with_retry(
            f"{BASE_URL}/update_inventory",
            data=request.data
        )

        inventory_root = ET.fromstring(inventory_response.content)

        if inventory_root.find("Status").text != "Success":
            return Response(inventory_response.content, mimetype="application/xml")

        product = inventory_root.find("Product").text
        category = inventory_root.find("Category").text
        price_per_unit = float(inventory_root.find("Price").text)
        total_amount = quantity * price_per_unit

        # 2. Process payment
        payment_xml = ET.Element("Payment")
        ET.SubElement(payment_xml, "Amount").text = str(total_amount)
        ET.SubElement(payment_xml, "Product").text = product
        ET.SubElement(payment_xml, "Quantity").text = str(quantity)

        payment_response = post_with_retry(
            f"{BASE_URL}/process_payment",
            data=ET.tostring(payment_xml)
        )

        payment_root = ET.fromstring(payment_response.content)

        if payment_root.find("Status").text != "Success":
            return Response(payment_response.content, mimetype="application/xml")

        transaction_id = payment_root.find("TransactionID").text

        # 3. Save order to database using ORM
        with Session() as session:
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

        # 4. Final response
        final_response = ET.Element("OrderResponse")
        ET.SubElement(final_response, "Status").text = "Success"
        ET.SubElement(final_response, "TransactionID").text = transaction_id
        ET.SubElement(final_response, "ProductCode").text = product_code
        ET.SubElement(final_response, "Product").text = product
        ET.SubElement(final_response, "Category").text = category
        ET.SubElement(final_response, "Quantity").text = str(quantity)
        ET.SubElement(final_response, "PricePerUnit").text = f"{price_per_unit:.2f}"
        ET.SubElement(final_response, "TotalAmount").text = f"{total_amount:.2f}"
        ET.SubElement(final_response, "RemainingStock").text = inventory_root.find("RemainingStock").text
        ET.SubElement(final_response, "Message").text = "Order placed and payment processed successfully"

        return xml_response(final_response)

    except Exception as e:
        return error_response("OrderResponse", str(e))


@app.route("/order_history", methods=["GET"])
def order_history():
    """Return all orders as XML."""
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
                    order.quantity = int(quantity)
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
    app.run(host="0.0.0.0", port=port, debug=True)