import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

conn = psycopg.connect(os.getenv("DATABASE_URL"))

with conn.cursor() as cur:
    cur.execute("""
        SELECT id, name, email, role, is_active
        FROM users
        ORDER BY created_at
    """)

    for row in cur.fetchall():
        print(row)

conn.close()
