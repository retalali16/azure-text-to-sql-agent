import os
import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,       # number of persistent connections kept open
    max_overflow=20,    # extra connections allowed under burst load
    pool_pre_ping=True,  # avoids using dead connections
    pool_recycle=1800,  # recycle connections every 30 min
)

# Blocks any statement that could mutate or destroy data.
FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|CREATE)\b",
    re.IGNORECASE,
)


def is_safe_query(sql: str) -> bool:
    """Only allow single, read-only SELECT statements."""
    sql = sql.strip().rstrip(";")
    if ";" in sql:
        return False  # blocks stacked/multiple statements
    return sql.upper().startswith("SELECT") and not FORBIDDEN.search(sql)


async def execute_sql(query: str, row_limit: int = 200):
    """Execute a validated SQL query and return (rows, error)."""
    if not is_safe_query(query):
        return None, "Query rejected: only single SELECT statements are allowed."

    # Cap rows returned so a huge result set never gets sent back to the LLM.
    limited_query = f"SELECT * FROM ({query}) AS sub LIMIT {row_limit}"

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(limited_query))
            rows = result.fetchall()
            return [tuple(row) for row in rows], None
    except Exception as e:
        return None, str(e)
