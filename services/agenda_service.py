from datetime import datetime
import re


# ============================================================
# PROJETOS
# Futuramente virão do PostgreSQL
# ============================================================

PROJECTS = [
    {
        "id": 1,
        "name": "Apolo",
        "trigger": "apolo",
        "active": True,
    },
    {
        "id": 2,
        "name": "Clínica Teste",
        "trigger": "clinica teste",
        "active": True,
    },
]


# ============================================================
# CATEGORIAS
# Futuramente virão do PostgreSQL
# ============================================================

CATEGORIES = [
    {
        "id": 1,
        "name": "Reunião com cliente",
        "code": "REC",
        "active": True,
    },
    {
        "id": 2,
        "name": "Otimização",
        "code": "OTM",
        "active": True,
    },
    {
        "id": 3,
        "name": "Demanda interna",
        "code": "INT",
        "active": True,
    },
]


# ============================================================
# EVENTOS FICTÍCIOS
#
# Futuramente estes eventos serão substituídos
# pelos eventos vindos da API do Google Calendar.
# ============================================================

MOCK_EVENTS = [
    {
        "id": "event-001",
        "title": "[REC] Apolo - Reunião com cliente",
        "start": "2026-08-24 09:00",
        "end": "2026-08-24 10:00",
        "user": "William",
    },
    {
        "id": "event-002",
        "title": "[OTM] Apolo - Otimização Meta",
        "start": "2026-08-24 14:00",
        "end": "2026-08-24 15:30",
        "user": "William",
    },
    {
        "id": "event-003",
        "title": "[INT] Reunião interna Prospecte",
        "start": "2026-08-24 16:00",
        "end": "2026-08-24 16:45",
        "user": "William",
    },
    {
        "id": "event-004",
        "title": "[REC] Clínica Teste - Reunião",
        "start": "2026-08-24 11:00",
        "end": "2026-08-24 13:00",
        "user": "William",
    },
    {
        "id": "event-005",
        "title": "[OTM] Apolo - Ajuste de campanha",
        "start": "2026-08-23 15:00",
        "end": "2026-08-23 16:00",
        "user": "William",
    },
    {
        "id": "event-006",
        "title": "[REC] Apolo - Reunião de acompanhamento",
        "start": "2026-08-22 10:00",
        "end": "2026-08-22 11:30",
        "user": "William",
    },
    {
        "id": "event-007",
        "title": "[INT] Planejamento interno",
        "start": "2026-08-21 09:00",
        "end": "2026-08-21 10:00",
        "user": "William",
    },
]


# ============================================================
# PARSE DE DATAS
# ============================================================

def parse_datetime(value):
    return datetime.strptime(
        value,
        "%Y-%m-%d %H:%M"
    )


# ============================================================
# DURAÇÃO
# ============================================================

def calculate_duration_hours(start, end):
    duration = end - start

    return duration.total_seconds() / 3600


# ============================================================
# IDENTIFICAR PROJETO
# ============================================================

def identify_project(title):
    title_lower = title.lower()

    for project in PROJECTS:

        if not project["active"]:
            continue

        trigger = project["trigger"].lower()

        if trigger in title_lower:

            return project

    return None


# ============================================================
# IDENTIFICAR CATEGORIA
# ============================================================

def identify_category(title):
    title_upper = title.upper()

    for category in CATEGORIES:

        if not category["active"]:
            continue

        code = category["code"].upper()

        # Procura o código entre colchetes.
        # Exemplo:
        # [OTM] Apolo - Otimização
        pattern = rf"\[{re.escape(code)}\]"

        if re.search(pattern, title_upper):

            return category

    return None


# ============================================================
# CLASSIFICAR EVENTO
# ============================================================

def classify_event(event):

    start = parse_datetime(event["start"])
    end = parse_datetime(event["end"])

    project = identify_project(
        event["title"]
    )

    category = identify_category(
        event["title"]
    )

    duration = calculate_duration_hours(
        start,
        end
    )

    return {
        **event,

        "start_datetime": start,
        "end_datetime": end,

        "project": project,

        "category": category,

        "duration_hours": duration,
    }


# ============================================================
# BUSCAR EVENTOS
#
# Por enquanto usa dados fictícios.
#
# Futuramente:
#
# Google Calendar API
#         ↓
# lista de eventos
#         ↓
# esta mesma função de classificação
# ============================================================

def get_events(
    start_date=None,
    end_date=None
):

    classified_events = []

    for event in MOCK_EVENTS:

        classified = classify_event(
            event
        )

        event_date = classified[
            "start_datetime"
        ].date()

        if start_date:

            if event_date < start_date:
                continue

        if end_date:

            if event_date > end_date:
                continue

        classified_events.append(
            classified
        )

    classified_events.sort(
        key=lambda event:
            event["start_datetime"]
    )

    return classified_events


# ============================================================
# DASHBOARD
# ============================================================

def get_dashboard_data(
    start_date=None,
    end_date=None
):

    events = get_events(
        start_date=start_date,
        end_date=end_date
    )

    total_hours = sum(
        event["duration_hours"]
        for event in events
    )

    total_events = len(events)

    # --------------------------------------------------------
    # CLIENTES / PROJETOS
    # --------------------------------------------------------

    project_data = {}

    for event in events:

        project = event["project"]

        if not project:
            continue

        project_name = project["name"]

        if project_name not in project_data:

            project_data[project_name] = {
                "name": project_name,
                "events": 0,
                "hours": 0,
            }

        project_data[
            project_name
        ]["events"] += 1

        project_data[
            project_name
        ]["hours"] += event[
            "duration_hours"
        ]

    # --------------------------------------------------------
    # CATEGORIAS
    # --------------------------------------------------------

    category_data = {}

    for event in events:

        category = event["category"]

        if not category:
            continue

        category_name = category["name"]

        if category_name not in category_data:

            category_data[category_name] = {
                "name": category_name,
                "code": category["code"],
                "events": 0,
                "hours": 0,
            }

        category_data[
            category_name
        ]["events"] += 1

        category_data[
            category_name
        ]["hours"] += event[
            "duration_hours"
        ]

    # --------------------------------------------------------
    # TRANSFORMAR EM LISTAS
    # --------------------------------------------------------

    projects = list(
        project_data.values()
    )

    categories = list(
        category_data.values()
    )

    # --------------------------------------------------------
    # ORDENAR POR HORAS
    # --------------------------------------------------------

    projects.sort(
        key=lambda item:
            item["hours"],
        reverse=True
    )

    categories.sort(
        key=lambda item:
            item["hours"],
        reverse=True
    )

    # --------------------------------------------------------
    # PERCENTUAL DA OPERAÇÃO
    # --------------------------------------------------------

    for project in projects:

        project["percentage"] = (

            (
                project["hours"]
                / total_hours
            ) * 100

            if total_hours > 0

            else 0
        )

        project["average"] = (

            project["hours"]
            / project["events"]

            if project["events"] > 0

            else 0
        )

    for category in categories:

        category["percentage"] = (

            (
                category["hours"]
                / total_hours
            ) * 100

            if total_hours > 0

            else 0
        )

    # --------------------------------------------------------
    # MÉDIA POR EVENTO
    # --------------------------------------------------------

    average_per_event = (

        total_hours
        / total_events

        if total_events > 0

        else 0
    )

    # --------------------------------------------------------
    # CLIENTES ATENDIDOS
    # --------------------------------------------------------

    clients_count = len(
        projects
    )

    # --------------------------------------------------------
    # RETORNO
    # --------------------------------------------------------

    return {
        "events": events,

        "total_hours": total_hours,

        "total_events": total_events,

        "clients_count": clients_count,

        "average_per_event": average_per_event,

        "projects": projects,

        "categories": categories,
    }