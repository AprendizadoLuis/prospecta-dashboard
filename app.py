
import os
import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
)

from services.agenda_service import get_dashboard_data
from services.auth_service import authenticate_user, get_db_connection
from services.client_service import (
    CLIENT_STATUSES,
    delete_client,
    get_client,
    list_clients,
    save_client,
)
from services.meta_oauth_service import (
    MetaOAuthError,
    build_authorization_url,
    disconnect_client_meta,
    exchange_code_for_token,
    get_ad_accounts as get_client_meta_ad_accounts,
    get_client_connection,
    get_meta_user,
    get_selected_ad_account_ids,
    save_connection,
    save_selected_ad_accounts,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY não configurada no arquivo .env"
    )


# ============================================================
# META ADS
# ============================================================

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")

META_API_VERSION = "v26.0"

MESSAGING_CONVERSATION_ACTION = (
    "onsite_conversion.messaging_conversation_started_7d"
)


# ============================================================
# AUTENTICAÇÃO
# ============================================================

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped_view


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    # Se já estiver logado, não precisa voltar para o login
    if "user_id" in session:
        return redirect(url_for("home"))

    error = None
    email = ""

    if request.method == "POST":

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:

            error = "Informe seu e-mail e sua senha."

        else:

            user = authenticate_user(
                email,
                password
            )

            if user:

                # Limpa qualquer sessão anterior
                session.clear()

                # Salva os dados necessários do usuário
                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                session["user_email"] = user["email"]
                session["user_role"] = user["role"]

                return redirect(url_for("home"))

            error = "E-mail ou senha inválidos."

    return render_template(
        "login.html",
        error=error,
        email=email
    )

@app.route("/register", methods=["GET", "POST"])
def register():

    if "user_id" in session:
        return redirect(url_for("home"))

    error = None

    name = ""
    email = ""

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not name or not email or not password:
            error = "Preencha todos os campos."

        elif password != confirm_password:
            error = "As senhas não coincidem."

        elif len(password) < 8:
            error = "A senha deve ter pelo menos 8 caracteres."

        else:

            try:

                from services.auth_service import create_user

                user = create_user(
                    name=name,
                    email=email,
                    password=password
                )

                if user:

                    session.clear()

                    session["user_id"] = user["id"]
                    session["user_name"] = user["name"]
                    session["user_email"] = user["email"]
                    session["user_role"] = user["role"]

                    return redirect(
                        url_for("home")
                    )

                error = "Este e-mail já está cadastrado."

            except Exception as e:

                print(
                    f"ERRO AO CRIAR USUÁRIO: {e}"
                )

                error = (
                    "Não foi possível criar a conta. "
                    "Tente novamente."
                )

    return render_template(
        "register.html",
        error=error,
        name=name,
        email=email
    )
# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))

@app.route("/perfil")
def perfil():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "perfil.html",
        active_page="perfil"
    )


# ============================================================
# CLIENTES
# ============================================================

def get_client_form_data():
    return {
        "name": request.form.get("name", "").strip(),
        "legal_name": request.form.get("legal_name", "").strip() or None,
        "document": request.form.get("document", "").strip() or None,
        "contact_name": request.form.get("contact_name", "").strip() or None,
        "contact_email": request.form.get("contact_email", "").strip().lower() or None,
        "contact_phone": request.form.get("contact_phone", "").strip() or None,
        "website": request.form.get("website", "").strip() or None,
        "segment": request.form.get("segment", "").strip() or None,
        "notes": request.form.get("notes", "").strip() or None,
        "status": request.form.get("status", "draft"),
        "responsible_user_id": request.form.get("responsible_user_id") or None,
    }
    
def list_users_for_assignment():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, email
                FROM users
                WHERE is_active = TRUE
                ORDER BY name
            """)
            rows = cur.fetchall()

    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "email": row[2],
        }
        for row in rows
    ]


def validate_client_form(data):
    if not data["name"]:
        return "Informe o nome do cliente."

    if data["status"] not in CLIENT_STATUSES:
        return "Status de cliente inválido."

    if data["contact_email"] and "@" not in data["contact_email"]:
        return "Informe um e-mail de contato válido."

    return None


def list_users_for_assignment():
    """
    Retorna os usuários ativos disponíveis para serem vinculados
    como gestores/responsáveis dos clientes.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, email, role
                FROM users
                WHERE is_active = TRUE
                ORDER BY name
            """)
            rows = cur.fetchall()

    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "email": row[2],
            "role": row[3],
        }
        for row in rows
    ]


@app.route("/clientes")
@login_required
def clientes():
    try:
        clients = list_clients()
        users = list_users_for_assignment()
        error = None
    except Exception as exc:
        print(f"ERRO AO LISTAR CLIENTES: {exc}")
        clients = []
        users = []
        error = "Não foi possível carregar os clientes. Tente novamente."

    return render_template(
        "clientes.html",
        active_page="clientes",
        clients=clients,
        users=users,
        error=error,
        message=request.args.get("message"),
    )


@app.route("/clientes/novo", methods=["GET", "POST"])
@login_required
def novo_cliente():
    client = {
        "status": "draft",
        "responsible_user_id": None,
    }
    error = None

    try:
        users = list_users_for_assignment()
    except Exception as exc:
        print(f"ERRO AO LISTAR USUÁRIOS PARA CLIENTE: {exc}")
        users = []
        error = "Não foi possível carregar os gestores disponíveis."

    if request.method == "POST":
        client = get_client_form_data()
        error = validate_client_form(client)

        if not error:
            try:
                save_client(client)
                return redirect(
                    url_for(
                        "clientes",
                        message="Cliente criado com sucesso.",
                    )
                )
            except Exception as exc:
                print(f"ERRO AO CRIAR CLIENTE: {exc}")
                error = (
                    "Não foi possível criar o cliente. "
                    "Verifique os dados e tente novamente."
                )

    return render_template(
        "cliente_form.html",
        active_page="clientes",
        client=client,
        users=users,
        error=error,
        is_edit=False,
    )


@app.route("/clientes/<uuid:client_id>/editar", methods=["GET", "POST"])
@login_required
def editar_cliente(client_id):
    try:
        client = get_client(client_id)
    except Exception as exc:
        print(f"ERRO AO BUSCAR CLIENTE: {exc}")
        client = None

    if not client:
        return redirect(
            url_for(
                "clientes",
                message="Cliente não encontrado.",
            )
        )

    error = None

    try:
        users = list_users_for_assignment()
    except Exception as exc:
        print(f"ERRO AO LISTAR USUÁRIOS PARA CLIENTE: {exc}")
        users = []
        error = "Não foi possível carregar os gestores disponíveis."

    if request.method == "POST":
        client = get_client_form_data()
        client["id"] = str(client_id)
        error = validate_client_form(client)

        if not error:
            try:
                save_client(client, client_id)
                return redirect(
                    url_for(
                        "clientes",
                        message="Cliente atualizado com sucesso.",
                    )
                )
            except Exception as exc:
                print(f"ERRO AO ATUALIZAR CLIENTE: {exc}")
                error = "Não foi possível atualizar o cliente. Tente novamente."

    return render_template(
        "cliente_form.html",
        active_page="clientes",
        client=client,
        users=users,
        error=error,
        is_edit=True,
        meta_connection=get_client_connection(client_id),
        meta_message=request.args.get("meta_message"),
        meta_error=request.args.get("meta_error"),
    )


@app.route("/clientes/<uuid:client_id>/excluir", methods=["POST"])
@login_required
def excluir_cliente(client_id):
    try:
        deleted = delete_client(client_id)
        message = "Cliente removido com sucesso." if deleted else "Cliente não encontrado."
    except Exception as exc:
        print(f"ERRO AO REMOVER CLIENTE: {exc}")
        message = "Não foi possível remover o cliente."

    return redirect(url_for("clientes", message=message))


# ============================================================
# META ADS / OAUTH POR CLIENTE
# ============================================================

@app.route("/clientes/<uuid:client_id>/meta/conectar")
@login_required
def conectar_meta_cliente(client_id):
    if not get_client(client_id):
        return redirect(url_for("clientes", message="Cliente não encontrado."))

    state = secrets.token_urlsafe(32)
    session["meta_oauth"] = {
        "state": state,
        "client_id": str(client_id),
    }

    try:
        return redirect(build_authorization_url(state))
    except MetaOAuthError as exc:
        return redirect(
            url_for(
                "editar_cliente",
                client_id=client_id,
                meta_error=str(exc),
            )
        )


@app.route("/integracoes/meta/callback")
@login_required
def meta_oauth_callback():

    print("\n========== META CALLBACK ==========")
    print("URL:", request.url)
    print("ARGS:", dict(request.args))
    print("SESSION:", dict(session))

    oauth_context = session.pop("meta_oauth", None)
    received_state = request.args.get("state")

    print("OAUTH CONTEXT:", oauth_context)
    print("RECEIVED STATE:", received_state)

    if not oauth_context:
        print("ERRO: oauth_context NÃO EXISTE")
        return redirect(
            url_for(
                "clientes",
                message="A autorização Meta expirou ou é inválida."
            )
        )

    if not secrets.compare_digest(
        oauth_context.get("state", ""),
        received_state or ""
    ):
        print("ERRO: STATE NÃO CONFERE")
        print("STATE SALVO:", oauth_context.get("state"))
        print("STATE RECEBIDO:", received_state)

        return redirect(
            url_for(
                "clientes",
                message="A autorização Meta expirou ou é inválida."
            )
        )

    client_id = oauth_context["client_id"]

    meta_error = request.args.get("error")

    if meta_error:
        print("ERRO META:", meta_error)

        return redirect(
            url_for(
                "editar_cliente",
                client_id=client_id,
                meta_error="A autorização Meta foi cancelada ou não foi concedida.",
            )
        )

    code = request.args.get("code")

    print("CODE RECEBIDO:", bool(code))

    if not code:
        print("ERRO: CODE NÃO RECEBIDO")

        return redirect(
            url_for(
                "editar_cliente",
                client_id=client_id,
                meta_error="A Meta não retornou o código de autorização.",
            )
        )

    try:

        print("1 - Trocando CODE por TOKEN...")

        token, expires_at = exchange_code_for_token(code)

        print("2 - TOKEN RECEBIDO:", bool(token))

        print("3 - Buscando usuário Meta...")

        meta_user = get_meta_user(token)

        print("4 - META USER:", meta_user)

        print("5 - Salvando conexão no banco...")

        connection_id = save_connection(
            client_id,
            meta_user,
            token,
            expires_at
        )

        print("6 - CONEXÃO SALVA:", connection_id)

        return redirect(
            url_for(
                "selecionar_contas_meta",
                client_id=client_id
            )
        )

    except Exception as exc:

        print("========== ERRO META ==========")
        print(type(exc).__name__, str(exc))

        return redirect(
            url_for(
                "editar_cliente",
                client_id=client_id,
                meta_error=f"Erro na conexão Meta: {exc}",
            )
        )

@app.route("/clientes/<uuid:client_id>/meta/contas", methods=["GET", "POST"])
@login_required
def selecionar_contas_meta(client_id):
    client = get_client(client_id)
    if not client:
        return redirect(url_for("clientes", message="Cliente não encontrado."))

    try:
        connection = get_client_connection(client_id, include_token=True)
        if not connection:
            raise MetaOAuthError("Conecte a Meta Ads antes de escolher as contas.")

        accounts = get_client_meta_ad_accounts(connection["access_token"])
        selected_account_ids = get_selected_ad_account_ids(client_id)

        if request.method == "POST":
            save_selected_ad_accounts(
                client_id,
                connection["id"],
                accounts,
                request.form.getlist("account_ids"),
            )
            return redirect(
                url_for(
                    "editar_cliente",
                    client_id=client_id,
                    meta_message="Contas de anúncio vinculadas com sucesso.",
                )
            )

    except MetaOAuthError as exc:
        return redirect(
            url_for("editar_cliente", client_id=client_id, meta_error=str(exc))
        )

    return render_template(
        "meta_accounts.html",
        active_page="clientes",
        client=client,
        accounts=accounts,
        connection=connection,
        selected_account_ids=selected_account_ids,
    )


@app.route("/clientes/<uuid:client_id>/meta/desconectar", methods=["POST"])
@login_required
def desconectar_meta_cliente(client_id):
    try:
        disconnect_client_meta(client_id)
        message = "Conexão Meta removida com sucesso."
        error = None
    except Exception as exc:
        print(f"ERRO AO DESCONECTAR META: {exc}")
        message = None
        error = "Não foi possível remover a conexão Meta."

    return redirect(
        url_for(
            "editar_cliente",
            client_id=client_id,
            meta_message=message,
            meta_error=error,
        )
    )

# ============================================================
# DATAS
# ============================================================

def get_default_dates():

    today = datetime.now().date()

    since = today - timedelta(days=29)

    until = today

    return (
        since.strftime("%Y-%m-%d"),
        until.strftime("%Y-%m-%d")
    )


def validate_dates(since, until):

    try:

        since_date = datetime.strptime(
            since,
            "%Y-%m-%d"
        ).date()

        until_date = datetime.strptime(
            until,
            "%Y-%m-%d"
        ).date()

        if since_date > until_date:
            return False

        return True

    except (ValueError, TypeError):

        return False


def format_date_br(date_string):

    try:

        date = datetime.strptime(
            date_string,
            "%Y-%m-%d"
        )

        return date.strftime("%d/%m/%Y")

    except (ValueError, TypeError):

        return date_string


# ============================================================
# CONTAS DE ANÚNCIOS
# ============================================================

def get_ad_accounts():

    url = (
        f"https://graph.facebook.com/"
        f"{META_API_VERSION}/me/adaccounts"
    )

    params = {

        "access_token":
            META_ACCESS_TOKEN,

        "fields":
            "id,name,account_id,account_status",

        "limit":
            100
    }

    accounts = []

    while url:

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        data = response.json()

        if response.status_code != 200:

            return [], data

        accounts.extend(
            data.get("data", [])
        )

        url = (
            data.get(
                "paging",
                {}
            ).get("next")
        )

        params = {}

    return accounts, None


# ============================================================
# INSIGHTS DA CONTA
# ============================================================

def get_account_insights(
    account,
    since,
    until,
    access_token
):

    account_id = account["id"]

    url = (
        f"https://graph.facebook.com/"
        f"{META_API_VERSION}/"
        f"{account_id}/insights"
    )

    params = {

        "access_token":
            access_token,

        "fields":
            "spend,impressions,reach,actions",

        "time_range":
            f'{{"since":"{since}","until":"{until}"}}'
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        data = response.json()

        if response.status_code != 200:

            return {

                "id":
                    account_id,

                "name":
                    (
                        account.get("client_name")
                        or account.get("name")
                        or "Sem nome"
                    ),

                "account_id":
                    account.get(
                        "account_id",
                        ""
                    ),

                "spend":
                    0,

                "conversations":
                    0,

                "cost_per_conversation":
                    0,

                "impressions":
                    0,

                "reach":
                    0,

                "link_clicks":
                    0,

                "ctr":
                    0,

                "cpm":
                    0,

                "error":
                    data
            }


        # ====================================================
        # VALORES
        # ====================================================

        spend = 0

        impressions = 0

        reach = 0

        link_clicks = 0

        conversations = 0


        # ====================================================
        # DATA
        # ====================================================

        if data.get("data"):

            result = data["data"][0]

            spend = float(
                result.get(
                    "spend",
                    0
                )
            )

            impressions = int(
                float(
                    result.get(
                        "impressions",
                        0
                    )
                )
            )

            reach = int(
                float(
                    result.get(
                        "reach",
                        0
                    )
                )
            )

            actions = result.get(
                "actions",
                []
            )


            # =================================================
            # ACTIONS
            # =================================================

            for action in actions:

                action_type = action.get(
                    "action_type",
                    ""
                )

                value = float(
                    action.get(
                        "value",
                        0
                    )
                )


                # ------------------------------------------------
                # CONVERSAS INICIADAS
                # ------------------------------------------------

                if action_type == (
                    MESSAGING_CONVERSATION_ACTION
                ):

                    conversations += value


                # ------------------------------------------------
                # CLIQUES NO LINK
                # ------------------------------------------------

                if action_type in [

                    "link_click",

                    "inline_link_click"

                ]:

                    link_clicks += value


        # ====================================================
        # MÉTRICAS CALCULADAS
        # ====================================================

        cost_per_conversation = (

            spend / conversations

            if conversations > 0

            else 0
        )


        ctr = (

            (
                link_clicks
                / impressions
            ) * 100

            if impressions > 0

            else 0
        )


        cpm = (

            (
                spend
                / impressions
            ) * 1000

            if impressions > 0

            else 0
        )


        # ====================================================
        # RETORNO
        # ====================================================

        return {

            "id":
                account_id,

            "name":
                (
                    account.get("client_name")
                    or account.get("name")
                    or "Sem nome"
                ),

            "account_id":
                account.get(
                    "account_id",
                    ""
                ),

            "spend":
                spend,

            "conversations":
                conversations,

            "cost_per_conversation":
                cost_per_conversation,

            "impressions":
                impressions,

            "reach":
                reach,

            "link_clicks":
                link_clicks,

            "ctr":
                ctr,

            "cpm":
                cpm,

            "error":
                None
        }


    except Exception as error:

        return {

            "id":
                account_id,

            "name":
                (
                    account.get("client_name")
                    or account.get("name")
                    or "Sem nome"
                ),

            "account_id":
                account.get(
                    "account_id",
                    ""
                ),

            "spend":
                0,

            "conversations":
                0,

            "cost_per_conversation":
                0,

            "impressions":
                0,

            "reach":
                0,

            "link_clicks":
                0,

            "ctr":
                0,

            "cpm":
                0,

            "error": {

                "message":
                    str(error)
            }
        }


# ============================================================
# STATUS
# ============================================================

def classify_account(
    account,
    average_cost
):

    cost = account[
        "cost_per_conversation"
    ]


    if account[
        "conversations"
    ] == 0:

        return {

            "label":
                "Crítico",

            "class":
                "critical"
        }


    if average_cost <= 0:

        return {

            "label":
                "Saudável",

            "class":
                "healthy"
        }


    ratio = cost / average_cost


    if ratio <= 1.15:

        return {

            "label":
                "Saudável",

            "class":
                "healthy"
        }


    if ratio <= 1.50:

        return {

            "label":
                "Atenção",

            "class":
                "warning"
        }


    return {

        "label":
            "Crítico",

        "class":
            "critical"
    }


# ============================================================
# HOME / OVERVIEW
# ============================================================

def calculate_percentage_change(current, previous):
    """Retorna a variação percentual entre dois períodos.

    Quando o período anterior é zero, não existe uma base matemática
    confiável para calcular a porcentagem; nesse caso retornamos None.
    """
    if previous == 0:
        return None

    return ((current - previous) / previous) * 100


def get_previous_period(since, until):
    """Calcula o período imediatamente anterior com a mesma duração."""
    since_date = datetime.strptime(since, "%Y-%m-%d").date()
    until_date = datetime.strptime(until, "%Y-%m-%d").date()

    period_days = (until_date - since_date).days + 1

    previous_until = since_date - timedelta(days=1)
    previous_since = previous_until - timedelta(days=period_days - 1)

    return (
        previous_since.strftime("%Y-%m-%d"),
        previous_until.strftime("%Y-%m-%d")
    )


def get_account_period_data(
    account,
    access_token,
    since,
    until,
    previous_since,
    previous_until
):
    """Busca o período atual e o período anterior da mesma conta."""
    current = get_account_insights(
        account,
        since,
        until,
        access_token
    )

    previous = get_account_insights(
        account,
        previous_since,
        previous_until,
        access_token
    )

    return current, previous


@app.route("/")
@login_required
def home():

    # ========================================================
    # DATAS
    # ========================================================

    default_since, default_until = get_default_dates()

    since = request.args.get(
        "since",
        default_since
    )

    until = request.args.get(
        "until",
        default_until
    )

    if not validate_dates(since, until):
        since = default_since
        until = default_until

    previous_since, previous_until = get_previous_period(
        since,
        until
    )

    period_label = (
        f"{format_date_br(since)} - "
        f"{format_date_br(until)}"
    )

    previous_period_label = (
        f"{format_date_br(previous_since)} - "
        f"{format_date_br(previous_until)}"
    )

    # ========================================================
    # CLIENTES CONECTADOS
    # ========================================================

    try:
        clients = list_clients()
    except Exception as exc:
        print(f"ERRO AO LISTAR CLIENTES DO OVERVIEW: {exc}")

        return render_template(
            "index.html",
            active_page="overview",
            accounts=[],
            error="Não foi possível carregar os clientes conectados.",
            since=since,
            until=until,
            period_label=period_label,
            previous_period_label=previous_period_label,
            total_spend=0,
            previous_total_spend=0,
            total_conversations=0,
            previous_total_conversations=0,
            average_cost_per_conversation=0,
            previous_average_cost_per_conversation=0,
            average_ctr=0,
            previous_average_ctr=0,
            average_cpm=0,
            previous_average_cpm=0,
            spend_change=None,
            conversations_change=None,
            cost_change=None,
            ctr_change=None,
            cpm_change=None,
            critical_count=0,
            warning_count=0,
            healthy_count=0
        )

    # ========================================================
    # BUSCAR CONTAS DOS CLIENTES CONECTADOS
    # ========================================================

    connected_accounts = []

    for client in clients:

        client_id = client.get("id")

        if not client_id:
            continue

        try:
            connection = get_client_connection(
                client_id,
                include_token=True
            )

            if not connection:
                continue

            if connection.get("status") != "connected":
                continue

            access_token = connection.get("access_token")

            if not access_token:
                continue

            selected_ids = get_selected_ad_account_ids(
                client_id
            )

            if not selected_ids:
                continue

            meta_accounts = get_client_meta_ad_accounts(
                access_token
            )

            for account in meta_accounts:

                if account.get("id") not in selected_ids:
                    continue

                account = dict(account)

                # Identificação da conta
                account["client_id"] = str(client_id)

                # Nome do cliente cadastrado no sistema
                account["client_name"] = (
                    client.get("name")
                    or "Cliente sem nome"
                )

                connected_accounts.append(
                    (
                        account,
                        access_token
                    )
                )

        except MetaOAuthError as exc:
            print(
                f"ERRO META NO CLIENTE {client_id}: {exc}"
            )
            continue

        except Exception as exc:
            print(
                f"ERRO AO CARREGAR META DO CLIENTE "
                f"{client_id}: {exc}"
            )
            continue

    # ========================================================
    # BUSCAR PERÍODO ATUAL + PERÍODO ANTERIOR
    # ========================================================

    period_results = []

    with ThreadPoolExecutor(max_workers=8) as executor:

        futures = [
            executor.submit(
                get_account_period_data,
                account,
                access_token,
                since,
                until,
                previous_since,
                previous_until
            )
            for account, access_token in connected_accounts
        ]

        for future in as_completed(futures):
            try:
                current, previous = future.result()
                period_results.append((current, previous))
            except Exception as exc:
                print(
                    f"ERRO AO BUSCAR COMPARATIVO META: {exc}"
                )

    # ========================================================
    # SEPARAR RESULTADOS
    # ========================================================

    results = [current for current, _ in period_results]
    previous_results = [previous for _, previous in period_results]

    # Mantém os dados do período anterior junto de cada conta.
    # Isso permite que o Overview faça a seleção de clientes no navegador
    # sem precisar consultar a Meta novamente a cada clique.
    previous_by_id = {
        str(previous.get("id")): previous
        for previous in previous_results
    }

    for account in results:
        previous = previous_by_id.get(str(account.get("id")), {})

        account["previous_spend"] = previous.get("spend", 0)
        account["previous_conversations"] = previous.get("conversations", 0)
        account["previous_impressions"] = previous.get("impressions", 0)
        account["previous_link_clicks"] = previous.get("link_clicks", 0)
        account["previous_cost_per_conversation"] = previous.get(
            "cost_per_conversation", 0
        )
        account["previous_ctr"] = previous.get("ctr", 0)
        account["previous_cpm"] = previous.get("cpm", 0)

    results.sort(
        key=lambda x: x["name"].lower()
    )

    # ========================================================
    # TOTAIS DO PERÍODO ATUAL
    # ========================================================

    total_spend = sum(
        account["spend"]
        for account in results
    )

    total_conversations = sum(
        account["conversations"]
        for account in results
    )

    total_impressions = sum(
        account["impressions"]
        for account in results
    )

    total_link_clicks = sum(
        account["link_clicks"]
        for account in results
    )

    # ========================================================
    # TOTAIS DO PERÍODO ANTERIOR
    # ========================================================

    previous_total_spend = sum(
        account["spend"]
        for account in previous_results
    )

    previous_total_conversations = sum(
        account["conversations"]
        for account in previous_results
    )

    previous_total_impressions = sum(
        account["impressions"]
        for account in previous_results
    )

    previous_total_link_clicks = sum(
        account["link_clicks"]
        for account in previous_results
    )

    # ========================================================
    # MÉTRICAS ATUAIS
    # ========================================================

    average_cost_per_conversation = (
        total_spend / total_conversations
        if total_conversations > 0
        else 0
    )

    average_ctr = (
        (
            total_link_clicks
            / total_impressions
        ) * 100
        if total_impressions > 0
        else 0
    )

    average_cpm = (
        (
            total_spend
            / total_impressions
        ) * 1000
        if total_impressions > 0
        else 0
    )

    # ========================================================
    # MÉTRICAS ANTERIORES
    # ========================================================

    previous_average_cost_per_conversation = (
        previous_total_spend / previous_total_conversations
        if previous_total_conversations > 0
        else 0
    )

    previous_average_ctr = (
        (
            previous_total_link_clicks
            / previous_total_impressions
        ) * 100
        if previous_total_impressions > 0
        else 0
    )

    previous_average_cpm = (
        (
            previous_total_spend
            / previous_total_impressions
        ) * 1000
        if previous_total_impressions > 0
        else 0
    )

    # ========================================================
    # COMPARATIVOS
    # ========================================================

    spend_change = calculate_percentage_change(
        total_spend,
        previous_total_spend
    )

    conversations_change = calculate_percentage_change(
        total_conversations,
        previous_total_conversations
    )

    cost_change = calculate_percentage_change(
        average_cost_per_conversation,
        previous_average_cost_per_conversation
    )

    ctr_change = calculate_percentage_change(
        average_ctr,
        previous_average_ctr
    )

    cpm_change = calculate_percentage_change(
        average_cpm,
        previous_average_cpm
    )

    # ========================================================
    # STATUS
    # ========================================================

    for account in results:
        account["status"] = classify_account(
            account,
            average_cost_per_conversation
        )

    # ========================================================
    # CONTAGEM
    # ========================================================

    critical_count = sum(
        1
        for account in results
        if account["status"]["class"] == "critical"
    )

    warning_count = sum(
        1
        for account in results
        if account["status"]["class"] == "warning"
    )

    healthy_count = sum(
        1
        for account in results
        if account["status"]["class"] == "healthy"
    )

    # ========================================================
    # RENDER
    # ========================================================

    return render_template(
        "index.html",
        active_page="overview",
        accounts=results,
        error=None,
        since=since,
        until=until,
        period_label=period_label,
        previous_period_label=previous_period_label,
        total_spend=total_spend,
        previous_total_spend=previous_total_spend,
        total_conversations=total_conversations,
        previous_total_conversations=previous_total_conversations,
        average_cost_per_conversation=average_cost_per_conversation,
        previous_average_cost_per_conversation=previous_average_cost_per_conversation,
        average_ctr=average_ctr,
        previous_average_ctr=previous_average_ctr,
        average_cpm=average_cpm,
        previous_average_cpm=previous_average_cpm,
        spend_change=spend_change,
        conversations_change=conversations_change,
        cost_change=cost_change,
        ctr_change=ctr_change,
        cpm_change=cpm_change,
        critical_count=critical_count,
        warning_count=warning_count,
        healthy_count=healthy_count
    )


# ============================================================
# AGENDA
# ============================================================

@app.route("/agenda")
@login_required
def agenda():

    # ========================================================
    # DATAS PADRÃO
    # ========================================================

    today = datetime.now().date()

    default_start = (
        today - timedelta(days=29)
    )

    default_end = today


    # ========================================================
    # FILTROS
    # ========================================================

    start_string = request.args.get(
        "start",
        default_start.strftime("%Y-%m-%d")
    )


    end_string = request.args.get(
        "end",
        default_end.strftime("%Y-%m-%d")
    )


    try:

        start_date = datetime.strptime(
            start_string,
            "%Y-%m-%d"
        ).date()

        end_date = datetime.strptime(
            end_string,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        start_date = default_start

        end_date = default_end

        start_string = (
            default_start.strftime("%Y-%m-%d")
        )

        end_string = (
            default_end.strftime("%Y-%m-%d")
        )


    # ========================================================
    # DADOS DA AGENDA
    # ========================================================

    dashboard = get_dashboard_data(

        start_date=start_date,

        end_date=end_date
    )


    # ========================================================
    # RENDER
    # ========================================================

    return render_template(

        "agenda.html",

        active_page="agenda",

        start_date=start_string,

        end_date=end_string,

        dashboard=dashboard,

        user_name=session.get(
            "user_name"
        ),

        user_email=session.get(
            "user_email"
        )
    )



# ============================================================
# TAREFAS
# ============================================================

def _task_current_user_id():
    return str(session.get("user_id")) if session.get("user_id") else None


def _task_is_admin():
    return session.get("user_role") == "admin"


def _task_is_gestor():
    return session.get("user_role") in {"user", "gestor"}


def _parse_task_due_date(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _get_active_users():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, email, role
                FROM users
                WHERE is_active = TRUE
                ORDER BY name
            """)
            rows = cur.fetchall()

    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "email": row[2],
            "role": row[3],
        }
        for row in rows
    ]


def _get_task(task_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    t.id,
                    t.client_id,
                    c.name,
                    t.created_by,
                    creator.name,
                    t.assigned_to,
                    assignee.name,
                    t.title,
                    t.description,
                    t.status,
                    t.priority,
                    t.visibility,
                    t.due_date,
                    t.completed_at,
                    t.created_at,
                    t.updated_at
                FROM tasks t
                JOIN clients c ON c.id = t.client_id
                JOIN users creator ON creator.id = t.created_by
                JOIN users assignee ON assignee.id = t.assigned_to
                WHERE t.id = %s
            """, (task_id,))
            row = cur.fetchone()

    if not row:
        return None

    return {
        "id": str(row[0]),
        "client_id": str(row[1]),
        "client_name": row[2],
        "created_by": str(row[3]),
        "created_by_name": row[4],
        "assigned_to": str(row[5]),
        "assigned_to_name": row[6],
        "title": row[7],
        "description": row[8],
        "status": row[9],
        "priority": row[10],
        "visibility": row[11],
        "due_date": row[12],
        "completed_at": row[13],
        "created_at": row[14],
        "updated_at": row[15],
    }


def _can_view_task(task):
    """
    Neste momento todos os usuários autenticados
    podem visualizar qualquer tarefa.
    """
    return bool(task)


def _can_manage_task(task):
    """
    Neste momento todos os usuários autenticados
    podem editar, concluir, alterar status e excluir
    qualquer tarefa.
    """
    return bool(task)


def _list_tasks():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    t.id,
                    t.client_id,
                    c.name,
                    t.created_by,
                    t.assigned_to,
                    u.name,
                    t.title,
                    t.description,
                    t.status,
                    t.priority,
                    t.visibility,
                    t.due_date,
                    t.completed_at,
                    t.created_at,
                    t.updated_at
                FROM tasks t
                JOIN clients c ON c.id = t.client_id
                JOIN users u ON u.id = t.assigned_to
                ORDER BY
                    CASE t.status
                        WHEN 'in_progress' THEN 1
                        WHEN 'pending' THEN 2
                        WHEN 'completed' THEN 3
                        ELSE 4
                    END,
                    CASE t.priority
                        WHEN 'urgent' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    t.due_date NULLS LAST,
                    t.created_at DESC
            """)
            rows = cur.fetchall()

    current_user = _task_current_user_id()
    tasks = []

    for row in rows:
        task = {
            "id": str(row[0]),
            "client_id": str(row[1]),
            "client_name": row[2],
            "created_by": str(row[3]),
            "assigned_to": str(row[4]),
            "assigned_to_name": row[5],
            "title": row[6],
            "description": row[7],
            "status": row[8],
            "priority": row[9],
            "visibility": row[10],
            "due_date": (
                row[11].strftime("%Y-%m-%dT%H:%M")
                if row[11]
                else ""
            ),
            "due_date_br": (
                row[11].strftime("%d/%m/%Y %H:%M")
                if row[11]
                else "Sem prazo"
            ),
            "completed_at": row[12],
            "created_at": row[13],
            "updated_at": row[14],
        }

        if (
            _task_is_admin()
            or task["visibility"] == "public"
            or current_user in {
                task["created_by"],
                task["assigned_to"],
            }
        ):
            tasks.append(task)

    return tasks


def _get_task_form_data():
    return {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip() or None,
        "client_id": request.form.get("client_id", "").strip(),
        "assigned_to": request.form.get("assigned_to", "").strip(),
        "priority": request.form.get("priority", "medium"),
        "visibility": request.form.get("visibility", "public"),
        "due_date": _parse_task_due_date(
            request.form.get("due_date", "").strip()
        ),
    }


def _validate_task_data(data):
    if not data["title"]:
        return "Informe o título da tarefa."

    if not data["client_id"]:
        return "Selecione um cliente."

    if not data["assigned_to"]:
        return "Selecione um responsável."

    if data["priority"] not in {"low", "medium", "high", "urgent"}:
        return "Prioridade inválida."

    if data["visibility"] not in {"public", "private"}:
        return "Visibilidade inválida."

    return None


@app.route("/tarefas")
@login_required
def tarefas():
    try:
        tasks = _list_tasks()
        clients = list_clients()
        users = _get_active_users()
        error = None
    except Exception as exc:
        print(f"ERRO AO LISTAR TAREFAS: {exc}")
        tasks = []
        clients = []
        users = []
        error = "Não foi possível carregar as tarefas. Tente novamente."

    return render_template(
        "tasks.html",
        active_page="tarefas",
        tasks=tasks,
        clients=clients,
        users=users,
        error=error,
        message=request.args.get("message"),
    )


@app.route("/tarefas/criar", methods=["POST"])
@login_required
def criar_tarefa():
    data = _get_task_form_data()

    data = _get_task_form_data()

    error = _validate_task_data(data)

    error = _validate_task_data(data)

    if error:
        return redirect(url_for("tarefas", message=error))

    if not get_client(data["client_id"]):
        return redirect(
            url_for("tarefas", message="Cliente não encontrado.")
        )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id
                FROM users
                WHERE id = %s
                  AND is_active = TRUE
                LIMIT 1
            """, (data["assigned_to"],))

            if not cur.fetchone():
                return redirect(
                    url_for("tarefas", message="Responsável inválido.")
                )

            cur.execute("""
                INSERT INTO tasks (
                    client_id,
                    created_by,
                    assigned_to,
                    title,
                    description,
                    status,
                    priority,
                    visibility,
                    due_date
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    'pending', %s, %s, %s
                )
            """, (
                data["client_id"],
                _task_current_user_id(),
                data["assigned_to"],
                data["title"],
                data["description"],
                data["priority"],
                data["visibility"],
                data["due_date"],
            ))

        conn.commit()

    return redirect(
        url_for("tarefas", message="Tarefa criada com sucesso.")
    )


@app.route("/tarefas/<uuid:task_id>/editar", methods=["GET", "POST"])
@login_required
def editar_tarefa(task_id):
    task = _get_task(task_id)

    if not task:
        return redirect(
            url_for("tarefas", message="Tarefa não encontrada.")
        )

    if not _can_view_task(task):
        return redirect(
            url_for(
                "tarefas",
                message="Você não tem acesso a esta tarefa."
            )
        )

    if not _can_manage_task(task):
        return redirect(
            url_for(
                "tarefas",
                message="Você não tem permissão para editar esta tarefa."
            )
        )

    clients = list_clients()
    users = _get_active_users()
    error = None

    if request.method == "POST":
        data = _get_task_form_data()

        if not _task_is_admin():
            data["assigned_to"] = task["assigned_to"]

        error = _validate_task_data(data)

        if not error:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE tasks
                        SET
                            client_id = %s,
                            assigned_to = %s,
                            title = %s,
                            description = %s,
                            priority = %s,
                            visibility = %s,
                            due_date = %s,
                            updated_at = now()
                        WHERE id = %s
                    """, (
                        data["client_id"],
                        data["assigned_to"],
                        data["title"],
                        data["description"],
                        data["priority"],
                        data["visibility"],
                        data["due_date"],
                        task_id,
                    ))

                conn.commit()

            return redirect(
                url_for(
                    "tarefas",
                    message="Tarefa atualizada com sucesso."
                )
            )

    return render_template(
        "task_form.html",
        active_page="tarefas",
        task=task,
        clients=clients,
        users=users,
        error=error,
        is_edit=True,
    )


@app.route("/tarefas/<uuid:task_id>/status", methods=["POST"])
@login_required
def alterar_status_tarefa(task_id):
    task = _get_task(task_id)

    if not task:
        return redirect(
            url_for("tarefas", message="Tarefa não encontrada.")
        )

    if not _can_manage_task(task):
        return redirect(
            url_for(
                "tarefas",
                message="Você não tem permissão para alterar esta tarefa."
            )
        )

    status = request.form.get("status", "").strip()

    if status not in {"pending", "in_progress", "completed"}:
        return redirect(
            url_for("tarefas", message="Status de tarefa inválido.")
        )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if status == "completed":
                cur.execute("""
                    UPDATE tasks
                    SET
                        status = 'completed',
                        completed_at = now(),
                        updated_at = now()
                    WHERE id = %s
                """, (task_id,))
            else:
                cur.execute("""
                    UPDATE tasks
                    SET
                        status = %s,
                        completed_at = NULL,
                        updated_at = now()
                    WHERE id = %s
                """, (status, task_id))

        conn.commit()

    return redirect(
        url_for("tarefas", message="Status atualizado com sucesso.")
    )


@app.route("/tarefas/<uuid:task_id>/concluir", methods=["POST"])
@login_required
def concluir_tarefa(task_id):
    task = _get_task(task_id)

    if not task:
        return redirect(
            url_for("tarefas", message="Tarefa não encontrada.")
        )

    if not _can_manage_task(task):
        return redirect(
            url_for(
                "tarefas",
                message="Você não tem permissão para concluir esta tarefa."
            )
        )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tasks
                SET
                    status = 'completed',
                    completed_at = now(),
                    updated_at = now()
                WHERE id = %s
            """, (task_id,))

        conn.commit()

    return redirect(
        url_for("tarefas", message="Tarefa concluída com sucesso.")
    )


@app.route("/tarefas/<uuid:task_id>/excluir", methods=["POST"])
@login_required
def excluir_tarefa(task_id):
    task = _get_task(task_id)

    if not task:
        return redirect(
            url_for("tarefas", message="Tarefa não encontrada.")
        )

    if not _can_manage_task(task):
        return redirect(
            url_for(
                "tarefas",
                message="Você não tem permissão para excluir esta tarefa."
            )
        )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tasks WHERE id = %s",
                (task_id,)
            )

        conn.commit()

    return redirect(
        url_for("tarefas", message="Tarefa excluída com sucesso.")
    )



# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )
