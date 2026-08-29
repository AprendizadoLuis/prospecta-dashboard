import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não encontrada no arquivo .env")


try:
    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cursor:

            cursor.execute("SELECT version();")

            result = cursor.fetchone()

            print("================================")
            print("CONEXÃO COM O BANCO OK!")
            print("================================")
            print(result[0])

except Exception as e:

    print("================================")
    print("ERRO AO CONECTAR AO BANCO")
    print("================================")
    print(e)