"""
Serviço de Relatórios - Integrado com Meta Ads

Reutiliza as funções existentes de:
- Busca de clientes
- Conexões Meta Ads
- Métricas de contas
- Cálculos de variação
"""

from datetime import datetime, timedelta
from services.auth_service import get_db_connection
from services.client_service import get_client
from services.meta_oauth_service import (
    get_client_connection,
    get_selected_ad_account_ids,
)


def get_ad_account_details(account_id, access_token, since, until):
    """
    Busca detalhes de uma conta de anúncio específica.
    Reutiliza a função get_account_insights do app.py
    """
    # Esta função será chamada pelo app.py
    # pois get_account_insights está lá
    pass


def get_client_report_data(client_id, since, until):
    """
    Busca todos os dados necessários para montar um relatório completo de um cliente.
    
    Retorna:
    {
        'client': {...},
        'connection': {...},
        'accounts': [...],
        'metrics': {...},
    }
    """
    
    client = get_client(client_id)
    if not client:
        return None
    
    connection = get_client_connection(client_id, include_token=True)
    if not connection or not connection.get('access_token'):
        return {
            'client': client,
            'connection': None,
            'accounts': [],
            'metrics': None,
            'error': 'Cliente não possui conexão Meta Ads ativa.'
        }
    
    # Buscar IDs das contas selecionadas
    selected_account_ids = get_selected_ad_account_ids(client_id)
    
    return {
        'client': client,
        'connection': connection,
        'selected_account_ids': selected_account_ids,
        'since': since,
        'until': until,
    }


def calculate_period_comparison(current_metrics, previous_metrics):
    """
    Compara dois períodos e calcula variações percentuais.
    
    Retorna um dicionário com as métricas e suas variações.
    """
    if not current_metrics or not previous_metrics:
        return None
    
    comparison = {}
    
    # Métricas principais para comparação
    metric_keys = [
        'spend',
        'impressions',
        'reach',
        'link_clicks',
        'conversations',
        'ctr',
        'cpm',
        'cost_per_conversation',
    ]
    
    for key in metric_keys:
        current = current_metrics.get(key, 0)
        previous = previous_metrics.get(key, 0)
        
        # Calcular variação percentual
        if previous == 0:
            variation = None  # Não há base de comparação
        else:
            variation = ((current - previous) / previous) * 100
        
        comparison[key] = {
            'current': current,
            'previous': previous,
            'variation': variation,
        }
    
    return comparison


def format_currency(value):
    """Formata valor como moeda brasileira"""
    if isinstance(value, (int, float)):
        return f"R$ {value:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return value


def format_percentage(value):
    """Formata valor como percentual"""
    if isinstance(value, (int, float)):
        return f"{value:,.2f}%".replace(',', 'X').replace('.', ',').replace('X', '.')
    return value


def get_period_display_name(since, until):
    """
    Formata o período para exibição.
    Entrada: "2026-08-01"
    Saída: "01/08/2026 até 31/08/2026"
    """
    try:
        since_date = datetime.strptime(since, "%Y-%m-%d")
        until_date = datetime.strptime(until, "%Y-%m-%d")
        
        since_str = since_date.strftime("%d/%m/%Y")
        until_str = until_date.strftime("%d/%m/%Y")
        
        return f"{since_str} até {until_str}"
    except:
        return f"{since} até {until}"


def get_quick_periods():
    """
    Retorna períodos rápidos pré-definidos com datas calculadas.
    """
    today = datetime.now().date()
    
    return {
        '7d': {
            'label': 'Últimos 7 dias',
            'since': (today - timedelta(days=6)).strftime("%Y-%m-%d"),
            'until': today.strftime("%Y-%m-%d"),
        },
        '15d': {
            'label': 'Últimos 15 dias',
            'since': (today - timedelta(days=14)).strftime("%Y-%m-%d"),
            'until': today.strftime("%Y-%m-%d"),
        },
        '30d': {
            'label': 'Últimos 30 dias',
            'since': (today - timedelta(days=29)).strftime("%Y-%m-%d"),
            'until': today.strftime("%Y-%m-%d"),
        },
        'month': {
            'label': 'Este mês',
            'since': today.replace(day=1).strftime("%Y-%m-%d"),
            'until': today.strftime("%Y-%m-%d"),
        },
        'prev_month': {
            'label': 'Mês anterior',
            'since': (today.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d"),
            'until': (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d"),
        },
    }


def get_metric_interpretation(metric_name, current, previous, variation):
    """
    Retorna uma interpretação qualitativa da métrica.
    
    Exemplo:
    - 'spend' com aumento = negativo
    - 'reach' com aumento = positivo
    - 'cost_per_conversation' com redução = positivo
    """
    
    if variation is None:
        return None
    
    # Métricas onde aumento = bom
    positive_metrics = {
        'impressions', 'reach', 'link_clicks', 'conversations',
        'conversions', 'sales'
    }
    
    # Métricas onde redução = bom
    negative_metrics = {
        'spend', 'cpc', 'cpm', 'cost_per_conversation',
        'cost_per_lead', 'cost_per_purchase'
    }
    
    is_increase = variation > 0
    
    if metric_name in positive_metrics:
        return 'positive' if is_increase else 'negative'
    elif metric_name in negative_metrics:
        return 'negative' if is_increase else 'positive'
    
    return None


def aggregate_accounts_metrics(accounts_list):
    """
    Agrega métricas de múltiplas contas em um único objeto.
    
    Soma spend, impressions, etc.
    Calcula médias ponderadas para ctr, cpm, etc.
    """
    
    if not accounts_list:
        return None
    
    aggregated = {
        'spend': 0,
        'impressions': 0,
        'reach': 0,
        'link_clicks': 0,
        'conversations': 0,
        'ctr': 0,
        'cpm': 0,
        'cost_per_conversation': 0,
    }
    
    # Somar métricas diretas
    for account in accounts_list:
        if not account.get('error'):
            aggregated['spend'] += account.get('spend', 0)
            aggregated['impressions'] += account.get('impressions', 0)
            aggregated['reach'] += account.get('reach', 0)
            aggregated['link_clicks'] += account.get('link_clicks', 0)
            aggregated['conversations'] += account.get('conversations', 0)
    
    # Calcular médias para métricas de taxa
    if aggregated['impressions'] > 0:
        aggregated['ctr'] = (aggregated['link_clicks'] / aggregated['impressions']) * 100
        aggregated['cpm'] = (aggregated['spend'] / aggregated['impressions']) * 1000
    
    if aggregated['conversations'] > 0:
        aggregated['cost_per_conversation'] = aggregated['spend'] / aggregated['conversations']
    
    return aggregated
