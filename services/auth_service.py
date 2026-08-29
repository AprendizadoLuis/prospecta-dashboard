from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)

import os
import psycopg


def get_db_connection():

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL não configurada."
        )

    return psycopg.connect(
        database_url
    )


def authenticate_user(email, password):

    email = email.strip().lower()

    with get_db_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    name,
                    email,
                    role,
                    password_hash,
                    is_active
                FROM users
                WHERE LOWER(email) = %s
                LIMIT 1
                """,
                (email,)
            )

            user = cur.fetchone()

    if not user:
        return None

    (
        user_id,
        name,
        email,
        role,
        password_hash,
        is_active
    ) = user

    if not is_active:
        return None

    if not check_password_hash(
        password_hash,
        password
    ):
        return None

    return {
        "id": str(user_id),
        "name": name,
        "email": email,
        "role": role
    }


def create_user(name, email, password):

    email = email.strip().lower()

    password_hash = generate_password_hash(
        password
    )

    with get_db_connection() as conn:

        with conn.cursor() as cur:

            # Verifica se já existe
            cur.execute(
                """
                SELECT id
                FROM users
                WHERE LOWER(email) = %s
                LIMIT 1
                """,
                (email,)
            )

            existing_user = cur.fetchone()

            if existing_user:
                return None

            # Primeiro usuário criado será admin.
            # Depois podemos transformar isso
            # em uma regra de convite/permissão.
            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                """
            )

            total_users = cur.fetchone()[0]

            role = (
                "admin"
                if total_users == 0
                else "user"
            )

            cur.execute(
                """
                INSERT INTO users (
                    name,
                    email,
                    password_hash,
                    role,
                    is_active
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    TRUE
                )
                RETURNING id, name, email, role
                """,
                (
                    name,
                    email,
                    password_hash,
                    role
                )
            )

            user = cur.fetchone()

        conn.commit()

    return {
        "id": str(user[0]),
        "name": user[1],
        "email": user[2],
        "role": user[3]
    }