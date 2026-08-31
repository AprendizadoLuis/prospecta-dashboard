import os
import psycopg
from dotenv import load_dotenv


load_dotenv()


def main():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL não configurada.")

    print("Conectando ao banco...")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:

            print("Criando tabela tasks...")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

                    client_id UUID NOT NULL,
                    created_by UUID NOT NULL,
                    assigned_to UUID NOT NULL,

                    title VARCHAR(255) NOT NULL,
                    description TEXT,

                    status VARCHAR(30) NOT NULL DEFAULT 'pending',
                    priority VARCHAR(30) NOT NULL DEFAULT 'medium',
                    visibility VARCHAR(20) NOT NULL DEFAULT 'public',

                    due_date TIMESTAMP WITH TIME ZONE,

                    completed_at TIMESTAMP WITH TIME ZONE,

                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),

                    CONSTRAINT fk_tasks_client
                        FOREIGN KEY (client_id)
                        REFERENCES clients(id)
                        ON DELETE RESTRICT,

                    CONSTRAINT fk_tasks_created_by
                        FOREIGN KEY (created_by)
                        REFERENCES users(id)
                        ON DELETE RESTRICT,

                    CONSTRAINT fk_tasks_assigned_to
                        FOREIGN KEY (assigned_to)
                        REFERENCES users(id)
                        ON DELETE RESTRICT,

                    CONSTRAINT chk_tasks_status
                        CHECK (
                            status IN (
                                'pending',
                                'in_progress',
                                'completed',
                                'cancelled'
                            )
                        ),

                    CONSTRAINT chk_tasks_priority
                        CHECK (
                            priority IN (
                                'low',
                                'medium',
                                'high',
                                'urgent'
                            )
                        ),

                    CONSTRAINT chk_tasks_visibility
                        CHECK (
                            visibility IN (
                                'public',
                                'private'
                            )
                        )
                )
            """)

            print("✓ Tabela tasks criada ou já existente.")

            # Índices para acelerar as consultas mais utilizadas
            print("Criando índices...")

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_client_id
                ON tasks(client_id)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_created_by
                ON tasks(created_by)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to
                ON tasks(assigned_to)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_due_date
                ON tasks(due_date)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status
                ON tasks(status)
            """)

            print("✓ Índices criados.")

        conn.commit()

    print()
    print("========================================")
    print("MIGRATION 002 CONCLUÍDA")
    print("========================================")
    print()
    print("Tabela tasks está pronta.")
    print()
    print("Relacionamentos:")
    print("  tasks.client_id    → clients.id")
    print("  tasks.created_by   → users.id")
    print("  tasks.assigned_to  → users.id")
    print()
    print("assigned_to é obrigatório.")
    print("Nenhum dado existente foi alterado.")
    print()


if __name__ == "__main__":
    main()