import os
import requests
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)

WINDSOR_API_KEY = os.environ.get('WINDSOR_API_KEY', 'ab2a32d495a3d6c5f46565bd9ea6e0e3b6f9')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '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')
WINDSOR_BASE = 'https://connectors.windsor.ai/facebook'
FIELDS = 'account_name,spend,actions_lead,actions_onsite_conversion_messaging_conversation_started_7d'
PRESETS = {'30': 'last_30dT', '15': 'last_15dT', '7': 'last_7dT'}

CLIENTES = [
    {"nome": "BAHAMONDES", "valor": 2500, "nivel": "ouro"},
    {"nome": "BAHAMONDES 2", "valor": 2500, "nivel": "ouro"},
    {"nome": "SHEIK", "valor": 2000, "nivel": "ouro"},
    {"nome": "OTAVIO APEPROPRIO", "valor": 1500, "nivel": "prata"},
    {"nome": "GUTO", "valor": 1500, "nivel": "prata"},
    {"nome": "LUCCO", "valor": 1500, "nivel": "prata"},
    {"nome": "LBM", "valor": 1000, "nivel": "prata"},
    {"nome": "JIMY", "valor": 1000, "nivel": "prata"},
    {"nome": "ROJO", "valor": 1000, "nivel": "prata"},
    {"nome": "B&G (ROCHA)", "valor": 1000, "nivel": "prata"},
    {"nome": "JOSIAS", "valor": 500, "nivel": "bronze"},
    {"nome": "JEGE", "valor": 500, "nivel": "bronze"},
    {"nome": "ALARICK", "valor": 500, "nivel": "bronze"},
    {"nome": "SARÇA", "valor": 500, "nivel": "bronze"},
    {"nome": "WENDY", "valor": 500, "nivel": "bronze"},
    {"nome": "DISLEIDE", "valor": 500, "nivel": "bronze"},
    {"nome": "CANUT", "valor": 500, "nivel": "bronze"},
    {"nome": "DICK LOURENÇO", "valor": 500, "nivel": "bronze"},
    {"nome": "CHAPOLIM", "valor": 500, "nivel": "bronze"},
    {"nome": "CLARICE", "valor": 500, "nivel": "bronze"},
    {"nome": "LUCAS PADRE", "valor": 500, "nivel": "bronze"},
    {"nome": "DISNEY", "valor": 500, "nivel": "bronze"},
    {"nome": "INFINITY", "valor": 500, "nivel": "bronze"},
    {"nome": "DOUGLAS", "valor": 500, "nivel": "bronze"},
    {"nome": "IMOB ADRIANO", "valor": 500, "nivel": "bronze"},
    {"nome": "OXFORD", "valor": 350, "nivel": "bronze"},
    {"nome": "EGITO", "valor": 350, "nivel": "bronze"},
    {"nome": "EDGARD", "valor": 350, "nivel": "bronze"},
    {"nome": "FUNARI", "valor": 350, "nivel": "bronze"},
]

FATURAMENTO = {
    "Janeiro": 16000, "Fevereiro": 10500, "Março": 19250,
    "Abril": 16550, "Maio": 31300, "Junho": "em andamento"
}

def fetch_ads_data(preset):
    params = {'api_key': WINDSOR_API_KEY, 'date_preset': preset, 'fields': FIELDS}
    r = requests.get(WINDSOR_BASE, params=params, timeout=30)
    r.raise_for_status()
    raw = r.json().get('data', r.json())
    aggregated = {}
    for row in raw:
        name = (row.get('account_name') or '').strip()
        if not name:
            continue
        spend = float(row.get('spend') or 0)
        leads = float(row.get('actions_lead') or 0)
        msg = float(row.get('actions_onsite_conversion_messaging_conversation_started_7d') or 0)
        if name in aggregated:
            aggregated[name]['spend'] += spend
            aggregated[name]['leads'] += leads
            aggregated[name]['msg'] += msg
        else:
            aggregated[name] = {'account_name': name, 'spend': spend, 'leads': leads, 'msg': msg}
    result = []
    for v in aggregated.values():
        total = v['leads'] + v['msg']
        cpl = round(v['spend'] / total, 2) if total else None
        result.append({
            'account_name': v['account_name'],
            'spend': round(v['spend'], 2),
            'leads': int(v['leads']),
            'msg': int(v['msg']),
            'total': int(total),
            'cpl': cpl,
        })
    result.sort(key=lambda x: x['spend'], reverse=True)
    return result

def build_context(ads_data):
    total_spend = sum(d['spend'] for d in ads_data)
    total_results = sum(d['total'] for d in ads_data)
    total_leads = sum(d['leads'] for d in ads_data)
    total_msg = sum(d['msg'] for d in ads_data)
    cpl_avg = round(total_spend / total_results, 2) if total_results else 0
    active = len([d for d in ads_data if d['spend'] > 0])
    alertas = [d for d in ads_data if d['cpl'] and d['cpl'] > 15 and d['spend'] > 0]
    alertas.sort(key=lambda x: x['cpl'], reverse=True)
    total_faturamento = sum(c['valor'] for c in CLIENTES)

    ctx = f"""Você é o assistente da agência Mobilli Digital, de André Mota.
André tem 29 clientes ativos divididos em: 3 Ouro (acima de R$1.500/mês), 7 Prata (R$700-R$1.500) e 19 Bronze (até R$700).
Faturamento mensal esperado: R${total_faturamento:,.0f}.

HISTÓRICO DE FATURAMENTO 2026:
Janeiro: R$16.000 | Fevereiro: R$10.500 | Março: R$19.250 | Abril: R$16.550 | Maio: R$31.300 | Junho: em andamento
Previsão Julho: R$22.367 (média dos últimos 3 meses)

META ADS — ÚLTIMOS 30 DIAS:
- Investimento total: R${total_spend:,.2f}
- Total de resultados: {total_results:,} ({total_leads:,} leads + {total_msg:,} conversas iniciadas)
- CPL médio: R${cpl_avg:.2f}
- Contas ativas: {active} de {len(ads_data)}

TOP 5 CONTAS POR INVESTIMENTO:
"""
    for d in ads_data[:5]:
        cpl_str = f"R${d['cpl']:.2f}" if d['cpl'] else "sem conversão"
        ctx += f"- {d['account_name']}: R${d['spend']:,.2f} gasto | {d['total']} resultados | CPL {cpl_str}\n"

    if alertas:
        ctx += f"\nCONTAS COM CPL ACIMA DE R$15 (REQUEREM ATENÇÃO):\n"
        for d in alertas[:6]:
            ctx += f"- {d['account_name']}: CPL R${d['cpl']:.2f} | Gasto R${d['spend']:,.2f} | {d['total']} resultados\n"
    else:
        ctx += "\nNENHUMA CONTA com CPL acima de R$15 hoje. ✅\n"

    ctx += "\nCLIENTES POR NÍVEL:\n"
    for nivel in ['ouro', 'prata', 'bronze']:
        clientes_nivel = [c for c in CLIENTES if c['nivel'] == nivel]
        nomes = ', '.join([c['nome'] for c in clientes_nivel])
        total_nivel = sum(c['valor'] for c in clientes_nivel)
        ctx += f"- {nivel.upper()}: {nomes} (total R${total_nivel:,}/mês)\n"

    return ctx

@app.route('/api/data')
def api_data():
    period = request.args.get('period', '30')
    preset = PRESETS.get(period, 'last_30dT')
    try:
        data = fetch_ads_data(preset)
        total_spend = sum(d['spend'] for d in data)
        total_results = sum(d['total'] for d in data)
        total_leads = sum(d['leads'] for d in data)
        total_msg = sum(d['msg'] for d in data)
        active = len([d for d in data if d['spend'] > 0])
        cpl_avg = round(total_spend / total_results, 2) if total_results else 0
        return jsonify({
            'ok': True,
            'kpis': {
                'spend': round(total_spend, 2),
                'results': total_results,
                'leads': total_leads,
                'msg': total_msg,
                'cpl': cpl_avg,
                'active': active,
                'total': len(data),
            },
            'accounts': data,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def api_chat():
    try:
        body = request.json
        messages = body.get('messages', [])

        # Busca dados do Meta Ads para contexto
        try:
            ads_data = fetch_ads_data('last_30dT')
        except:
            ads_data = []

        system_prompt = build_context(ads_data)
        system_prompt += """
Você é o assistente pessoal de André na Mobilli Digital. Responda sempre em português, de forma direta e objetiva.
Quando for o primeiro briefing do dia, faça um resumo executivo com: situação geral, alertas prioritários e 3 atividades recomendadas para o dia.
Para perguntas seguintes, responda de forma concisa com base nos dados acima.
Use emojis moderadamente para facilitar a leitura. Nunca invente dados — use apenas os fornecidos acima.
"""
        # Garante que messages tem alternância correta user/assistant
        clean_messages = []
        for m in messages:
            if m.get('role') in ('user', 'assistant') and m.get('content'):
                clean_messages.append({'role': m['role'], 'content': str(m['content'])})

        # Garante que começa com user
        if not clean_messages or clean_messages[0]['role'] != 'user':
            clean_messages = [{'role': 'user', 'content': 'Olá'}] + clean_messages

        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': 'claude-sonnet-4-6',
                'max_tokens': 1024,
                'system': system_prompt,
                'messages': clean_messages,
            },
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data['content'][0]['text']
        return jsonify({'ok': True, 'reply': reply})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/faturamento')
def faturamento():
    return send_from_directory('static', 'faturamento.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
