import os
import psycopg
from dotenv import load_dotenv


load_dotenv()


conn = psycopg.connect(
    os.getenv("DATABASE_URL")
)

with conn.cursor() as cur:

    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND (
              table_name ILIKE '%task%'
              OR table_name ILIKE '%tarefa%'
          )
        ORDER BY table_name
    """)

    rows = cur.fetchall()

    if not rows:
        print("Nenhuma tabela de tarefas encontrada.")
    else:
        print("Tabelas encontradas:")

        for row in rows:
            print(row[0])


conn.close()