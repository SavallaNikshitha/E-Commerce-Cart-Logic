"""
E-Commerce Cart Logic API
-------------------------
A Flask + SQLite shopping cart API with product catalogue, cart operations,
quantity validation, stock checks, discounts and order summary.

Install:
    pip install Flask

Run:
    python app.py

Useful endpoints:
    GET    /api/products
    POST   /api/cart/items          {"product_id": 1, "quantity": 2}
    GET    /api/cart
    PATCH  /api/cart/items/<id>     {"quantity": 3}
    DELETE /api/cart/items/<id>
    DELETE /api/cart
    POST   /api/cart/apply-coupon   {"code": "SAVE10"}
"""

from flask import Flask, request, jsonify
import sqlite3
from pathlib import Path

app = Flask(__name__)
DATABASE = Path(__file__).with_name("store.db")

# Sample catalogue. On first run these products are inserted into SQLite.
DEFAULT_PRODUCTS = [
    (1, "Wireless Mouse", "Ergonomic wireless mouse", 599.00, 25),
    (2, "Mechanical Keyboard", "Compact mechanical keyboard", 2499.00, 15),
    (3, "USB-C Hub", "Multi-port USB-C adapter", 1299.00, 20),
    (4, "Laptop Stand", "Adjustable aluminium laptop stand", 999.00, 18),
]

COUPONS = {
    "SAVE10": 10,   # 10 percent off
    "SAVE5": 5
}


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL CHECK(price >= 0),
                stock INTEGER NOT NULL CHECK(stock >= 0)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS cart_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL UNIQUE,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """)
        count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            db.executemany("""
                INSERT INTO products (id, name, description, price, stock)
                VALUES (?, ?, ?, ?, ?)
            """, DEFAULT_PRODUCTS)


def fail(message, status=400):
    return jsonify({"success": False, "message": message}), status


def cart_summary(db, coupon_code=None):
    rows = db.execute("""
        SELECT c.id AS cart_item_id, p.id AS product_id, p.name,
               p.price, p.stock, c.quantity,
               (p.price * c.quantity) AS line_total
        FROM cart_items c
        JOIN products p ON p.id = c.product_id
        ORDER BY c.id
    """).fetchall()

    items = [dict(row) for row in rows]
    subtotal = round(sum(item["line_total"] for item in items), 2)

    discount_percent = COUPONS.get(coupon_code.upper(), 0) if coupon_code else 0
    discount = round(subtotal * discount_percent / 100, 2)
    total = round(subtotal - discount, 2)

    return {
        "items": items,
        "item_count": sum(item["quantity"] for item in items),
        "subtotal": subtotal,
        "coupon": coupon_code.upper() if coupon_code else None,
        "discount_percent": discount_percent,
        "discount": discount,
        "total": total,
        "currency": "INR"
    }


@app.get("/")
def home():
    return jsonify({
        "service": "E-Commerce Cart Logic API",
        "version": "1.0.0",
        "message": "Use the /api endpoints to manage products and the shopping cart."
    })


@app.get("/health")
def health():
    return jsonify({"success": True, "status": "healthy"})


@app.get("/api/products")
def products():
    with get_db() as db:
        rows = db.execute("SELECT * FROM products ORDER BY id").fetchall()
    return jsonify({"success": True, "products": [dict(row) for row in rows]})


@app.get("/api/products/<int:product_id>")
def product_details(product_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        return fail("Product not found.", 404)
    return jsonify({"success": True, "product": dict(row)})


@app.post("/api/cart/items")
def add_to_cart():
    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    quantity = data.get("quantity", 1)

    if not isinstance(product_id, int) or not isinstance(quantity, int) or quantity < 1:
        return fail("product_id and a positive integer quantity are required.")

    with get_db() as db:
        product = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            return fail("Product not found.", 404)

        current = db.execute(
            "SELECT quantity FROM cart_items WHERE product_id=?", (product_id,)
        ).fetchone()
        new_quantity = quantity + (current["quantity"] if current else 0)

        if new_quantity > product["stock"]:
            return fail(f"Only {product['stock']} units are available.")

        db.execute("""
            INSERT INTO cart_items (product_id, quantity) VALUES (?, ?)
            ON CONFLICT(product_id) DO UPDATE SET quantity=excluded.quantity
        """, (product_id, new_quantity))

        summary = cart_summary(db)

    return jsonify({"success": True, "message": "Product added to cart.", "cart": summary}), 201


@app.get("/api/cart")
def view_cart():
    with get_db() as db:
        summary = cart_summary(db)
    return jsonify({"success": True, "cart": summary})


@app.patch("/api/cart/items/<int:item_id>")
def update_cart_item(item_id):
    data = request.get_json(silent=True) or {}
    quantity = data.get("quantity")

    if not isinstance(quantity, int) or quantity < 1:
        return fail("quantity must be a positive integer.")

    with get_db() as db:
        item = db.execute("""
            SELECT c.product_id, p.stock
            FROM cart_items c JOIN products p ON p.id=c.product_id
            WHERE c.id=?
        """, (item_id,)).fetchone()

        if not item:
            return fail("Cart item not found.", 404)
        if quantity > item["stock"]:
            return fail(f"Only {item['stock']} units are available.")

        db.execute("UPDATE cart_items SET quantity=? WHERE id=?", (quantity, item_id))
        summary = cart_summary(db)

    return jsonify({"success": True, "message": "Cart quantity updated.", "cart": summary})


@app.delete("/api/cart/items/<int:item_id>")
def remove_cart_item(item_id):
    with get_db() as db:
        cursor = db.execute("DELETE FROM cart_items WHERE id=?", (item_id,))
        if cursor.rowcount == 0:
            return fail("Cart item not found.", 404)
        summary = cart_summary(db)

    return jsonify({"success": True, "message": "Item removed.", "cart": summary})


@app.delete("/api/cart")
def clear_cart():
    with get_db() as db:
        db.execute("DELETE FROM cart_items")
    return jsonify({"success": True, "message": "Cart cleared."})


@app.post("/api/cart/apply-coupon")
def apply_coupon():
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip().upper()

    if code not in COUPONS:
        return fail("Invalid coupon code.")

    with get_db() as db:
        summary = cart_summary(db, code)

    return jsonify({"success": True, "message": "Coupon applied.", "cart": summary})


initialize_database()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
