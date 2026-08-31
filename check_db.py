import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

conn = psycopg.connect(os.getenv("DATABASE_URL"))

with conn.cursor() as cur:
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)

    for row in cur.fetchall():
        print(row[0])

conn.close()
