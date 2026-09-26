import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from config import DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS numbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL UNIQUE,
                price_stars INTEGER NOT NULL CHECK(price_stars > 0),
                status TEXT NOT NULL DEFAULT 'available'
                    CHECK(status IN ('available', 'sold')),
                owner_id INTEGER,
                purchased_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                number_id INTEGER NOT NULL,
                amount_stars INTEGER NOT NULL CHECK(amount_stars > 0),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'paid', 'refunded', 'cancelled')),
                telegram_payment_id TEXT UNIQUE,
                created_at TEXT NOT NULL,
                paid_at TEXT,
                FOREIGN KEY(number_id) REFERENCES numbers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_numbers_status
                ON numbers(status);
            CREATE INDEX IF NOT EXISTS idx_numbers_owner
                ON numbers(owner_id);
            CREATE INDEX IF NOT EXISTS idx_orders_user
                ON orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status
                ON orders(status);
            """
        )


def upsert_user(telegram_id: int, username: Optional[str], first_name: Optional[str]) -> None:
    with get_db() as db:
        db.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
            """,
            (telegram_id, username, first_name, utc_now()),
        )


def get_available_numbers(limit: int = 10, offset: int = 0):
    with get_db() as db:
        return db.execute(
            """
            SELECT * FROM numbers
            WHERE status = 'available'
            ORDER BY id ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()


def count_available_numbers() -> int:
    with get_db() as db:
        return int(db.execute(
            "SELECT COUNT(*) AS c FROM numbers WHERE status='available'"
        ).fetchone()["c"])


def get_number(number_id: int):
    with get_db() as db:
        return db.execute(
            "SELECT * FROM numbers WHERE id = ?", (number_id,)
        ).fetchone()


def add_number(phone_number: str, price_stars: int) -> int:
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO numbers (phone_number, price_stars, status, owner_id, created_at)
            VALUES (?, ?, 'available', NULL, ?)
            """,
            (phone_number, price_stars, utc_now()),
        )
        return int(cur.lastrowid)


def delete_number(number_id: int) -> bool:
    with get_db() as db:
        row = db.execute(
            "SELECT status FROM numbers WHERE id = ?", (number_id,)
        ).fetchone()
        if not row:
            return False
        if row["status"] != "available":
            return False
        db.execute("DELETE FROM numbers WHERE id = ?", (number_id,))
        return True


def get_all_numbers(limit: int = 10, offset: int = 0):
    with get_db() as db:
        return db.execute(
            """
            SELECT n.*, u.username AS owner_username
            FROM numbers n
            LEFT JOIN users u ON u.telegram_id = n.owner_id
            ORDER BY n.id ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()


def count_numbers() -> int:
    with get_db() as db:
        return int(db.execute("SELECT COUNT(*) AS c FROM numbers").fetchone()["c"])


def get_sold_numbers(limit: int = 10, offset: int = 0):
    with get_db() as db:
        return db.execute(
            """
            SELECT n.*, u.username AS owner_username
            FROM numbers n
            LEFT JOIN users u ON u.telegram_id = n.owner_id
            WHERE n.status = 'sold'
            ORDER BY n.purchased_at DESC, n.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()


def count_sold_numbers() -> int:
    with get_db() as db:
        return int(db.execute(
            "SELECT COUNT(*) AS c FROM numbers WHERE status='sold'"
        ).fetchone()["c"])


def create_pending_order(user_id: int, number_id: int, amount_stars: int) -> int:
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO orders
                (user_id, number_id, amount_stars, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (user_id, number_id, amount_stars, utc_now()),
        )
        return int(cur.lastrowid)


def get_order(order_id: int):
    with get_db() as db:
        return db.execute(
            """
            SELECT o.*, n.phone_number, n.status AS number_status,
                   n.owner_id, n.price_stars
            FROM orders o
            JOIN numbers n ON n.id = o.number_id
            WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()


def mark_order_cancelled(order_id: int) -> None:
    with get_db() as db:
        db.execute(
            """
            UPDATE orders
            SET status='cancelled'
            WHERE id=? AND status='pending'
            """,
            (order_id,),
        )


def finalize_successful_payment(
    order_id: int,
    user_id: int,
    number_id: int,
    amount_stars: int,
    telegram_payment_id: str,
) -> tuple[bool, str]:
    """
    Atomically handles a successful payment.

    Returns:
      (True, "paid") when this payment completed the order.
      (False, "duplicate") when this payment charge was already processed.
      (False, "unavailable") when the number is no longer available.
      (False, "invalid") when the payload/order does not match.
    """
    with get_db() as db:
        existing = db.execute(
            """
            SELECT id, status FROM orders
            WHERE telegram_payment_id = ?
            """,
            (telegram_payment_id,),
        ).fetchone()
        if existing:
            return False, "duplicate"

        order = db.execute(
            """
            SELECT id, user_id, number_id, amount_stars, status
            FROM orders
            WHERE id = ?
            """,
            (order_id,),
        ).fetchone()

        if not order:
            return False, "invalid"

        if (
            order["user_id"] != user_id
            or order["number_id"] != number_id
            or order["amount_stars"] != amount_stars
        ):
            return False, "invalid"

        if order["status"] == "paid":
            return False, "duplicate"

        number = db.execute(
            """
            SELECT id, status, price_stars
            FROM numbers
            WHERE id = ?
            """,
            (number_id,),
        ).fetchone()

        if not number or number["status"] != "available":
            return False, "unavailable"

        now = utc_now()

        # The WHERE clause makes the sale itself atomic.
        updated = db.execute(
            """
            UPDATE numbers
            SET status='sold', owner_id=?, purchased_at=?
            WHERE id=? AND status='available'
            """,
            (user_id, now, number_id),
        ).rowcount

        if updated != 1:
            return False, "unavailable"

        db.execute(
            """
            UPDATE orders
            SET status='paid',
                telegram_payment_id=?,
                paid_at=?
            WHERE id=? AND status='pending'
            """,
            (telegram_payment_id, now, order_id),
        )
        return True, "paid"


def mark_order_refunded(order_id: int, telegram_payment_id: str) -> None:
    with get_db() as db:
        db.execute(
            """
            UPDATE orders
            SET status='refunded', telegram_payment_id=?
            WHERE id=? AND status='pending'
            """,
            (telegram_payment_id, order_id),
        )


def get_user_numbers(telegram_id: int):
    with get_db() as db:
        return db.execute(
            """
            SELECT * FROM numbers
            WHERE owner_id=? AND status='sold'
            ORDER BY purchased_at DESC, id DESC
            """,
            (telegram_id,),
        ).fetchall()


def get_user_orders(telegram_id: int, limit: int = 50):
    with get_db() as db:
        return db.execute(
            """
            SELECT o.*, n.phone_number
            FROM orders o
            JOIN numbers n ON n.id=o.number_id
            WHERE o.user_id=?
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        ).fetchall()


def get_recent_paid_orders(limit: int = 20):
    with get_db() as db:
        return db.execute(
            """
            SELECT o.*, n.phone_number
            FROM orders o
            JOIN numbers n ON n.id=o.number_id
            WHERE o.status='paid'
            ORDER BY o.paid_at DESC, o.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_stats() -> dict[str, int]:
    with get_db() as db:
        total_numbers = db.execute(
            "SELECT COUNT(*) AS c FROM numbers"
        ).fetchone()["c"]
        available = db.execute(
            "SELECT COUNT(*) AS c FROM numbers WHERE status='available'"
        ).fetchone()["c"]
        sold = db.execute(
            "SELECT COUNT(*) AS c FROM numbers WHERE status='sold'"
        ).fetchone()["c"]
        orders = db.execute(
            "SELECT COUNT(*) AS c FROM orders"
        ).fetchone()["c"]
        stars = db.execute(
            "SELECT COALESCE(SUM(amount_stars),0) AS s FROM orders WHERE status='paid'"
        ).fetchone()["s"]
        paid_orders = db.execute(
            "SELECT COUNT(*) AS c FROM orders WHERE status='paid'"
        ).fetchone()["c"]

        return {
            "total_numbers": int(total_numbers),
            "available": int(available),
            "sold": int(sold),
            "orders": int(orders),
            "stars": int(stars),
            "paid_orders": int(paid_orders),
        }


def export_backup() -> dict[str, Any]:
    with get_db() as db:
        users = [dict(r) for r in db.execute(
            "SELECT * FROM users ORDER BY id"
        ).fetchall()]
        numbers = [dict(r) for r in db.execute(
            "SELECT * FROM numbers ORDER BY id"
        ).fetchall()]
        orders = [dict(r) for r in db.execute(
            "SELECT * FROM orders ORDER BY id"
        ).fetchall()]

    return {
        "schema_version": 1,
        "exported_at": utc_now(),
        "users": users,
        "numbers": numbers,
        "orders": orders,
    }


def validate_backup(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Backup root must be a JSON object."

    if data.get("schema_version") != 1:
        return False, "Unsupported or missing schema_version."

    for key in ("users", "numbers", "orders"):
        if not isinstance(data.get(key), list):
            return False, f"'{key}' must be a list."

    user_keys = {"id", "telegram_id", "username", "first_name", "created_at"}
    number_keys = {
        "id", "phone_number", "price_stars", "status",
        "owner_id", "purchased_at", "created_at"
    }
    order_keys = {
        "id", "user_id", "number_id", "amount_stars",
        "status", "telegram_payment_id", "created_at", "paid_at"
    }

    for row in data["users"]:
        if not isinstance(row, dict) or not user_keys.issubset(row):
            return False, "Invalid users row."

    for row in data["numbers"]:
        if not isinstance(row, dict) or not number_keys.issubset(row):
            return False, "Invalid numbers row."
        if row["status"] not in ("available", "sold"):
            return False, "Invalid number status."
        if int(row["price_stars"]) <= 0:
            return False, "Invalid Stars price."

    for row in data["orders"]:
        if not isinstance(row, dict) or not order_keys.issubset(row):
            return False, "Invalid orders row."
        if row["status"] not in ("pending", "paid", "refunded", "cancelled"):
            return False, "Invalid order status."
        if int(row["amount_stars"]) <= 0:
            return False, "Invalid order amount."

    return True, "OK"


def restore_backup(data: dict[str, Any]) -> None:
    ok, reason = validate_backup(data)
    if not ok:
        raise ValueError(reason)

    # Extra integrity checks before changing the live database.
    phone_numbers = [row["phone_number"] for row in data["numbers"]]
    if len(phone_numbers) != len(set(phone_numbers)):
        raise ValueError("Backup contains duplicate phone numbers.")

    user_ids = {row["telegram_id"] for row in data["users"]}
    number_ids = {row["id"] for row in data["numbers"]}

    for n in data["numbers"]:
        if n["owner_id"] is not None and n["owner_id"] not in user_ids:
            raise ValueError("A number references a missing owner.")

    for o in data["orders"]:
        if o["user_id"] not in user_ids:
            raise ValueError("An order references a missing user.")
        if o["number_id"] not in number_ids:
            raise ValueError("An order references a missing number.")

    with get_db() as db:
        db.execute("DELETE FROM orders")
        db.execute("DELETE FROM numbers")
        db.execute("DELETE FROM users")

        for row in data["users"]:
            db.execute(
                """
                INSERT INTO users
                    (id, telegram_id, username, first_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["telegram_id"], row["username"],
                    row["first_name"], row["created_at"]
                ),
            )

        for row in data["numbers"]:
            db.execute(
                """
                INSERT INTO numbers
                    (id, phone_number, price_stars, status, owner_id,
                     purchased_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["phone_number"], int(row["price_stars"]),
                    row["status"], row["owner_id"], row["purchased_at"],
                    row["created_at"]
                ),
            )

        for row in data["orders"]:
            db.execute(
                """
                INSERT INTO orders
                    (id, user_id, number_id, amount_stars, status,
                     telegram_payment_id, created_at, paid_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["user_id"], row["number_id"],
                    int(row["amount_stars"]), row["status"],
                    row["telegram_payment_id"], row["created_at"],
                    row["paid_at"]
                ),
            )

        # Keep AUTOINCREMENT sequences above restored IDs.
        db.execute(
            """
            DELETE FROM sqlite_sequence
            WHERE name IN ('users', 'numbers', 'orders')
            """
        )
        db.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES('users', COALESCE((SELECT MAX(id) FROM users),0))"
        )
        db.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES('numbers', COALESCE((SELECT MAX(id) FROM numbers),0))"
        )
        db.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES('orders', COALESCE((SELECT MAX(id) FROM orders),0))"
        )
