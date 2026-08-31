import os
import psycopg
from dotenv import load_dotenv


load_dotenv()


def main():

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL não configurada."
        )

    print("Conectando ao banco...")

    with psycopg.connect(database_url) as conn:

        with conn.cursor() as cur:

            # ============================================================
            # 1. Verifica se a coluna já existe
            # ============================================================

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'clients'
                      AND column_name = 'responsible_user_id'
                )
            """)

            column_exists = cur.fetchone()[0]

            if column_exists:

                print(
                    "✓ A coluna responsible_user_id já existe."
                )

            else:

                print(
                    "→ Criando coluna responsible_user_id..."
                )

                cur.execute("""
                    ALTER TABLE clients
                    ADD COLUMN responsible_user_id UUID
                """)

                print(
                    "✓ Coluna criada."
                )

            # ============================================================
            # 2. Verifica se a Foreign Key já existe
            # ============================================================

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE constraint_schema = 'public'
                      AND table_name = 'clients'
                      AND constraint_name = 'fk_clients_responsible_user'
                      AND constraint_type = 'FOREIGN KEY'
                )
            """)

            fk_exists = cur.fetchone()[0]

            if fk_exists:

                print(
                    "✓ A Foreign Key já existe."
                )

            else:

                print(
                    "→ Criando Foreign Key..."
                )

                cur.execute("""
                    ALTER TABLE clients
                    ADD CONSTRAINT fk_clients_responsible_user
                    FOREIGN KEY (responsible_user_id)
                    REFERENCES users(id)
                    ON DELETE SET NULL
                """)

                print(
                    "✓ Foreign Key criada."
                )

        conn.commit()

    print()
    print("========================================")
    print("MIGRATION 001 CONCLUÍDA")
    print("========================================")
    print()
    print(
        "clients.responsible_user_id está pronto."
    )
    print(
        "Nenhum cliente existente foi alterado."
    )
    print()


if __name__ == "__main__":
    main()