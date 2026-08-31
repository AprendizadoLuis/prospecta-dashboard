import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

conn = psycopg.connect(os.getenv("DATABASE_URL"))

with conn.cursor() as cur:

    for table in ["users", "clients", "calendar_events"]:

        print("\n========================================")
        print(f"TABELA: {table}")
        print("========================================")

        cur.execute("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
        """, (table,))

        for row in cur.fetchall():
            print(row)

conn.close()
