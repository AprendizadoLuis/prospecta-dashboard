import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests
from flask import Flask, render_template, request
from dotenv import load_dotenv


# ============================================================
# CONFIGURAÇÃO
# ============================================================

load_dotenv()

app = Flask(__name__)

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")

META_API_VERSION = "v26.0"

MESSAGING_CONVERSATION_ACTION = (
    "onsite_conversion.messaging_conversation_started_7d"
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
    until
):

    account_id = account["id"]

    url = (
        f"https://graph.facebook.com/"
        f"{META_API_VERSION}/"
        f"{account_id}/insights"
    )

    params = {

        "access_token":
            META_ACCESS_TOKEN,

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
                    account.get(
                        "name",
                        "Sem nome"
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
                account.get(
                    "name",
                    "Sem nome"
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
                account.get(
                    "name",
                    "Sem nome"
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
# HOME
# ============================================================

@app.route("/")
def home():

    # ========================================================
    # DATAS
    # ========================================================

    default_since, default_until = (
        get_default_dates()
    )


    since = request.args.get(
        "since",
        default_since
    )


    until = request.args.get(
        "until",
        default_until
    )


    if not validate_dates(
        since,
        until
    ):

        since = default_since

        until = default_until


    # ========================================================
    # CONTAS
    # ========================================================

    accounts, error = get_ad_accounts()


    if error:

        return render_template(

            "index.html",

            accounts=[],

            error=error,

            since=since,

            until=until,

            period_label=(
                f"{format_date_br(since)} - "
                f"{format_date_br(until)}"
            ),

            total_spend=0,

            total_conversations=0,

            average_cost_per_conversation=0,

            average_ctr=0,

            average_cpm=0,

            critical_count=0,

            warning_count=0,

            healthy_count=0
        )


    # ========================================================
    # SOMENTE CONTAS ATIVAS
    # ========================================================

    active_accounts = [

        account

        for account in accounts

        if account.get(
            "account_status"
        ) == 1
    ]


    # ========================================================
    # BUSCAR INSIGHTS
    # ========================================================

    results = []


    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:


        futures = [

            executor.submit(

                get_account_insights,

                account,

                since,

                until

            )

            for account in active_accounts
        ]


        for future in as_completed(
            futures
        ):

            results.append(
                future.result()
            )


    # ========================================================
    # ORDENAR
    # ========================================================

    results.sort(

        key=lambda x:
            x["name"].lower()
    )


    # ========================================================
    # TOTAIS
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
    # CUSTO MÉDIO PONDERADO
    # ========================================================

    average_cost_per_conversation = (

        total_spend
        / total_conversations

        if total_conversations > 0

        else 0
    )


    # ========================================================
    # CTR MÉDIO
    # ========================================================

    average_ctr = (

        (
            total_link_clicks
            / total_impressions
        ) * 100

        if total_impressions > 0

        else 0
    )


    # ========================================================
    # CPM MÉDIO
    # ========================================================

    average_cpm = (

        (
            total_spend
            / total_impressions
        ) * 1000

        if total_impressions > 0

        else 0
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

        if account["status"]["class"]
        == "critical"
    )


    warning_count = sum(

        1

        for account in results

        if account["status"]["class"]
        == "warning"
    )


    healthy_count = sum(

        1

        for account in results

        if account["status"]["class"]
        == "healthy"
    )


    # ========================================================
    # RENDER
    # ========================================================

    return render_template(

        "index.html",

        accounts=results,

        error=None,

        since=since,

        until=until,

        period_label=(

            f"{format_date_br(since)} - "
            f"{format_date_br(until)}"

        ),

        total_spend=total_spend,

        total_conversations=total_conversations,

        average_cost_per_conversation=(
            average_cost_per_conversation
        ),

        average_ctr=average_ctr,

        average_cpm=average_cpm,

        critical_count=critical_count,

        warning_count=warning_count,

        healthy_count=healthy_count
    )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )