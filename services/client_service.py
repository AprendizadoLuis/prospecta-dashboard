import os
import time

import requests
from dotenv import load_dotenv

from services.auth_service import get_db_connection


# Garante que as variáveis do .env estejam carregadas antes
# de ler SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.
load_dotenv()


CLIENT_STATUSES = {"draft", "active", "paused", "archived"}

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
AVATAR_BUCKET = "client-avatars"

ALLOWED_AVATAR_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MAX_AVATAR_SIZE = 5 * 1024 * 1024


def _serialize_client(row):
    if not row:
        return None

    return {
        "id": str(row[0]),
        "name": row[1],
        "legal_name": row[2],
        "document": row[3],
        "contact_name": row[4],
        "contact_email": row[5],
        "contact_phone": row[6],
        "website": row[7],
        "segment": row[8],
        "notes": row[9],
        "status": row[10],
        "is_active": row[11],
        "meta_connection_status": row[12],
        "meta_last_synced_at": row[13],
        "responsible_user_id": str(row[14]) if row[14] else None,
        "responsible_name": row[15],
        "avatar_url": row[16],
    }


CLIENT_COLUMNS = """
    c.id,
    c.name,
    c.legal_name,
    c.document,
    c.contact_name,
    c.contact_email,
    c.contact_phone,
    c.website,
    c.segment,
    c.notes,
    c.status,
    c.is_active,
    c.meta_connection_status,
    c.meta_last_synced_at,
    c.responsible_user_id,
    u.name AS responsible_name,
    c.avatar_url
"""


def _validate_avatar(avatar_file):
    if not avatar_file:
        return None

    content_type = (avatar_file.content_type or "").lower()

    if content_type not in ALLOWED_AVATAR_TYPES:
        raise ValueError(
            "A foto deve estar em JPG, PNG ou WEBP."
        )

    avatar_file.stream.seek(0)
    content = avatar_file.stream.read()
    avatar_file.stream.seek(0)

    if len(content) > MAX_AVATAR_SIZE:
        raise ValueError(
            "A foto deve ter no máximo 5 MB."
        )

    if not content:
        raise ValueError(
            "O arquivo da foto está vazio."
        )

    return ALLOWED_AVATAR_TYPES[content_type]


def _upload_avatar(client_id, avatar_file):
    """
    Envia a foto para o bucket client-avatars e retorna a URL pública.
    """

    # Relembra as variáveis do ambiente no momento do upload.
    # Isso evita problemas caso o módulo tenha sido importado antes do .env.
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url:
        raise RuntimeError(
            "SUPABASE_URL não configurada no arquivo .env."
        )

    if not service_role_key:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY não configurada no arquivo .env."
        )

    extension = _validate_avatar(avatar_file)

    avatar_file.stream.seek(0)
    file_content = avatar_file.stream.read()
    avatar_file.stream.seek(0)

    file_path = f"clients/{client_id}/avatar{extension}"

    upload_url = (
        f"{supabase_url}/storage/v1/object/"
        f"{AVATAR_BUCKET}/{file_path}"
    )

    headers = {
        "Authorization": f"Bearer {service_role_key}",
        "apikey": service_role_key,
        "Content-Type": avatar_file.content_type,
        "x-upsert": "true",
    }

    response = requests.post(
        upload_url,
        headers=headers,
        data=file_content,
        timeout=30,
    )

    if response.status_code not in {200, 201}:
        raise RuntimeError(
            "Erro ao enviar foto para o Supabase: "
            f"{response.status_code} - {response.text}"
        )

    # A query string impede que o navegador mantenha a versão anterior
    # da mesma imagem em cache depois de uma nova atualização.
    cache_buster = int(time.time())

    public_url = (
        f"{supabase_url}/storage/v1/object/public/"
        f"{AVATAR_BUCKET}/{file_path}?v={cache_buster}"
    )

    print(f"FOTO ENVIADA AO SUPABASE: {public_url}")

    return public_url


def list_clients():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {CLIENT_COLUMNS}
                FROM clients c
                LEFT JOIN users u
                    ON u.id = c.responsible_user_id
                ORDER BY
                    CASE c.status
                        WHEN 'active' THEN 1
                        WHEN 'draft' THEN 2
                        WHEN 'paused' THEN 3
                        ELSE 4
                    END,
                    c.name
                """
            )

            rows = cur.fetchall()

    return [_serialize_client(row) for row in rows]


def get_client(client_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {CLIENT_COLUMNS}
                FROM clients c
                LEFT JOIN users u
                    ON u.id = c.responsible_user_id
                WHERE c.id = %s
                """,
                (client_id,),
            )

            return _serialize_client(cur.fetchone())


def save_client(data, client_id=None, avatar_file=None):
    values = (
        data["name"],
        data["legal_name"],
        data["document"],
        data["contact_name"],
        data["contact_email"],
        data["contact_phone"],
        data["website"],
        data["segment"],
        data["notes"],
        data["status"],
        data.get("responsible_user_id") or None,
    )

    with get_db_connection() as conn:
        with conn.cursor() as cur:

            if client_id:

                cur.execute(
                    """
                    UPDATE clients
                    SET
                        name = %s,
                        legal_name = %s,
                        document = %s,
                        contact_name = %s,
                        contact_email = %s,
                        contact_phone = %s,
                        website = %s,
                        segment = %s,
                        notes = %s,
                        status = %s,
                        responsible_user_id = %s
                    WHERE id = %s
                    RETURNING id
                    """,
                    values + (client_id,),
                )

            else:

                cur.execute(
                    """
                    INSERT INTO clients (
                        name,
                        legal_name,
                        document,
                        contact_name,
                        contact_email,
                        contact_phone,
                        website,
                        segment,
                        notes,
                        status,
                        responsible_user_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    values,
                )

            row = cur.fetchone()

        conn.commit()

    saved_client_id = str(row[0]) if row else None

    if not saved_client_id:
        return None

    # Faz o upload somente se uma nova foto foi enviada.
    if avatar_file and avatar_file.filename:
        print(
            f"INICIANDO UPLOAD DA FOTO DO CLIENTE: "
            f"{saved_client_id} - {avatar_file.filename}"
        )

        avatar_url = _upload_avatar(
            saved_client_id,
            avatar_file
        )

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE clients
                    SET avatar_url = %s
                    WHERE id = %s
                    """,
                    (
                        avatar_url,
                        saved_client_id,
                    ),
                )

            conn.commit()

        print(
            f"AVATAR_URL SALVA NO BANCO PARA {saved_client_id}: "
            f"{avatar_url}"
        )

    return saved_client_id


def delete_client(client_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                DELETE FROM clients
                WHERE id = %s
                RETURNING id
                """,
                (client_id,),
            )

            row = cur.fetchone()

        conn.commit()

    return bool(row)
