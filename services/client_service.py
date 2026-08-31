from services.auth_service import get_db_connection


CLIENT_STATUSES = {"draft", "active", "paused", "archived"}


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
    u.name AS responsible_name
"""


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


def save_client(data, client_id=None):
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

    return str(row[0]) if row else None


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