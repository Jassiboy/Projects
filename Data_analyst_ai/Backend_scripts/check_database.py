"""Check configured MySQL connectivity and print the available application tables."""

import sys
from contextlib import closing
from pathlib import Path

import mysql.connector
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


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


def main() -> int:
    """Run the script workflow and print its verification result for the operator."""
    try:
        settings = DatabaseSettings()
        with closing(
            mysql.connector.connect(
                host=settings.host,
                port=settings.port,
                user=settings.user,
                password=settings.password,
                database=settings.database,
            )
        ) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                print(f"SELECT 1 result: {result[0]}")

                cursor.execute("SHOW TABLES")
                tables = [row[0] for row in cursor.fetchall()]

                print(f"Tables in {settings.database} ({len(tables)}):")
                for table in tables:
                    print(f"- {table}")
    except (ValidationError, mysql.connector.Error) as error:
        print(f"Database check failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
