import os
import requests
import traceback
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)

WINDSOR_API_KEY = os.environ.get('WINDSOR_API_KEY', 'ab2a32d495a3d6c5f46565bd9ea6e0e3b6f9')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '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')
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://uhbmbmqoivoxgqnaighr.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'sb_publishable_EOI3VEJ7rgZOhNG7gU2zCA__hKX7Cqb')

WINDSOR_BASE = 'https://connectors.windsor.ai/facebook'
FIELDS = 'account_name,spend,actions_lead,actions_onsite_conversion_messaging_conversation_started_7d'
PRESETS = {'30': 'last_30dT', '15': 'last_15dT', '7': 'last_7dT'}

def supa_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_KEY,
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

def fetch_ads_data(preset):
    params = {'api_key': WINDSOR_API_KEY, 'date_preset': preset, 'fields': FIELDS}
    r = requests.get(WINDSOR_BASE, params=params, timeout=30)
    r.raise_for_status()
    raw = r.json().get('data', r.json())
    agg = {}
    for row in raw:
        name = (row.get('account_name') or '').strip()
        if not name: continue
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
        top5_lines = '\n'.join(['- ' + d['account_name'] + ': R$' + str(round(d['spend'])) + ' gasto, ' + str(d['total']) + ' resultados, CPL R$' + str(d['cpl'] or 0) for d in top5])
        alert_lines = '\n'.join(['- ' + d['account_name'] + ': CPL R$' + str(d['cpl']) + ', gasto R$' + str(round(d['spend'])) for d in alertas[:6]]) if alertas else 'Nenhuma conta com CPL alto.'
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
            'CLIENTES OURO: BAHAMONDES x2 R$2500, SHEIK R$2000\n'
            'CLIENTES PRATA: OTAVIO R$1500, GUTO R$1500, LUCCO R$1500, LBM R$1000, JIMY R$1000, ROJO R$1000, B&G ROCHA R$1000\n'
            'CLIENTES BRONZE: 19 clientes entre R$350-500'
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
            headers={'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 1024, 'system': system, 'messages': clean},
            timeout=30
        )
        resp.raise_for_status()
        return jsonify({'ok': True, 'reply': resp.json()['content'][0]['text']})
    except Exception as e:
        print('CHAT ERROR:', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Supabase: Clientes ──
@app.route('/api/clientes', methods=['GET'])
def get_clientes():
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true&order=nivel.asc,valor.desc', headers=supa_headers())
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes', methods=['POST'])
def add_cliente():
    try:
        body = request.json
        r = requests.post(SUPABASE_URL + '/rest/v1/clientes', headers=supa_headers(), json=body)
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>', methods=['DELETE'])
def delete_cliente(id):
    try:
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json={'ativo': False})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Supabase: Pagamentos ──
@app.route('/api/pagamentos/<mes>', methods=['GET'])
def get_pagamentos(mes):
    try:
        # Busca clientes ativos
        clientes_r = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true&order=nivel.asc,valor.desc', headers=supa_headers())
        clientes = clientes_r.json()

        # Pagamentos do mês atual
        pag_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes, headers=supa_headers())
        pagamentos = {p['cliente_id']: p for p in pag_r.json()}

        # Calcula mês anterior para buscar atrasados
        ano, m = int(mes[:4]), int(mes[5:])
        if m == 1:
            mes_ant = str(ano-1) + '-12'
        else:
            mes_ant = str(ano) + '-' + str(m-1).zfill(2)

        pag_ant_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes_ant + '&atrasado=eq.true&pago=eq.false', headers=supa_headers())
        atrasados_ant = {p['cliente_id']: p for p in pag_ant_r.json()}

        result = []
        for c in clientes:
            p = pagamentos.get(c['id'], {})
            # Se nao tem pagamento no mes atual mas estava atrasado no mes anterior
            is_atrasado = p.get('atrasado', False) or (c['id'] in atrasados_ant and not p)
            result.append({**c, 'pago': p.get('pago', False), 'atrasado': is_atrasado, 'pag_id': p.get('id')})
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/pagamentos/<mes>/<int:cliente_id>', methods=['POST'])
def set_pagamento(mes, cliente_id):
    try:
        body = request.json
        # Upsert
        r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes + '&cliente_id=eq.' + str(cliente_id), headers=supa_headers())
        existing = r.json()
        if existing:
            requests.patch(SUPABASE_URL + '/rest/v1/pagamentos?id=eq.' + str(existing[0]['id']), headers=supa_headers(), json={**body, 'updated_at': 'now()'})
        else:
            requests.post(SUPABASE_URL + '/rest/v1/pagamentos', headers=supa_headers(), json={'mes': mes, 'cliente_id': cliente_id, **body})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/historico', methods=['GET'])
def get_historico():
    try:
        # Busca todos os meses com pagamentos
        r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?select=mes&order=mes.desc', headers=supa_headers())
        meses = list(dict.fromkeys([p['mes'] for p in r.json()]))
        resultado = []
        for mes in meses:
            pag_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes, headers=supa_headers())
            pags = pag_r.json()
            cli_r = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true', headers=supa_headers())
            clientes = {c['id']: c for c in cli_r.json()}
            total = sum(clientes[p['cliente_id']]['valor'] for p in pags if p['cliente_id'] in clientes)
            recebido = sum(clientes[p['cliente_id']]['valor'] for p in pags if p.get('pago') and p['cliente_id'] in clientes)
            atrasado = sum(clientes[p['cliente_id']]['valor'] for p in pags if p.get('atrasado') and not p.get('pago') and p['cliente_id'] in clientes)
            resultado.append({'mes': mes, 'total': total, 'recebido': recebido, 'atrasado': atrasado})
        return jsonify({'ok': True, 'data': resultado})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Supabase: Tarefas ──
@app.route('/api/tarefas', methods=['GET'])
def get_tarefas():
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/tarefas?concluida=eq.false&order=created_at.asc', headers=supa_headers())
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/tarefas', methods=['POST'])
def add_tarefa():
    try:
        body = request.json
        r = requests.post(SUPABASE_URL + '/rest/v1/tarefas', headers=supa_headers(), json=body)
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/tarefas/<int:id>', methods=['DELETE'])
def delete_tarefa(id):
    try:
        requests.patch(SUPABASE_URL + '/rest/v1/tarefas?id=eq.' + str(id), headers=supa_headers(), json={'concluida': True})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/faturamento')
def faturamento():
    return send_from_directory('static', 'faturamento.html')

@app.route('/tarefas')
def tarefas():
    return send_from_directory('static', 'tarefas.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
