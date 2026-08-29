import os
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken

from services.auth_service import get_db_connection


META_API_VERSION = os.getenv("META_API_VERSION", "v26.0")
META_OAUTH_SCOPES = ("ads_read", "business_management")


class MetaOAuthError(Exception):
    pass


def _config():
    config = {
        "app_id": os.getenv("META_APP_ID"),
        "app_secret": os.getenv("META_APP_SECRET"),
        "redirect_uri": os.getenv("META_REDIRECT_URI"),
        "encryption_key": os.getenv("META_TOKEN_ENCRYPTION_KEY"),
    }

    if not all(config.values()):
        raise MetaOAuthError(
            "A conexão Meta ainda não foi configurada no servidor."
        )

    return config


def _fernet():
    try:
        return Fernet(_config()["encryption_key"].encode())
    except (ValueError, TypeError) as exc:
        raise MetaOAuthError(
            "A chave de criptografia da conexão Meta é inválida."
        ) from exc


def build_authorization_url(state):
    config = _config()
    query = urlencode(
        {
            "client_id": config["app_id"],
            "redirect_uri": config["redirect_uri"],
            "response_type": "code",
            "scope": ",".join(META_OAUTH_SCOPES),
            "state": state,
            "auth_type": "rerequest",
        }
    )
    return f"https://www.facebook.com/{META_API_VERSION}/dialog/oauth?{query}"


def _graph_get(path, token, params=None):
    try:
        response = requests.get(
            f"https://graph.facebook.com/{META_API_VERSION}/{path.lstrip('/')}",
            params={"access_token": token, **(params or {})},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise MetaOAuthError("Não foi possível comunicar com a Meta.") from exc

    if not response.ok:
        raise MetaOAuthError("A Meta recusou a solicitação de conexão.")

    return response.json()


def exchange_code_for_token(code):
    config = _config()
    try:
        response = requests.get(
            f"https://graph.facebook.com/{META_API_VERSION}/oauth/access_token",
            params={
                "client_id": config["app_id"],
                "client_secret": config["app_secret"],
                "redirect_uri": config["redirect_uri"],
                "code": code,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise MetaOAuthError("Não foi possível comunicar com a Meta.") from exc

    if not response.ok:
        raise MetaOAuthError("Não foi possível concluir a autorização na Meta.")

    data = response.json()
    token = data.get("access_token")
    if not token:
        raise MetaOAuthError("A Meta não retornou um token de acesso válido.")

    # Troca o token inicial por uma credencial de maior duração quando a Meta
    # disponibiliza essa extensão para o app e usuário autorizados.
    try:
        extended_response = requests.get(
            f"https://graph.facebook.com/{META_API_VERSION}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": config["app_id"],
                "client_secret": config["app_secret"],
                "fb_exchange_token": token,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise MetaOAuthError("Não foi possível comunicar com a Meta.") from exc

    if extended_response.ok:
        extended_data = extended_response.json()
        token = extended_data.get("access_token", token)
        data["expires_in"] = extended_data.get(
            "expires_in", data.get("expires_in")
        )

    expires_at = None
    if data.get("expires_in"):
        expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + int(data["expires_in"]),
            tz=timezone.utc,
        )

    return token, expires_at


def get_meta_user(token):
    data = _graph_get("me", token, {"fields": "id,name"})
    if not data.get("id"):
        raise MetaOAuthError("Não foi possível identificar o usuário autorizado na Meta.")
    return data


def get_ad_accounts(token):
    accounts = []
    url = f"https://graph.facebook.com/{META_API_VERSION}/me/adaccounts"
    params = {
        "access_token": token,
        "fields": "id,account_id,name,account_status,currency,timezone_name",
        "limit": 100,
    }

    while url:
        try:
            response = requests.get(url, params=params, timeout=20)
        except requests.RequestException as exc:
            raise MetaOAuthError("Não foi possível comunicar com a Meta.") from exc
        if not response.ok:
            raise MetaOAuthError("Não foi possível listar as contas de anúncio na Meta.")

        data = response.json()
        accounts.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = None

    return accounts


def _serialize_connection(row, include_token=False):
    if not row:
        return None

    connection = {
        "id": str(row[0]),
        "meta_user_id": row[1],
        "meta_user_name": row[2],
        "token_expires_at": row[4],
        "granted_scopes": row[5] or [],
        "status": row[6],
        "last_error": row[7],
        "last_synced_at": row[8],
        "connected_at": row[9],
    }

    if include_token:
        try:
            connection["access_token"] = _fernet().decrypt(row[3].encode()).decode()
        except InvalidToken as exc:
            raise MetaOAuthError("Não foi possível ler o token salvo para este cliente.") from exc

    return connection


def get_client_connection(client_id, include_token=False):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, meta_user_id, meta_user_name, access_token_encrypted,
                    token_expires_at, granted_scopes, status, last_error,
                    last_synced_at, connected_at
                FROM client_meta_connections
                WHERE client_id = %s
                ORDER BY connected_at DESC
                LIMIT 1
                """,
                (client_id,),
            )
            row = cur.fetchone()

    return _serialize_connection(row, include_token)


def save_connection(client_id, meta_user, token, expires_at):
    encrypted_token = _fernet().encrypt(token.encode()).decode()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO client_meta_connections (
                    client_id, meta_user_id, meta_user_name,
                    access_token_encrypted, token_expires_at,
                    granted_scopes, status, last_error
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'connected', NULL)
                ON CONFLICT (client_id, meta_user_id)
                DO UPDATE SET
                    meta_user_name = EXCLUDED.meta_user_name,
                    access_token_encrypted = EXCLUDED.access_token_encrypted,
                    token_expires_at = EXCLUDED.token_expires_at,
                    granted_scopes = EXCLUDED.granted_scopes,
                    status = 'connected',
                    last_error = NULL,
                    connected_at = now()
                RETURNING id
                """,
                (
                    client_id,
                    meta_user["id"],
                    meta_user.get("name"),
                    encrypted_token,
                    expires_at,
                    list(META_OAUTH_SCOPES),
                ),
            )
            connection_id = cur.fetchone()[0]

            cur.execute(
                """
                UPDATE clients
                SET
                    meta_connection_status = 'connected',
                    meta_sync_error = NULL
                WHERE id = %s
                """,
                (client_id,),
            )

        conn.commit()

    return str(connection_id)


def save_selected_ad_accounts(client_id, connection_id, accounts, selected_ids):
    selected_ids = set(selected_ids)
    selected_accounts = [
        account for account in accounts if account.get("id") in selected_ids
    ]

    if not selected_accounts:
        raise MetaOAuthError("Selecione pelo menos uma conta de anúncio.")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM client_meta_ad_accounts WHERE client_id = %s",
                (client_id,),
            )

            for account in selected_accounts:
                cur.execute(
                    """
                    INSERT INTO client_meta_ad_accounts (
                        client_id, connection_id, meta_account_id,
                        meta_account_name, account_status, is_selected
                    )
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                    """,
                    (
                        client_id,
                        connection_id,
                        account["id"],
                        account.get("name") or account["id"],
                        account.get("account_status"),
                    ),
                )

            cur.execute(
                """
                UPDATE client_meta_connections
                SET last_synced_at = now(), status = 'connected', last_error = NULL
                WHERE id = %s
                """,
                (connection_id,),
            )
            cur.execute(
                """
                UPDATE clients
                SET
                    meta_connection_status = 'connected',
                    meta_last_synced_at = now(),
                    meta_sync_error = NULL
                WHERE id = %s
                """,
                (client_id,),
            )

        conn.commit()


def disconnect_client_meta(client_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM client_meta_connections WHERE client_id = %s",
                (client_id,),
            )
            cur.execute(
                """
                UPDATE clients
                SET
                    meta_connection_status = 'not_connected',
                    meta_last_synced_at = NULL,
                    meta_sync_error = NULL
                WHERE id = %s
                """,
                (client_id,),
            )
        conn.commit()


def get_selected_ad_account_ids(client_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT meta_account_id
                FROM client_meta_ad_accounts
                WHERE client_id = %s
                  AND is_selected = TRUE
                """,
                (client_id,),
            )
            rows = cur.fetchall()

    return {row[0] for row in rows}
