import os
import requests
import traceback
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)

WINDSOR_API_KEY = os.environ.get('WINDSOR_API_KEY', 'ab2a32d495a3d6c5f46565bd9ea6e0e3b6f9')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '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')
WINDSOR_BASE = 'https://connectors.windsor.ai/facebook'
FIELDS = 'account_name,spend,actions_lead,actions_onsite_conversion_messaging_conversation_started_7d'
PRESETS = {'30': 'last_30dT', '15': 'last_15dT', '7': 'last_7dT'}

def fetch_ads_data(preset):
    params = {'api_key': WINDSOR_API_KEY, 'date_preset': preset, 'fields': FIELDS}
    r = requests.get(WINDSOR_BASE, params=params, timeout=30)
    r.raise_for_status()
    raw = r.json().get('data', r.json())
    agg = {}
    for row in raw:
        name = (row.get('account_name') or '').strip()
        if not name:
            continue
        spend = float(row.get('spend') or 0)
        leads = float(row.get('actions_lead') or 0)
        msg = float(row.get('actions_onsite_conversion_messaging_conversation_started_7d') or 0)
        if name in agg:
            agg[name]['spend'] += spend
            agg[name]['leads'] += leads
            agg[name]['msg'] += msg
        else:
            agg[name] = {'account_name': name, 'spend': spend, 'leads': leads, 'msg': msg}
    result = []
    for v in agg.values():
        total = v['leads'] + v['msg']
        cpl = round(v['spend'] / total, 2) if total else None
        result.append({'account_name': v['account_name'], 'spend': round(v['spend'], 2), 'leads': int(v['leads']), 'msg': int(v['msg']), 'total': int(total), 'cpl': cpl})
    result.sort(key=lambda x: x['spend'], reverse=True)
    return result

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
        return jsonify({'ok': True, 'kpis': {'spend': round(total_spend, 2), 'results': total_results, 'leads': total_leads, 'msg': total_msg, 'cpl': cpl_avg, 'active': active, 'total': len(data)}, 'accounts': data})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def api_chat():
    try:
        body = request.json or {}
        messages = body.get('messages', [])

        try:
            ads_data = fetch_ads_data('last_30dT')
        except:
            ads_data = []

        total_spend = sum(d['spend'] for d in ads_data)
        total_results = sum(d['total'] for d in ads_data)
        total_leads = sum(d['leads'] for d in ads_data)
        total_msg = sum(d['msg'] for d in ads_data)
        cpl_avg = round(total_spend / total_results, 2) if total_results else 0
        alertas = [d for d in ads_data if d['cpl'] and d['cpl'] > 15 and d['spend'] > 0]
        alertas.sort(key=lambda x: x['cpl'], reverse=True)

        top5 = ads_data[:5]
        top5_lines = '\n'.join([
            '- ' + d['account_name'] + ': R$' + str(round(d['spend'])) + ' gasto, ' + str(d['total']) + ' resultados, CPL R$' + str(d['cpl'] or 0)
            for d in top5
        ])
        alert_lines = '\n'.join([
            '- ' + d['account_name'] + ': CPL R$' + str(d['cpl']) + ', gasto R$' + str(round(d['spend']))
            for d in alertas[:6]
        ]) if alertas else 'Nenhuma conta com CPL alto.'

        system = (
            'Voce e o assistente da agencia Mobilli Digital de Andre Mota. '
            'Responda sempre em portugues de forma direta e objetiva. '
            'Use emojis moderadamente. Nunca invente dados.\n\n'
            'DADOS DA AGENCIA:\n'
            'Clientes ativos: 29 (3 Ouro, 7 Prata, 19 Bronze)\n'
            'Faturamento mensal esperado: R$24400\n'
            'Historico 2026: Jan R$16000, Fev R$10500, Mar R$19250, Abr R$16550, Mai R$31300, Jun em andamento\n'
            'Previsao Julho: R$22367\n\n'
            'META ADS ULTIMOS 30 DIAS:\n'
            'Investimento total: R$' + str(round(total_spend)) + '\n'
            'Resultados: ' + str(total_results) + ' (' + str(total_leads) + ' leads + ' + str(total_msg) + ' conversas)\n'
            'CPL medio: R$' + str(cpl_avg) + '\n\n'
            'TOP 5 CONTAS:\n' + top5_lines + '\n\n'
            'ALERTAS CPL ACIMA R$15:\n' + alert_lines + '\n\n'
            'CLIENTES OURO (acima R$1500): BAHAMONDES x2 R$2500, SHEIK R$2000\n'
            'CLIENTES PRATA (R$700-1500): OTAVIO R$1500, GUTO R$1500, LUCCO R$1500, LBM R$1000, JIMY R$1000, ROJO R$1000, B&G ROCHA R$1000\n'
            'CLIENTES BRONZE (ate R$700): 19 clientes entre R$350-500'
        )

        clean = []
        for m in messages:
            role = m.get('role', '')
            content = m.get('content', '')
            if role in ('user', 'assistant') and content:
                clean.append({'role': role, 'content': str(content)})

        if not clean:
            clean = [{'role': 'user', 'content': 'Ola'}]
        elif clean[0]['role'] != 'user':
            clean = [{'role': 'user', 'content': 'Ola'}] + clean

        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': 'claude-haiku-4-5-20251001',
                'max_tokens': 1024,
                'system': system,
                'messages': clean,
            },
            timeout=30
        )
        print('Anthropic status:', resp.status_code)
        print('Anthropic body:', resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
        reply = data['content'][0]['text']
        return jsonify({'ok': True, 'reply': reply})

    except Exception as e:
        tb = traceback.format_exc()
        print('CHAT ERROR:', tb)
        return jsonify({'ok': False, 'error': str(e), 'trace': tb}), 500

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/faturamento')
def faturamento():
    return send_from_directory('static', 'faturamento.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
