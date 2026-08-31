import os
import psycopg
from dotenv import load_dotenv


load_dotenv()


conn = psycopg.connect(
    os.getenv("DATABASE_URL")
)

with conn.cursor() as cur:

    print("========================================")
    print("ESTRUTURA DA TABELA TASKS")
    print("========================================")

    cur.execute("""
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tasks'
        ORDER BY ordinal_position
    """)

    for row in cur.fetchall():
        print(row)

    print()
    print("========================================")
    print("FOREIGN KEYS")
    print("========================================")

    cur.execute("""
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS referenced_table,
            ccu.column_name AS referenced_column
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.table_name = 'tasks'
          AND tc.constraint_type = 'FOREIGN KEY'
        ORDER BY kcu.column_name
    """)

    for row in cur.fetchall():
        print(row)

conn.close()