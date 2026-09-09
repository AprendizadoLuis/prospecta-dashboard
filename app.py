
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
    jsonify,
)

from services.agenda_service import get_dashboard_data

from services.auth_service import (
    authenticate_user,
    get_db_connection,
    update_user_avatar
)

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
from services.report_service import (
    get_client_report_data,
    calculate_period_comparison,
    get_quick_periods,
    get_period_display_name,
    aggregate_accounts_metrics,
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
                session["user_avatar_url"] = user["avatar_url"]

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


@app.route("/perfil/avatar/upload", methods=["POST"])
@login_required
def upload_user_avatar():

    # ========================================================
    # VALIDAR ARQUIVO
    # ========================================================

    if "file" not in request.files:

        return jsonify({
            "ok": False,
            "error": "Nenhum arquivo enviado."
        }), 400

    file = request.files["file"]

    if not file or file.filename == "":

        return jsonify({
            "ok": False,
            "error": "Arquivo sem nome."
        }), 400


    # ========================================================
    # VALIDAR TIPO
    # ========================================================

    allowed_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png"
    }

    content_type = file.content_type or ""

    if content_type not in allowed_types:

        return jsonify({
            "ok": False,
            "error": "Apenas JPG ou PNG são permitidos."
        }), 400


    # ========================================================
    # VALIDAR TAMANHO
    # ========================================================

    MAX_SIZE = 2 * 1024 * 1024

    file.seek(0, 2)

    file_size = file.tell()

    file.seek(0)

    if file_size > MAX_SIZE:

        return jsonify({
            "ok": False,
            "error": "A imagem deve ter no máximo 2 MB."
        }), 400


    # ========================================================
    # SUPABASE
    # ========================================================

    supabase_url = os.getenv(
        "SUPABASE_URL",
        ""
    ).rstrip("/")

    service_role_key = os.getenv(
        "SUPABASE_SERVICE_ROLE_KEY",
        ""
    )


    if not supabase_url or not service_role_key:

        print(
            "ERRO: SUPABASE_URL ou "
            "SUPABASE_SERVICE_ROLE_KEY não configurado."
        )

        return jsonify({
            "ok": False,
            "error": "Storage não configurado no servidor."
        }), 500


    # ========================================================
    # ARQUIVO
    # ========================================================

    bucket = "client-avatars"

    extension = allowed_types[content_type]

    user_id = session.get("user_id")

    file_path = (
        f"users/{user_id}/"
        f"avatar-{secrets.token_hex(8)}{extension}"
    )


    # ========================================================
    # UPLOAD
    # ========================================================

    upload_url = (
        f"{supabase_url}"
        f"/storage/v1/object/"
        f"{bucket}/{file_path}"
    )

    print(
        f"Uploadando avatar do usuário para: {file_path}"
    )


    try:

        response = requests.put(
            upload_url,
            headers={
                "apikey": service_role_key,
                "Authorization": (
                    f"Bearer {service_role_key}"
                ),
                "Content-Type": content_type
            },
            data=file.read(),
            timeout=30
        )


        if response.status_code not in (200, 201):

            print(
                f"ERRO no upload: "
                f"{response.status_code}"
            )

            print(
                f"Resposta: {response.text}"
            )

            return jsonify({
                "ok": False,
                "error": "Erro ao enviar a foto para o Storage."
            }), 500


        # ====================================================
        # URL PÚBLICA
        # ====================================================

        public_url = (
            f"{supabase_url}"
            f"/storage/v1/object/public/"
            f"{bucket}/{file_path}"
        )


        # ====================================================
        # SALVAR NO BANCO
        # ====================================================

        update_user_avatar(
            user_id,
            public_url
        )


        # Atualizar sessão imediatamente
        session["user_avatar_url"] = public_url


        print(
            f"Avatar atualizado com sucesso: "
            f"{public_url}"
        )


        return jsonify({
            "ok": True,
            "public_url": public_url
        })


    except requests.RequestException as exc:

        print(
            "ERRO DE COMUNICAÇÃO COM O SUPABASE:"
        )

        print(exc)

        return jsonify({
            "ok": False,
            "error": (
                "Não foi possível comunicar "
                "com o Supabase Storage."
            )
        }), 500


    except Exception as exc:

        print(
            "ERRO AO FAZER UPLOAD DO AVATAR:"
        )

        print(exc)

        return jsonify({
            "ok": False,
            "error": (
                "Não foi possível salvar "
                "a foto do perfil."
            )
        }), 500

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
        "avatar_url": request.form.get("avatar_url", "").strip() or None,
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

@app.route("/clientes")
@login_required
def clientes():
    try:
        clients = list_clients()
        error = None
    except Exception as exc:
        print(f"ERRO AO LISTAR CLIENTES: {exc}")
        clients = []
        error = "Não foi possível carregar os clientes. Tente novamente."

    return render_template(
        "clientes.html",
        active_page="clientes",
        clients=clients,
        error=error,
        message=request.args.get("message"),
    )
    
# ============================================================
# RELATÓRIO INDIVIDUAL DO CLIENTE
# ============================================================

@app.route("/relatorios/cliente/<uuid:client_id>")
@login_required
def relatorio_cliente(client_id):

    # ========================================================
    # CLIENTE
    # ========================================================

    client = get_client(client_id)

    if not client:
        return redirect(
            url_for("relatorios")
        )


    # ========================================================
    # DATAS
    # ========================================================

    default_since, default_until = get_default_dates()

    since = request.args.get(
        "since",
        default_since
    ).strip()

    until = request.args.get(
        "until",
        default_until
    ).strip()


    if not validate_dates(
        since,
        until
    ):
        since = default_since
        until = default_until


    # ========================================================
    # RELATÓRIO
    # ========================================================

    report = None
    meta_status = "not_connected"
    meta_error = None


    try:

        report = get_complete_report_data(
            client_id,
            since,
            until
        )

        meta_status = "connected"


    except Exception as exc:

        print(
            "ERRO AO GERAR RELATÓRIO "
            f"{client_id}: {exc}"
        )

        import traceback
        traceback.print_exc()


        error_message = str(exc)


        if "conexão Meta Ads" in error_message:
            meta_status = "not_connected"

        elif "contas de anúncio selecionadas" in error_message:
            meta_status = "no_account"

        else:
            meta_status = "error"

            meta_error = (
                "Não foi possível carregar "
                "os dados da Meta Ads."
            )


    # ========================================================
    # DADOS PARA O TEMPLATE
    # ========================================================

    if report:

        metrics = report.get(
            "metrics",
            {}
        )

        previous_metrics = report.get(
            "previous_metrics",
            {}
        )

        comparison = report.get(
            "comparison",
            {}
        )

        campaigns = report.get(
            "campaigns",
            []
        )

        ads = report.get(
            "ads",
            []
        )

        daily = report.get(
            "daily",
            []
        )

        demographics = report.get(
            "demographics",
            {}
        )

        platforms = report.get(
            "platforms",
            {}
        )

        video = report.get(
            "video",
            {}
        )

    else:

        metrics = {}
        previous_metrics = {}
        comparison = {}
        campaigns = []
        ads = []
        daily = []

        demographics = {
            "age": [],
            "gender": []
        }

        platforms = {
            "instagram": 0,
            "facebook": 0
        }

        video = {
            "video_3s": 0,
            "video_25": 0,
            "video_50": 0,
            "video_75": 0,
            "video_95": 0
        }


    # ========================================================
    # PERÍODO
    # ========================================================

    period_label = (
        f"{format_date_br(since)} - "
        f"{format_date_br(until)}"
    )


    # ========================================================
    # RENDER
    # ========================================================

    return render_template(

        "relatorio_cliente.html",

        active_page="relatorios",

        client=client,

        report=report,

        metrics=metrics,

        previous_metrics=previous_metrics,

        comparison=comparison,

        campaigns=campaigns,

        ads=ads,

        daily=daily,

        demographics=demographics,

        platforms=platforms,

        video=video,

        since=since,

        until=until,

        period_label=period_label,

        meta_status=meta_status,

        meta_error=meta_error
    )

@app.route("/clientes/novo", methods=["GET", "POST"])
@login_required
def novo_cliente():

    client = {
        "status": "draft",
        "avatar_url": None,
    }

    error = None

    if request.method == "POST":

        client = get_client_form_data()

        error = validate_client_form(client)

        if not error:

            try:

                saved_client_id = save_client(client)

                if not saved_client_id:
                    raise RuntimeError(
                        "Não foi possível obter o ID do cliente criado."
                    )

                return redirect(
                    url_for(
                        "editar_cliente",
                        client_id=saved_client_id,
                        meta_message="Cliente criado com sucesso."
                    )
                )

            except Exception as exc:

                print(
                    f"ERRO AO CRIAR CLIENTE: {exc}"
                )

                error = (
                    "Não foi possível criar o cliente. "
                    "Verifique os dados e tente novamente."
                )

    return render_template(
        "cliente_form.html",
        active_page="clientes",
        client=client,
        error=error,
        is_edit=False,
        gestores=list_users_for_assignment(),
        supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
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
                message="Cliente não encontrado."
            )
        )

    error = None

    if request.method == "POST":

        client = get_client_form_data()
        client["id"] = str(client_id)

        error = validate_client_form(client)

        if not error:

            try:

                print("========== ATUALIZAÇÃO CLIENTE ==========")
                print("CLIENTE:", client_id)
                print("AVATAR URL:", client.get("avatar_url"))
                print("CONTENT TYPE:", request.content_type)
                print("=========================================")

                save_client(
                    client,
                    client_id
                )

                return redirect(
                    url_for(
                        "clientes",
                        message="Cliente atualizado com sucesso."
                    )
                )

            except Exception as exc:

                print(
                    f"ERRO AO ATUALIZAR CLIENTE: {exc}"
                )

                error = (
                    "Não foi possível atualizar o cliente. "
                    "Tente novamente."
                )

    return render_template(
        "cliente_form.html",
        active_page="clientes",
        client=client,
        error=error,
        is_edit=True,
        gestores=list_users_for_assignment(),
        meta_connection=get_client_connection(client_id),
        meta_message=request.args.get("meta_message"),
        meta_error=request.args.get("meta_error"),
        supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
    )

@app.route("/clientes/<uuid:client_id>/avatar/upload", methods=["POST"])
@login_required
def upload_avatar(client_id):
    """
    Recebe arquivo de foto do cliente e faz upload direto ao Supabase.
    
    O upload é servidor-para-servidor (Flask→Supabase),
    não navegador-para-Supabase, garantindo segurança.
    """

    client = get_client(client_id)

    if not client:
        return jsonify({
            "ok": False,
            "error": "Cliente não encontrado."
        }), 404

    # Validar arquivo
    if "file" not in request.files:
        return jsonify({
            "ok": False,
            "error": "Nenhum arquivo enviado."
        }), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({
            "ok": False,
            "error": "Arquivo sem nome."
        }), 400

    # Validar tipo
    allowed_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    content_type = file.content_type or ""
    if content_type not in allowed_types:
        return jsonify({
            "ok": False,
            "error": "Apenas JPG, PNG ou WEBP são permitidos."
        }), 400

    # Validar tamanho (5 MB)
    MAX_SIZE = 5 * 1024 * 1024
    file.seek(0, 2)  # Ir para o final
    file_size = file.tell()
    file.seek(0)  # Voltar para o início

    if file_size > MAX_SIZE:
        return jsonify({
            "ok": False,
            "error": "Arquivo maior que 5 MB."
        }), 400

    # Credenciais do Supabase
    supabase_url = os.getenv(
        "SUPABASE_URL",
        ""
    ).rstrip("/")

    service_role_key = os.getenv(
        "SUPABASE_SERVICE_ROLE_KEY",
        ""
    )

    if not supabase_url or not service_role_key:
        print(
            "ERRO: SUPABASE_URL ou "
            "SUPABASE_SERVICE_ROLE_KEY não configurado."
        )

        return jsonify({
            "ok": False,
            "error": "Storage não configurado no servidor."
        }), 500

    bucket = "client-avatars"
    extension = allowed_types[content_type]

    # Nome único
    file_path = (
        f"clients/{client_id}/"
        f"avatar-{secrets.token_hex(8)}{extension}"
    )

    # URL de upload no Supabase
    upload_url = (
        f"{supabase_url}"
        f"/storage/v1/object/{bucket}/{file_path}"
    )

    print(f"Uploadando para: {file_path}")

    try:
        # Fazer upload direto ao Supabase
        response = requests.put(
            upload_url,
            headers={
                "apikey": service_role_key,
                "Content-Type": content_type,
            },
            data=file.read(),
            timeout=30,
        )

        if response.status_code != 200:
            print(f"ERRO no upload: {response.status_code}")
            print(f"Resposta: {response.text}")

            return jsonify({
                "ok": False,
                "error": "Erro ao enviar arquivo ao Storage."
            }), 500

        # URL pública do arquivo
        public_url = (
            f"{supabase_url}"
            f"/storage/v1/object/public/"
            f"{bucket}/{file_path}"
        )

        print(f"Upload bem-sucedido: {public_url}")

        return jsonify({
            "ok": True,
            "public_url": public_url,
            "file_path": file_path,
        })

    except requests.RequestException as exc:

        print(
            "ERRO DE COMUNICAÇÃO COM O SUPABASE:"
        )
        print(exc)

        return jsonify({
            "ok": False,
            "error": (
                "Não foi possível comunicar "
                "com o Supabase Storage."
            )
        }), 500

    except Exception as exc:

        print(f"Upload bem-sucedido: {public_url}")

        return jsonify({
            "ok": True,
            "public_url": public_url,
        }), 200

    except Exception as exc:
        print("ERRO AO FAZER UPLOAD DO AVATAR:")
        print(exc)

        return jsonify({
            "ok": False,
            "error": (
                "Não foi possível preparar "
                "o upload da foto."
            )
        }), 500


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

                # Dados do gestor responsável pelo cliente.
                "client_id":
                    account.get("client_id"),

                "responsible_user_id":
                    account.get("responsible_user_id"),

                "responsible_user_name":
                    account.get(
                        "responsible_user_name",
                        "Sem gestor"
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

            # Dados do gestor responsável pelo cliente.
            # Precisam ser preservados aqui porque esta função
            # cria um novo dicionário para as métricas da conta.
            "client_id":
                account.get("client_id"),

            "responsible_user_id":
                account.get("responsible_user_id"),

            "responsible_user_name":
                account.get(
                    "responsible_user_name",
                    "Sem gestor"
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

            # Dados do gestor responsável pelo cliente.
            # Precisam ser preservados aqui porque esta função
            # cria um novo dicionário para as métricas da conta.
            "client_id":
                account.get("client_id"),

            "responsible_user_id":
                account.get("responsible_user_id"),

            "responsible_user_name":
                account.get(
                    "responsible_user_name",
                    "Sem gestor"
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

    # Gestor selecionado no filtro do Overview.
    # Quando informado, somente os clientes vinculados a esse gestor
    # serão consultados e exibidos.
    selected_gestor = request.args.get("gestor", "").strip() or None

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
        gestores = list_users_for_assignment()
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
            healthy_count=0,
            gestores=[],
            selected_gestor=selected_gestor
        )

    # ========================================================
    # BUSCAR CONTAS DOS CLIENTES CONECTADOS
    # ========================================================

    connected_accounts = []

    for client in clients:

        # Se houver gestor selecionado, não consulta clientes
        # que não pertencem a ele. Isso também deixa o Overview
        # mais rápido porque evita chamadas desnecessárias à Meta.
        if selected_gestor:
            client_responsible_id = client.get("responsible_user_id")

            if str(client_responsible_id or "") != str(selected_gestor):
                continue

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

                # Gestor responsável pelo cliente
                account["responsible_user_id"] = client.get("responsible_user_id")
                account["responsible_user_name"] = next(
                    (
                        gestor.get("name")
                        for gestor in gestores
                        if str(gestor.get("id")) == str(client.get("responsible_user_id"))
                    ),
                    "Sem gestor"
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
        gestores=gestores,
        selected_gestor=selected_gestor,
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
# DADOS AVANÇADOS PARA RELATÓRIOS META ADS
# ============================================================

def _meta_report_request(
    endpoint,
    access_token,
    params=None,
    timeout=45
):
    """
    Faz uma requisição segura à Graph API da Meta.
    Usada exclusivamente pelos relatórios.
    """

    url = (
        f"https://graph.facebook.com/"
        f"{META_API_VERSION}/"
        f"{endpoint.lstrip('/')}"
    )

    request_params = dict(params or {})
    request_params["access_token"] = access_token

    response = requests.get(
        url,
        params=request_params,
        timeout=timeout
    )

    try:
        data = response.json()
    except Exception:
        data = {
            "error": {
                "message": "Resposta inválida da Meta."
            }
        }

    if response.status_code >= 400:
        message = (
            data.get("error", {})
            .get("message")
            or "Erro desconhecido na Meta."
        )

        raise RuntimeError(
            f"Meta API: {message}"
        )

    return data


def _meta_report_paginated(
    endpoint,
    access_token,
    params=None,
    timeout=45,
    max_pages=20
):
    """
    Busca todos os registros paginados da Meta.
    """

    url = (
        f"https://graph.facebook.com/"
        f"{META_API_VERSION}/"
        f"{endpoint.lstrip('/')}"
    )

    request_params = dict(params or {})
    request_params["access_token"] = access_token

    results = []

    for _ in range(max_pages):

        response = requests.get(
            url,
            params=request_params,
            timeout=timeout
        )

        try:
            data = response.json()
        except Exception:
            data = {}

        if response.status_code >= 400:

            message = (
                data.get("error", {})
                .get("message")
                or "Erro desconhecido na Meta."
            )

            raise RuntimeError(
                f"Meta API: {message}"
            )

        results.extend(
            data.get("data", [])
        )

        next_url = (
            data.get("paging", {})
            .get("next")
        )

        if not next_url:
            break

        url = next_url
        request_params = {}

    return results


def _report_number(value):
    """
    Converte valores vindos da Meta em float.
    """

    try:
        return float(value or 0)
    except (
        ValueError,
        TypeError
    ):
        return 0.0


def _report_int(value):
    """
    Converte valores vindos da Meta em inteiro.
    """

    try:
        return int(
            float(value or 0)
        )
    except (
        ValueError,
        TypeError
    ):
        return 0


def _report_actions_value(
    actions,
    action_types
):
    """
    Soma valores de determinados tipos de ação.
    """

    if not actions:
        return 0

    if isinstance(action_types, str):
        action_types = {
            action_types
        }
    else:
        action_types = set(
            action_types
        )

    total = 0

    for action in actions:

        action_type = (
            action.get("action_type")
            or ""
        )

        if action_type in action_types:
            total += _report_number(
                action.get("value")
            )

    return total


def _report_conversations(
    actions
):
    """
    Identifica conversas iniciadas.
    """

    return _report_actions_value(
        actions,
        MESSAGING_CONVERSATION_ACTION
    )


def _report_link_clicks(
    actions
):
    """
    Identifica cliques no link.
    """

    return _report_actions_value(
        actions,
        {
            "link_click",
            "inline_link_click"
        }
    )


def _report_video_value(
    value
):
    """
    Os campos de vídeo da Meta normalmente
    retornam uma lista de ações.
    """

    if isinstance(value, list):

        total = 0

        for item in value:
            total += _report_number(
                item.get("value")
            )

        return total

    return _report_number(value)


def _report_insights(
    account_id,
    access_token,
    since,
    until,
    *,
    level=None,
    breakdowns=None,
    time_increment=None,
    fields=None
):
    """
    Consulta genérica de Insights para o relatório.
    """

    default_fields = (
    "spend,"
    "impressions,"
    "reach,"
    "clicks,"
    "inline_link_clicks,"
    "ctr,"
    "cpm,"
    "frequency,"
    "actions,"
    "video_p25_watched_actions,"
    "video_p50_watched_actions,"
    "video_p75_watched_actions,"
    "video_p95_watched_actions"
    )

    params = {
        "fields": fields or default_fields,
        "time_range": (
            f'{{"since":"{since}",'
            f'"until":"{until}"}}'
        ),
        "limit": 500
    }

    if level:
        params["level"] = level

    if breakdowns:
        params["breakdowns"] = breakdowns

    if time_increment:
        params["time_increment"] = time_increment

    return _meta_report_paginated(
        f"{account_id}/insights",
        access_token,
        params=params
    )


def _report_build_metrics(
    rows
):
    """
    Consolida diversas linhas de Insights.
    """

    spend = 0
    impressions = 0
    reach = 0
    clicks = 0
    link_clicks = 0
    conversations = 0

    comments = 0
    shares = 0
    saves = 0

    video_3s = 0
    video_25 = 0
    video_50 = 0
    video_75 = 0
    video_95 = 0

    for row in rows:

        spend += _report_number(
            row.get("spend")
        )

        impressions += _report_int(
            row.get("impressions")
        )

        reach += _report_int(
            row.get("reach")
        )

        clicks += _report_int(
            row.get("clicks")
        )

        link_clicks += _report_int(
            row.get("inline_link_clicks")
        )

        actions = row.get(
            "actions",
            []
        )

        conversations += _report_conversations(
            actions
        )

        comments += _report_actions_value(
            actions,
            {
                "comment",
                "post_comment"
            }
        )

        shares += _report_actions_value(
            actions,
            {
                "post",
                "share"
            }
        )

        saves += _report_actions_value(
            actions,
            {
                "onsite_conversion.post_save",
                "post_save"
            }
        )

        # A Meta não aceita mais o campo específico de 3 segundos.
        # Para manter essa métrica no relatório, usamos a ação
        # video_view dentro de actions.
        video_3s += _report_actions_value(
            actions,
            "video_view"
        )

        video_25 += _report_video_value(
            row.get(
                "video_p25_watched_actions"
            )
        )

        video_50 += _report_video_value(
            row.get(
                "video_p50_watched_actions"
            )
        )

        video_75 += _report_video_value(
            row.get(
                "video_p75_watched_actions"
            )
        )

        video_95 += _report_video_value(
            row.get(
                "video_p95_watched_actions"
            )
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

    cost_per_conversation = (
        spend
        / conversations
        if conversations > 0
        else 0
    )

    frequency = (
        impressions
        / reach
        if reach > 0
        else 0
    )

    return {
        "spend": spend,
        "impressions": impressions,
        "reach": reach,
        "clicks": clicks,
        "link_clicks": link_clicks,
        "conversations": conversations,
        "cost_per_conversation": cost_per_conversation,
        "ctr": ctr,
        "cpm": cpm,
        "frequency": frequency,

        "comments": comments,
        "shares": shares,
        "saves": saves,

        "video_3s": video_3s,
        "video_25": video_25,
        "video_50": video_50,
        "video_75": video_75,
        "video_95": video_95
    }


def _report_campaigns(
    account_id,
    access_token,
    since,
    until
):
    """
    Campanhas em destaque.
    """

    fields = (
        "campaign_id,"
        "campaign_name,"
        "spend,"
        "impressions,"
        "reach,"
        "clicks,"
        "inline_link_clicks,"
        "actions"
    )

    rows = _report_insights(
        account_id,
        access_token,
        since,
        until,
        level="campaign",
        fields=fields
    )

    campaigns = []

    for row in rows:

        actions = row.get(
            "actions",
            []
        )

        conversations = (
            _report_conversations(
                actions
            )
        )

        spend = _report_number(
            row.get("spend")
        )

        cost = (
            spend / conversations
            if conversations > 0
            else 0
        )

        campaigns.append({
            "id": row.get(
                "campaign_id"
            ),
            "name": (
                row.get(
                    "campaign_name"
                )
                or "Campanha sem nome"
            ),
            "spend": spend,
            "conversations": conversations,
            "cost_per_conversation": cost,
            "impressions": _report_int(
                row.get("impressions")
            ),
            "reach": _report_int(
                row.get("reach")
            )
        })

    campaigns.sort(
        key=lambda item: (
            item["conversations"],
            item["spend"]
        ),
        reverse=True
    )

    return campaigns[:20]


def _report_ads(
    account_id,
    access_token,
    since,
    until,
    limit=30
):
    """
    Anúncios em destaque.
    """

    fields = (
        "ad_id,"
        "ad_name,"
        "adset_id,"
        "adset_name,"
        "campaign_id,"
        "campaign_name,"
        "spend,"
        "impressions,"
        "reach,"
        "clicks,"
        "inline_link_clicks,"
        "actions"
    )

    rows = _report_insights(
        account_id,
        access_token,
        since,
        until,
        level="ad",
        fields=fields
    )

    ads = []

    for row in rows:

        actions = row.get(
            "actions",
            []
        )

        conversations = (
            _report_conversations(
                actions
            )
        )

        spend = _report_number(
            row.get("spend")
        )

        cost = (
            spend / conversations
            if conversations > 0
            else 0
        )

        ads.append({
            "id": row.get("ad_id"),
            "name": (
                row.get("ad_name")
                or "Anúncio sem nome"
            ),
            "adset_name": (
                row.get("adset_name")
                or "Conjunto sem nome"
            ),
            "campaign_name": (
                row.get("campaign_name")
                or ""
            ),
            "spend": spend,
            "conversations": conversations,
            "cost_per_conversation": cost,
            "thumbnail_url": None
        })

    ads.sort(
        key=lambda item: (
            item["conversations"],
            item["spend"]
        ),
        reverse=True
    )

    return ads[:limit]


def _report_ad_thumbnails(
    ads,
    access_token
):
    """
    Tenta recuperar miniaturas dos anúncios.
    Se a Meta não disponibilizar a imagem,
    mantém o anúncio normalmente.
    """

    for ad in ads:

        ad_id = ad.get("id")

        if not ad_id:
            continue

        try:

            data = _meta_report_request(
                ad_id,
                access_token,
                params={
                    "fields": (
                        "creative{"
                        "thumbnail_url,"
                        "image_url"
                        "}"
                    )
                }
            )

            creative = (
                data.get("creative")
                or {}
            )

            ad["thumbnail_url"] = (
                creative.get(
                    "thumbnail_url"
                )
                or creative.get(
                    "image_url"
                )
            )

        except Exception as exc:

            print(
                "AVISO: não foi possível "
                f"obter thumbnail do anúncio "
                f"{ad_id}: {exc}"
            )

    return ads


def _report_daily(
    account_id,
    access_token,
    since,
    until
):
    """
    Dados diários para o gráfico
    de conversas por data.
    """

    fields = (
        "spend,"
        "impressions,"
        "reach,"
        "actions"
    )

    rows = _report_insights(
        account_id,
        access_token,
        since,
        until,
        time_increment=1,
        fields=fields
    )

    daily = []

    for row in rows:

        actions = row.get(
            "actions",
            []
        )

        daily.append({
            "date": row.get(
                "date_start"
            ),
            "spend": _report_number(
                row.get("spend")
            ),
            "impressions": _report_int(
                row.get("impressions")
            ),
            "reach": _report_int(
                row.get("reach")
            ),
            "conversations": _report_conversations(
                actions
            )
        })

    daily.sort(
        key=lambda item: (
            item.get("date")
            or ""
        )
    )

    return daily


def _report_demographics(
    account_id,
    access_token,
    since,
    until
):
    """
    Dados de idade e gênero.
    """

    age_fields = (
        "spend,"
        "impressions,"
        "reach,"
        "actions"
    )

    age_rows = _report_insights(
        account_id,
        access_token,
        since,
        until,
        breakdowns="age",
        fields=age_fields
    )

    gender_rows = _report_insights(
        account_id,
        access_token,
        since,
        until,
        breakdowns="gender",
        fields=age_fields
    )

    ages = []

    for row in age_rows:

        ages.append({
            "age": (
                row.get("age")
                or "Desconhecido"
            ),
            "conversations": (
                _report_conversations(
                    row.get(
                        "actions",
                        []
                    )
                )
            ),
            "spend": _report_number(
                row.get("spend")
            )
        })

    genders = []

    for row in gender_rows:

        genders.append({
            "gender": (
                row.get("gender")
                or "Desconhecido"
            ),
            "conversations": (
                _report_conversations(
                    row.get(
                        "actions",
                        []
                    )
                )
            ),
            "spend": _report_number(
                row.get("spend")
            )
        })

    age_totals = {}

    for item in ages:

        key = item["age"]

        age_totals.setdefault(
            key,
            0
        )

        age_totals[key] += (
            item["conversations"]
        )

    gender_totals = {}

    for item in genders:

        key = item["gender"]

        gender_totals.setdefault(
            key,
            0
        )

        gender_totals[key] += (
            item["conversations"]
        )

    return {
        "age": [
            {
                "label": key,
                "value": value
            }
            for key, value
            in age_totals.items()
        ],
        "gender": [
            {
                "label": key,
                "value": value
            }
            for key, value
            in gender_totals.items()
        ]
    }


def _report_platforms(
    account_id,
    access_token,
    since,
    until
):
    """
    Separa conversas por plataforma:
    Instagram e Facebook.
    """

    fields = (
        "spend,"
        "impressions,"
        "reach,"
        "actions"
    )

    rows = _report_insights(
        account_id,
        access_token,
        since,
        until,
        breakdowns="publisher_platform",
        fields=fields
    )

    platforms = {}

    for row in rows:

        platform = (
            row.get(
                "publisher_platform"
            )
            or "unknown"
        )

        conversations = (
            _report_conversations(
                row.get(
                    "actions",
                    []
                )
            )
        )

        platforms.setdefault(
            platform,
            0
        )

        platforms[platform] += (
            conversations
        )

    return {
        "instagram": platforms.get(
            "instagram",
            0
        ),
        "facebook": platforms.get(
            "facebook",
            0
        )
    }


def _report_video_metrics(
    account_id,
    access_token,
    since,
    until
):
    """
    Funil de retenção de vídeos.
    """

    fields = (
        "actions,"
        "video_p25_watched_actions,"
        "video_p50_watched_actions,"
        "video_p75_watched_actions,"
        "video_p95_watched_actions,"
        "spend,"
        "impressions"
    )

    rows = _report_insights(
        account_id,
        access_token,
        since,
        until,
        fields=fields
    )

    metrics = _report_build_metrics(
        rows
    )

    return {
        "video_3s": metrics["video_3s"],
        "video_25": metrics["video_25"],
        "video_50": metrics["video_50"],
        "video_75": metrics["video_75"],
        "video_95": metrics["video_95"]
    }


def _report_account_data(
    account,
    access_token,
    since,
    until
):
    """
    Monta todos os dados necessários
    para uma conta de anúncios.
    """

    account_id = account["id"]

    # --------------------------------------------
    # MÉTRICAS GERAIS
    # --------------------------------------------

    general_rows = _report_insights(
        account_id,
        access_token,
        since,
        until
    )

    metrics = _report_build_metrics(
        general_rows
    )

    # --------------------------------------------
    # CAMPANHAS
    # --------------------------------------------

    campaigns = _report_campaigns(
        account_id,
        access_token,
        since,
        until
    )

    # --------------------------------------------
    # ANÚNCIOS
    # --------------------------------------------

    ads = _report_ads(
        account_id,
        access_token,
        since,
        until
    )

    # --------------------------------------------
    # MINIATURAS
    # --------------------------------------------

    ads = _report_ad_thumbnails(
        ads,
        access_token
    )

    # --------------------------------------------
    # DADOS POR DIA
    # --------------------------------------------

    daily = _report_daily(
        account_id,
        access_token,
        since,
        until
    )

    # --------------------------------------------
    # DEMOGRAFIA
    # --------------------------------------------

    demographics = _report_demographics(
        account_id,
        access_token,
        since,
        until
    )

    # --------------------------------------------
    # PLATAFORMAS
    # --------------------------------------------

    platforms = _report_platforms(
        account_id,
        access_token,
        since,
        until
    )

    # --------------------------------------------
    # VÍDEOS
    # --------------------------------------------

    video = _report_video_metrics(
        account_id,
        access_token,
        since,
        until
    )

    return {
        "account": account,
        "metrics": metrics,
        "campaigns": campaigns,
        "ads": ads,
        "daily": daily,
        "demographics": demographics,
        "platforms": platforms,
        "video": video
    }


def _report_merge_account_data(
    account_reports
):
    """
    Consolida os dados quando o cliente
    possui mais de uma conta Meta.
    """

    if not account_reports:
        return {
            "metrics": _report_build_metrics([]),
            "campaigns": [],
            "ads": [],
            "daily": [],
            "demographics": {
                "age": [],
                "gender": []
            },
            "platforms": {
                "instagram": 0,
                "facebook": 0
            },
            "video": {
                "video_3s": 0,
                "video_25": 0,
                "video_50": 0,
                "video_75": 0,
                "video_95": 0
            }
        }

    # --------------------------------------------
    # MÉTRICAS
    # --------------------------------------------

    metric_rows = []

    for report in account_reports:

        metrics = report.get(
            "metrics",
            {}
        )

        metric_rows.append({
            "spend": metrics.get(
                "spend",
                0
            ),
            "impressions": metrics.get(
                "impressions",
                0
            ),
            "reach": metrics.get(
                "reach",
                0
            ),
            "clicks": metrics.get(
                "clicks",
                0
            ),
            "inline_link_clicks": metrics.get(
                "link_clicks",
                0
            ),
            "actions": [{
                "action_type":
                    MESSAGING_CONVERSATION_ACTION,
                "value":
                    metrics.get(
                        "conversations",
                        0
                    )
            }]
        })

    metrics = _report_build_metrics(
        metric_rows
    )

    # --------------------------------------------
    # CAMPANHAS
    # --------------------------------------------

    campaigns_by_id = {}

    for report in account_reports:

        for campaign in report.get(
            "campaigns",
            []
        ):

            key = (
                campaign.get("id")
                or campaign.get("name")
            )

            if key not in campaigns_by_id:

                campaigns_by_id[key] = dict(
                    campaign
                )

            else:

                existing = (
                    campaigns_by_id[key]
                )

                existing["spend"] += (
                    campaign.get(
                        "spend",
                        0
                    )
                )

                existing["conversations"] += (
                    campaign.get(
                        "conversations",
                        0
                    )
                )

                if existing["conversations"] > 0:

                    existing[
                        "cost_per_conversation"
                    ] = (
                        existing["spend"]
                        / existing["conversations"]
                    )

    campaigns = list(
        campaigns_by_id.values()
    )

    campaigns.sort(
        key=lambda item: (
            item.get(
                "conversations",
                0
            ),
            item.get(
                "spend",
                0
            )
        ),
        reverse=True
    )

    # --------------------------------------------
    # ANÚNCIOS
    # --------------------------------------------

    ads = []

    for report in account_reports:
        ads.extend(
            report.get(
                "ads",
                []
            )
        )

    ads.sort(
        key=lambda item: (
            item.get(
                "conversations",
                0
            ),
            item.get(
                "spend",
                0
            )
        ),
        reverse=True
    )

    # --------------------------------------------
    # DAILY
    # --------------------------------------------

    daily_map = {}

    for report in account_reports:

        for item in report.get(
            "daily",
            []
        ):

            date = item.get(
                "date"
            )

            if not date:
                continue

            if date not in daily_map:

                daily_map[date] = {
                    "date": date,
                    "spend": 0,
                    "impressions": 0,
                    "reach": 0,
                    "conversations": 0
                }

            daily_map[date]["spend"] += (
                item.get(
                    "spend",
                    0
                )
            )

            daily_map[date]["impressions"] += (
                item.get(
                    "impressions",
                    0
                )
            )

            daily_map[date]["reach"] += (
                item.get(
                    "reach",
                    0
                )
            )

            daily_map[date]["conversations"] += (
                item.get(
                    "conversations",
                    0
                )
            )

    daily = sorted(
        daily_map.values(),
        key=lambda item: item["date"]
    )

    # --------------------------------------------
    # DEMOGRAFIA
    # --------------------------------------------

    age_map = {}
    gender_map = {}

    for report in account_reports:

        demographics = report.get(
            "demographics",
            {}
        )

        for item in demographics.get(
            "age",
            []
        ):

            label = item["label"]

            age_map[label] = (
                age_map.get(
                    label,
                    0
                )
                + item["value"]
            )

        for item in demographics.get(
            "gender",
            []
        ):

            label = item["label"]

            gender_map[label] = (
                gender_map.get(
                    label,
                    0
                )
                + item["value"]
            )

    # --------------------------------------------
    # PLATAFORMAS
    # --------------------------------------------

    instagram = 0
    facebook = 0

    for report in account_reports:

        platforms = report.get(
            "platforms",
            {}
        )

        instagram += platforms.get(
            "instagram",
            0
        )

        facebook += platforms.get(
            "facebook",
            0
        )

    # --------------------------------------------
    # VÍDEOS
    # --------------------------------------------

    video = {
        "video_3s": 0,
        "video_25": 0,
        "video_50": 0,
        "video_75": 0,
        "video_95": 0
    }

    for report in account_reports:

        report_video = report.get(
            "video",
            {}
        )

        for key in video:

            video[key] += _report_number(
                report_video.get(
                    key,
                    0
                )
            )

    return {
        "metrics": metrics,

        "campaigns": campaigns[:20],

        "ads": ads[:30],

        "daily": daily,

        "demographics": {
            "age": [
                {
                    "label": key,
                    "value": value
                }
                for key, value
                in age_map.items()
            ],
            "gender": [
                {
                    "label": key,
                    "value": value
                }
                for key, value
                in gender_map.items()
            ]
        },

        "platforms": {
            "instagram": instagram,
            "facebook": facebook
        },

        "video": video
    }


def get_complete_report_data(
    client_id,
    since,
    until
):
    """
    Busca o relatório completo de um cliente.
    """

    client = get_client(
        client_id
    )

    if not client:
        raise RuntimeError(
            "Cliente não encontrado."
        )

    connection = get_client_connection(
        client_id,
        include_token=True
    )

    if (
        not connection
        or not connection.get(
            "access_token"
        )
    ):
        raise RuntimeError(
            "Este cliente não possui "
            "conexão Meta Ads configurada."
        )

    access_token = connection.get(
        "access_token"
    )

    selected_ids = (
        get_selected_ad_account_ids(
            client_id
        )
    )

    if not selected_ids:
        raise RuntimeError(
            "Este cliente não possui "
            "contas de anúncio selecionadas."
        )

    meta_accounts = (
        get_client_meta_ad_accounts(
            access_token
        )
    )

    accounts = [
        account
        for account in meta_accounts
        if account.get("id")
        in selected_ids
    ]

    if not accounts:
        raise RuntimeError(
            "Nenhuma conta de anúncio "
            "selecionada foi encontrada."
        )

    account_reports = []

    for account in accounts:

        try:

            report = _report_account_data(
                account,
                access_token,
                since,
                until
            )

            account_reports.append(
                report
            )

        except Exception as exc:

            print(
                "ERRO AO GERAR DADOS DA "
                f"CONTA {account.get('id')}: "
                f"{exc}"
            )

    if not account_reports:

        raise RuntimeError(
            "Não foi possível obter "
            "dados da Meta para este cliente."
        )

    merged = _report_merge_account_data(
        account_reports
    )

    # --------------------------------------------
    # PERÍODO ANTERIOR
    # --------------------------------------------

    previous_since, previous_until = (
        get_previous_period(
            since,
            until
        )
    )

    previous_account_reports = []

    for account in accounts:

        try:

            previous_report = (
                _report_account_data(
                    account,
                    access_token,
                    previous_since,
                    previous_until
                )
            )

            previous_account_reports.append(
                previous_report
            )

        except Exception as exc:

            print(
                "AVISO: erro ao buscar "
                f"período anterior: {exc}"
            )

    previous = _report_merge_account_data(
        previous_account_reports
    )

    current_metrics = merged[
        "metrics"
    ]

    previous_metrics = previous[
        "metrics"
    ]

    comparison = (
        calculate_period_comparison(
            current_metrics,
            previous_metrics
        )
    )

    return {
        "client": client,

        "connection": connection,

        "accounts": accounts,

        "metrics": current_metrics,

        "previous_metrics": previous_metrics,

        "comparison": comparison,

        "campaigns": merged[
            "campaigns"
        ],

        "ads": merged[
            "ads"
        ],

        "daily": merged[
            "daily"
        ],

        "demographics": merged[
            "demographics"
        ],

        "platforms": merged[
            "platforms"
        ],

        "video": merged[
            "video"
        ],

        "since": since,

        "until": until,

        "previous_since": (
            previous_since
        ),

        "previous_until": (
            previous_until
        ),

        "period_display": (
            get_period_display_name(
                since,
                until
            )
        )
    }


# ============================================================
# RELATÓRIOS
# ============================================================

@app.route(
    "/relatorios",
    methods=["GET", "POST"]
)
@login_required
def relatorios():

    try:

        clients = list_clients()

    except Exception as exc:

        print(
            "ERRO AO LISTAR CLIENTES "
            f"PARA RELATÓRIO: {exc}"
        )

        clients = []

    quick_periods = get_quick_periods()

    default_since, default_until = (
        get_default_dates()
    )

    if request.method == "POST":

        client_id = (
            request.form
            .get("client_id", "")
            .strip()
        )

        since = (
            request.form
            .get("since", "")
            .strip()
        )

        until = (
            request.form
            .get("until", "")
            .strip()
        )

        if (
            client_id
            and since
            and until
        ):

            return redirect(
                url_for(
                    "gerar_relatorio",
                    client_id=client_id,
                    since=since,
                    until=until
                )
            )

    return render_template(

        "relatorios.html",

        active_page="relatorios",

        clients=clients,

        quick_periods=quick_periods,

        since=default_since,

        until=default_until,

        report=None,

        error=None
    )


@app.route("/relatorios/gerar", methods=["GET"])
@login_required
def gerar_relatorio():

    client_id_str = request.args.get(
        "client_id",
        ""
    ).strip()

    since = request.args.get(
        "since",
        ""
    ).strip()

    until = request.args.get(
        "until",
        ""
    ).strip()

    if (
        not client_id_str
        or not since
        or not until
    ):
        return redirect(
            url_for("relatorios")
        )

    if not validate_dates(
        since,
        until
    ):
        return redirect(
            url_for("relatorios")
        )

    try:

        from uuid import UUID

        client_id = UUID(
            client_id_str
        )

    except ValueError:

        return redirect(
            url_for("relatorios")
        )

    try:

        report = get_complete_report_data(
            client_id,
            since,
            until
        )

        return render_template(
            "relatorios.html",

            active_page="relatorios",

            clients=list_clients(),

            quick_periods=get_quick_periods(),

            since=since,

            until=until,

            report=report,

            error=None
        )

    except Exception as exc:

        print(
            "ERRO AO GERAR RELATÓRIO:"
        )

        import traceback

        traceback.print_exc()

        return render_template(
            "relatorios.html",

            active_page="relatorios",

            clients=list_clients(),

            quick_periods=get_quick_periods(),

            since=since,

            until=until,

            report=None,

            error=str(exc)
        )

@app.route("/relatorios/exportar-pdf", methods=["POST"])
@login_required
def exportar_relatorio_pdf():
    """
    Exporta o relatório em PDF.
    """
    
    from io import BytesIO
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
    
    client_id_str = request.form.get("client_id", "").strip()
    since = request.form.get("since", "").strip()
    until = request.form.get("until", "").strip()
    notes = request.form.get("notes", "").strip()
    
    # Validações
    try:
        from uuid import UUID
        client_id = UUID(client_id_str)
    except ValueError:
        return redirect(url_for("relatorios"))
    
    if not validate_dates(since, until):
        return redirect(url_for("relatorios"))
    
    try:
        # Buscar dados do relatório
        client = get_client(client_id)
        if not client:
            return redirect(url_for("relatorios"))
        
        connection = get_client_connection(client_id, include_token=True)
        if not connection:
            return redirect(url_for("relatorios"))
        
        access_token = connection.get("access_token")
        selected_account_ids = get_selected_ad_account_ids(client_id)
        
        meta_accounts = get_client_meta_ad_accounts(access_token)
        accounts_to_fetch = [
            acc for acc in meta_accounts
            if acc.get("id") in selected_account_ids
        ]
        
        # Buscar insights
        current_accounts = []
        previous_accounts = []
        
        previous_since, previous_until = get_previous_period(since, until)
        
        for account in accounts_to_fetch:
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
            
            current_accounts.append(current)
            previous_accounts.append(previous)
        
        # Agregar
        metrics = aggregate_accounts_metrics(current_accounts)
        previous_metrics = aggregate_accounts_metrics(previous_accounts)
        comparison = calculate_period_comparison(metrics, previous_metrics)
        
        # Criar PDF
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=A4,
            rightMargin=1.5*cm,
            leftMargin=1.5*cm,
            topMargin=1.5*cm,
            bottomMargin=1.5*cm,
        )
        
        # Estilos
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#061a45'),
            spaceAfter=12,
            alignment=TA_CENTER,
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#061a45'),
            spaceAfter=8,
            spaceBefore=12,
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['BodyText'],
            fontSize=10,
            textColor=colors.HexColor('#102044'),
            spaceAfter=6,
        )
        
        # Conteúdo
        elements = []
        
        # Capa
        elements.append(Spacer(1, 2*cm))
        
        # Logo/Avatar (se existir)
        if client.get("avatar_url"):
            try:
                img = Image(client.get("avatar_url"), width=3*cm, height=3*cm)
                elements.append(img)
                elements.append(Spacer(1, 0.5*cm))
            except:
                pass
        
        # Título
        elements.append(Paragraph("Relatório de Performance", title_style))
        elements.append(Paragraph(client.get("name", "Cliente"), title_style))
        elements.append(Spacer(1, 0.5*cm))
        
        # Período
        period_text = get_period_display_name(since, until)
        elements.append(Paragraph(f"<b>Período:</b> {period_text}", body_style))
        
        if client.get("responsible_name"):
            elements.append(Paragraph(f"<b>Gestor:</b> {client.get('responsible_name')}", body_style))
        
        elements.append(Paragraph(f"<b>Data da geração:</b> {datetime.now().strftime('%d/%m/%Y às %H:%M')}", body_style))
        
        elements.append(PageBreak())
        
        # Resumo de KPIs
        elements.append(Paragraph("Resumo do Período", heading_style))
        
        # Tabela de KPIs
        kpi_data = [
            ["Métrica", "Período Atual", "Período Anterior", "Variação"],
            [
                "Investimento",
                f"R$ {metrics.get('spend', 0):.2f}",
                f"R$ {previous_metrics.get('spend', 0):.2f}",
                f"{comparison['spend']['variation']:.1f}%" if comparison.get('spend', {}).get('variation') is not None else "N/A",
            ],
            [
                "Impressões",
                f"{metrics.get('impressions', 0):,.0f}",
                f"{previous_metrics.get('impressions', 0):,.0f}",
                f"{comparison['impressions']['variation']:.1f}%" if comparison.get('impressions', {}).get('variation') is not None else "N/A",
            ],
            [
                "Alcance",
                f"{metrics.get('reach', 0):,.0f}",
                f"{previous_metrics.get('reach', 0):,.0f}",
                f"{comparison['reach']['variation']:.1f}%" if comparison.get('reach', {}).get('variation') is not None else "N/A",
            ],
            [
                "Cliques",
                f"{metrics.get('link_clicks', 0):,.0f}",
                f"{previous_metrics.get('link_clicks', 0):,.0f}",
                f"{comparison['link_clicks']['variation']:.1f}%" if comparison.get('link_clicks', {}).get('variation') is not None else "N/A",
            ],
            [
                "Conversas",
                f"{metrics.get('conversations', 0):,.0f}",
                f"{previous_metrics.get('conversations', 0):,.0f}",
                f"{comparison['conversations']['variation']:.1f}%" if comparison.get('conversations', {}).get('variation') is not None else "N/A",
            ],
            [
                "CTR",
                f"{metrics.get('ctr', 0):.2f}%",
                f"{previous_metrics.get('ctr', 0):.2f}%",
                f"{comparison['ctr']['variation']:.1f}%" if comparison.get('ctr', {}).get('variation') is not None else "N/A",
            ],
            [
                "CPM",
                f"R$ {metrics.get('cpm', 0):.2f}",
                f"R$ {previous_metrics.get('cpm', 0):.2f}",
                f"{comparison['cpm']['variation']:.1f}%" if comparison.get('cpm', {}).get('variation') is not None else "N/A",
            ],
            [
                "Custo por Conversa",
                f"R$ {metrics.get('cost_per_conversation', 0):.2f}",
                f"R$ {previous_metrics.get('cost_per_conversation', 0):.2f}",
                f"{comparison['cost_per_conversation']['variation']:.1f}%" if comparison.get('cost_per_conversation', {}).get('variation') is not None else "N/A",
            ],
        ]
        
        kpi_table = Table(kpi_data)
        kpi_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#061a45')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))
        
        elements.append(kpi_table)
        
        # Observações
        if notes:
            elements.append(PageBreak())
            elements.append(Paragraph("Observações", heading_style))
            elements.append(Paragraph(notes, body_style))
        
        # Rodapé
        elements.append(Spacer(1, 1*cm))
        elements.append(Paragraph(
            f"Relatório gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} por Prospecte OS",
            ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.grey,
                alignment=TA_CENTER,
            )
        ))
        
        # Build PDF
        doc.build(elements)
        
        # Retornar arquivo
        pdf_buffer.seek(0)
        
        # Sanitizar nome do cliente
        client_name = client.get("name", "cliente").replace(" ", "-").lower()
        
        # Nome do arquivo
        filename = f"relatorio-{client_name}-{since}-ate-{until}.pdf"
        
        from flask import send_file
        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    
    except Exception as exc:
        print(f"ERRO AO EXPORTAR PDF: {exc}")
        import traceback
        traceback.print_exc()
        
        return redirect(url_for("relatorios"))


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


def _list_tasks(responsible_user_id=None):
    """
    Lista tarefas e permite filtrar pelo gestor responsável do cliente.

    O gestor do filtro é definido pelo campo clients.responsible_user_id.
    A tarefa continua tendo seu próprio assigned_to, que representa
    quem executa a tarefa.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT
                    t.id,
                    t.client_id,
                    c.name,
                    c.responsible_user_id,
                    responsible.name,
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
                LEFT JOIN users responsible
                    ON responsible.id = c.responsible_user_id
                JOIN users u ON u.id = t.assigned_to
            """

            params = []

            if responsible_user_id:
                query += """
                    WHERE c.responsible_user_id = %s
                """
                params.append(responsible_user_id)

            query += """
                ORDER BY
                    COALESCE(responsible.name, 'Sem gestor'),
                    c.name,
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
            """

            cur.execute(query, params)
            rows = cur.fetchall()

    current_user = _task_current_user_id()
    tasks = []

    for row in rows:
        task = {
            "id": str(row[0]),
            "client_id": str(row[1]),
            "client_name": row[2],
            "responsible_user_id": str(row[3]) if row[3] else None,
            "responsible_name": row[4],
            "created_by": str(row[5]),
            "assigned_to": str(row[6]),
            "assigned_to_name": row[7],
            "title": row[8],
            "description": row[9],
            "status": row[10],
            "priority": row[11],
            "visibility": row[12],
            "due_date": (
                row[13].strftime("%Y-%m-%dT%H:%M")
                if row[13]
                else ""
            ),
            "due_date_br": (
                row[13].strftime("%d/%m/%Y %H:%M")
                if row[13]
                else "Sem prazo"
            ),
            "completed_at": row[14],
            "created_at": row[15],
            "updated_at": row[16],
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


def _group_tasks_by_client(tasks):
    """
    Agrupa as tarefas por cliente, mantendo a ordem definida em _list_tasks().
    Cada grupo representa um projeto/cliente.
    """
    groups = {}

    for task in tasks:
        client_id = task["client_id"]

        if client_id not in groups:
            groups[client_id] = {
                "client_id": client_id,
                "client_name": task["client_name"],
                "responsible_user_id": task["responsible_user_id"],
                "responsible_name": task["responsible_name"],
                "tasks": [],
            }

        groups[client_id]["tasks"].append(task)

    return list(groups.values())


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
    """
    Tela principal de tarefas.

    Filtro:
      /tarefas?gestor=<UUID>

    Sem filtro, mostra todos os gestores/clientes.
    Com filtro, mostra apenas os clientes vinculados ao gestor.
    """
    selected_gestor = request.args.get("gestor", "").strip() or None

    try:
        tasks = _list_tasks(selected_gestor)
        clients = list_clients()
        users = _get_active_users()

        # Apenas usuários que podem ser gestores aparecem no filtro.
        gestores = users

        task_groups = _group_tasks_by_client(tasks)

        error = None
    except Exception as exc:
        print(f"ERRO AO LISTAR TAREFAS: {exc}")
        tasks = []
        task_groups = []
        clients = []
        users = []
        gestores = []
        error = "Não foi possível carregar as tarefas. Tente novamente."

    return render_template(
        "tasks.html",
        active_page="tarefas",
        tasks=tasks,
        task_groups=task_groups,
        clients=clients,
        users=users,
        gestores=gestores,
        selected_gestor=selected_gestor,
        error=error,
        message=request.args.get("message"),
    )


@app.route("/tarefas/criar", methods=["POST"])
@login_required
def criar_tarefa():
    data = _get_task_form_data()

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
