"""Create deterministic commerce sample data, insert it into MySQL, and verify the seeded business totals."""

import random
import sys
from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import mysql.connector
from faker import Faker
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


SEED = 20261017
BATCH_SIZE = 500
CATEGORY_NAMES = (
    "Electronics",
    "Home & Kitchen",
    "Clothing",
    "Beauty & Personal Care",
    "Sports & Outdoors",
    "Books & Media",
    "Toys & Games",
    "Food & Beverage",
)
REGIONS = ("Northeast", "Southeast", "Midwest", "Southwest", "West")
SALES_CHANNELS = ("online", "in_store", "marketplace", "mobile")
PAYMENT_METHODS = ("credit_card", "debit_card", "digital_wallet", "bank_transfer")
END_DATE = datetime(2025, 12, 31, 23, 59, 59)
ORDER_YEARS = range(2022, 2026)
TABLE_ORDER = (
    "categories",
    "products",
    "customers",
    "orders",
    "order_items",
    "payments",
    "refunds",
)

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS categories (
        category_id BIGINT PRIMARY KEY AUTO_INCREMENT,
        category_name VARCHAR(100) NOT NULL,
        UNIQUE KEY uq_category_name (category_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS customers (
        customer_id BIGINT PRIMARY KEY AUTO_INCREMENT,
        customer_name VARCHAR(150) NOT NULL,
        email VARCHAR(255),
        city VARCHAR(100),
        state VARCHAR(100),
        region VARCHAR(50),
        signup_date DATE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_customers_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        product_id BIGINT PRIMARY KEY AUTO_INCREMENT,
        product_name VARCHAR(200) NOT NULL,
        category_id BIGINT NOT NULL,
        unit_price DECIMAL(12, 2) NOT NULL,
        cost_price DECIMAL(12, 2) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id BIGINT PRIMARY KEY AUTO_INCREMENT,
        customer_id BIGINT NOT NULL,
        order_date DATETIME NOT NULL,
        order_status VARCHAR(30) NOT NULL,
        sales_channel VARCHAR(30) NOT NULL,
        shipping_amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
        discount_amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
        INDEX idx_orders_date (order_date),
        INDEX idx_orders_customer (customer_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS order_items (
        order_item_id BIGINT PRIMARY KEY AUTO_INCREMENT,
        order_id BIGINT NOT NULL,
        product_id BIGINT NOT NULL,
        quantity INT NOT NULL,
        unit_price DECIMAL(12, 2) NOT NULL,
        discount_amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id),
        INDEX idx_items_order (order_id),
        INDEX idx_items_product (product_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
        payment_id BIGINT PRIMARY KEY AUTO_INCREMENT,
        order_id BIGINT NOT NULL,
        payment_date DATETIME NOT NULL,
        payment_method VARCHAR(30) NOT NULL,
        payment_status VARCHAR(30) NOT NULL,
        amount DECIMAL(12, 2) NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        INDEX idx_payments_order (order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS refunds (
        refund_id BIGINT PRIMARY KEY AUTO_INCREMENT,
        order_id BIGINT NOT NULL,
        order_item_id BIGINT,
        refund_date DATETIME NOT NULL,
        refund_amount DECIMAL(12, 2) NOT NULL,
        refund_reason VARCHAR(255),
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (order_item_id) REFERENCES order_items(order_item_id),
        INDEX idx_refunds_order (order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
)

INSERT_STATEMENTS = {
    "categories": "INSERT INTO categories (category_id, category_name) VALUES (%s, %s)",
    "products": """
        INSERT INTO products (
            product_id, product_name, category_id, unit_price, cost_price,
            is_active
        ) VALUES (%s, %s, %s, %s, %s, %s)
    """,
    "customers": """
        INSERT INTO customers (
            customer_id, customer_name, email, city, state, region, signup_date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    """,
    "orders": """
        INSERT INTO orders (
            order_id, customer_id, order_date, order_status, sales_channel,
            shipping_amount, discount_amount
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    """,
    "order_items": """
        INSERT INTO order_items (
            order_item_id, order_id, product_id, quantity, unit_price,
            discount_amount
        ) VALUES (%s, %s, %s, %s, %s, %s)
    """,
    "payments": """
        INSERT INTO payments (
            payment_id, order_id, payment_date, payment_method,
            payment_status, amount
        ) VALUES (%s, %s, %s, %s, %s, %s)
    """,
    "refunds": """
        INSERT INTO refunds (
            refund_id, order_id, order_item_id, refund_date, refund_amount,
            refund_reason
        ) VALUES (%s, %s, %s, %s, %s, %s)
    """,
}


class DatabaseSettings(BaseSettings):
    """Validated settings used to establish and bound database connections."""
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(validation_alias="DB_HOST")
    port: int = Field(default=3306, validation_alias="DB_PORT")
    user: str = Field(validation_alias="DB_USER")
    password: str = Field(default="", validation_alias="DB_PASSWORD")
    database: str = Field(validation_alias="DB_NAME")


def as_money(cents: int) -> Decimal:
    """Quantize a numeric value and return a currency-safe decimal."""
    return Decimal(cents) / Decimal(100)


def build_seed_data() -> dict[str, list[tuple[object, ...]]]:
    """Generate and return deterministic rows for all sample commerce tables."""
    rng = random.Random(SEED)
    fake = Faker("en_US")
    fake.seed_instance(SEED)

    rows: dict[str, list[tuple[object, ...]]] = {
        table: [] for table in TABLE_ORDER
    }
    for category_id, name in enumerate(CATEGORY_NAMES, start=1):
        rows["categories"].append((category_id, name))

    product_prices: dict[int, int] = {}
    for product_id in range(1, 101):
        price_cents = rng.randint(499, 49999)
        product_prices[product_id] = price_cents
        rows["products"].append(
            (
                product_id,
                fake.unique.catch_phrase(),
                (product_id - 1) % len(CATEGORY_NAMES) + 1,
                as_money(price_cents),
                as_money(rng.randint(100, price_cents - 1)),
                rng.random() < 0.95,
            )
        )

    for customer_id in range(1, 501):
        rows["customers"].append(
            (
                customer_id,
                fake.name(),
                fake.unique.email(),
                fake.city(),
                fake.state(),
                REGIONS[(customer_id - 1) % len(REGIONS)],
                fake.date_between(
                    start_date=datetime(2020, 1, 1).date(),
                    end_date=END_DATE.date(),
                ),
            )
        )

    successful_order_ids: list[int] = []
    order_refund_items: dict[int, list[tuple[int, int]]] = {}
    item_id = 1
    for order_id in range(1, 5001):
        order_year = 2022 + (order_id - 1) % len(ORDER_YEARS)
        order_date = fake.date_time_between(
            start_date=datetime(order_year, 1, 1),
            end_date=datetime(order_year, 12, 31, 23, 59, 59),
        )
        selected_products = rng.sample(range(1, 101), rng.randint(1, 5))
        subtotal_cents = 0
        for product_id in selected_products:
            quantity = rng.randint(1, 4)
            price_cents = product_prices[product_id]
            line_subtotal_cents = quantity * price_cents
            line_discount_cents = rng.randint(0, line_subtotal_cents // 20)
            net_item_cents = line_subtotal_cents - line_discount_cents
            subtotal_cents += net_item_cents
            rows["order_items"].append(
                (
                    item_id,
                    order_id,
                    product_id,
                    quantity,
                    as_money(price_cents),
                    as_money(line_discount_cents),
                )
            )
            order_refund_items.setdefault(order_id, []).append(
                (item_id, net_item_cents)
            )
            item_id += 1

        payment_succeeded = rng.random() < 0.92
        if payment_succeeded:
            successful_order_ids.append(order_id)
        shipping_cents = rng.choice((0, 599, 899, 1299))
        order_discount_cents = rng.randint(
            0, min(5000, subtotal_cents // 10)
        )
        payment_amount_cents = (
            subtotal_cents + shipping_cents - order_discount_cents
        )
        rows["orders"].append(
            (
                order_id,
                rng.randint(1, 500),
                order_date,
                "completed" if payment_succeeded else "payment_failed",
                SALES_CHANNELS[(order_id - 1) % len(SALES_CHANNELS)],
                as_money(shipping_cents),
                as_money(order_discount_cents),
            )
        )
        rows["payments"].append(
            (
                order_id,
                order_id,
                order_date,
                rng.choice(PAYMENT_METHODS),
                "successful" if payment_succeeded else "failed",
                as_money(payment_amount_cents),
            )
        )

    refund_order_ids = rng.sample(successful_order_ids, 250)
    for refund_id, order_id in enumerate(refund_order_ids, start=1):
        order = rows["orders"][order_id - 1]
        order_date = order[2]
        assert isinstance(order_date, datetime)
        available_days = max(0, (END_DATE - order_date).days)
        refund_date = order_date + timedelta(
            days=rng.randint(0, min(60, available_days))
        )
        order_item_id, refundable_cents = rng.choice(
            order_refund_items[order_id]
        )
        rows["refunds"].append(
            (
                refund_id,
                order_id,
                order_item_id,
                refund_date,
                as_money(rng.randint(1, refundable_cents)),
                rng.choice(
                    (
                        "Customer changed mind",
                        "Item arrived damaged",
                        "Incorrect item received",
                        "Product did not meet expectations",
                    )
                ),
            )
        )

    return rows


def execute_batched(
    cursor: mysql.connector.cursor.MySQLCursor,
    statement: str,
    rows: list[tuple[object, ...]],
) -> None:
    """Insert rows in batches and return after all statements succeed."""
    for offset in range(0, len(rows), BATCH_SIZE):
        cursor.executemany(statement, rows[offset : offset + BATCH_SIZE])


def verify_seeded_data(
    cursor: mysql.connector.cursor.MySQLCursor,
) -> tuple[dict[str, int], dict[int, int]]:
    """Read seeded tables and return verified row counts and business totals."""
    counts: dict[str, int] = {}
    for table in TABLE_ORDER:
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
        result = cursor.fetchone()
        assert result is not None
        counts[table] = int(result[0])

    empty_tables = [table for table, count in counts.items() if count == 0]
    if empty_tables:
        raise RuntimeError(
            "Seed verification found empty tables: " + ", ".join(empty_tables)
        )

    cursor.execute(
        "SELECT YEAR(order_date), COUNT(*) FROM orders GROUP BY YEAR(order_date)"
    )
    years_result = cursor.fetchall()
    year_counts = {
        int(year): int(count) for year, count in years_result if year is not None
    }
    missing_years = [
        year for year in ORDER_YEARS if year_counts.get(year, 0) == 0
    ]
    if missing_years:
        raise RuntimeError(
            "Seed verification found no orders for years: "
            + ", ".join(map(str, missing_years))
        )

    relationship_checks = {
        "products without categories": """
            SELECT COUNT(*) FROM products p
            LEFT JOIN categories c ON c.category_id = p.category_id
            WHERE c.category_id IS NULL
        """,
        "orders without customers": """
            SELECT COUNT(*) FROM orders o
            LEFT JOIN customers c ON c.customer_id = o.customer_id
            WHERE c.customer_id IS NULL
        """,
        "order items without orders or products": """
            SELECT COUNT(*) FROM order_items oi
            LEFT JOIN orders o ON o.order_id = oi.order_id
            LEFT JOIN products p ON p.product_id = oi.product_id
            WHERE o.order_id IS NULL OR p.product_id IS NULL
        """,
        "payments without orders": """
            SELECT COUNT(*) FROM payments p
            LEFT JOIN orders o ON o.order_id = p.order_id
            WHERE o.order_id IS NULL
        """,
        "refunds without their order item": """
            SELECT COUNT(*) FROM refunds r
            LEFT JOIN orders o ON o.order_id = r.order_id
            LEFT JOIN order_items oi ON oi.order_item_id = r.order_item_id
            WHERE o.order_id IS NULL OR oi.order_item_id IS NULL
                OR oi.order_id <> r.order_id
        """,
        "refunds exceeding item value": """
            SELECT COUNT(*) FROM (
                SELECT r.order_item_id
                FROM refunds r
                JOIN order_items oi ON oi.order_item_id = r.order_item_id
                GROUP BY r.order_item_id, oi.quantity, oi.unit_price,
                    oi.discount_amount
                HAVING SUM(r.refund_amount)
                    > oi.quantity * oi.unit_price - oi.discount_amount
            ) AS over_refunded_items
        """,
    }
    violations: list[str] = []
    for description, statement in relationship_checks.items():
        cursor.execute(statement)
        result = cursor.fetchone()
        assert result is not None
        if int(result[0]) > 0:
            violations.append(f"{description}: {result[0]}")

    if violations:
        raise RuntimeError(
            "Seed verification found invalid relationships or refunds: "
            + "; ".join(violations)
        )

    return counts, year_counts


def main() -> int:
    """Run the script workflow and print its verification result for the operator."""
    connection: mysql.connector.MySQLConnection | None = None
    try:
        settings = DatabaseSettings()
        connection = mysql.connector.connect(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.database,
        )

        with closing(connection.cursor()) as cursor:
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)
            connection.commit()

            counts: dict[str, int] = {}
            for table in TABLE_ORDER:
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                result = cursor.fetchone()
                assert result is not None
                counts[table] = int(result[0])

            connection.commit()

            populated_tables = [
                table for table, count in counts.items() if count > 0
            ]
            if populated_tables:
                print(
                    "Existing data detected; seeding stopped without inserts: "
                    + ", ".join(populated_tables),
                    file=sys.stderr,
                )
                for table, count in counts.items():
                    print(f"{table}: {count}")
                return 1

            rows = build_seed_data()
            connection.start_transaction()
            try:
                for table in TABLE_ORDER:
                    execute_batched(cursor, INSERT_STATEMENTS[table], rows[table])
                counts, year_counts = verify_seeded_data(cursor)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

            for table, count in counts.items():
                print(f"{table}: {count}")
            print(
                "Orders by year: "
                + ", ".join(
                    f"{year}: {year_counts.get(year, 0)}" for year in ORDER_YEARS
                )
            )
            print("Seed verification passed.")
    except (ValidationError, mysql.connector.Error, RuntimeError) as error:
        print(f"Database seeding failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
