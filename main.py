import os
import requests
import traceback
import hashlib
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_from_directory, request, session, redirect
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)
app.secret_key = 'mobilli_secret_2026_xk9p'

WINDSOR_API_KEY = os.environ.get('WINDSOR_API_KEY', 'ab2a32d495a3d6c5f46565bd9ea6e0e3b6f9')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://uhbmbmqoivoxgqnaighr.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
PASSWORD_HASH = hashlib.sha256('Enricomota@2018'.encode()).hexdigest()

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

def check_auth():
    return session.get('autenticado') == True

@app.before_request
def require_login():
    public = ['/login', '/api/login', '/logout']
    if request.path in public or request.path.startswith('/static'):
        return None
    if not check_auth():
        if request.path.startswith('/api/'):
            return jsonify({'ok': False, 'error': 'Nao autorizado'}), 401
        return redirect('/login')

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
        result.append({'account_name': v['account_name'], 'spend': round(v['spend'], 2),
                       'leads': int(v['leads']), 'msg': int(v['msg']), 'total': int(total), 'cpl': cpl})
    result.sort(key=lambda x: x['spend'], reverse=True)
    return result

def get_fat_info():
    try:
        mes_atual = datetime.utcnow().strftime('%Y-%m')
        cli_r = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true', headers=supa_headers(), timeout=10)
        clientes_list = cli_r.json()
        pag_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes_atual, headers=supa_headers(), timeout=10)
        pagamentos = {p['cliente_id']: p for p in pag_r.json()}
        ano, m = int(mes_atual[:4]), int(mes_atual[5:])
        mes_ant = str(ano) + '-' + str(m-1).zfill(2) if m > 1 else str(ano-1) + '-12'
        pag_ant_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes_ant + '&atrasado=eq.true&pago=eq.false', headers=supa_headers(), timeout=10)
        atrasados_ant = {p['cliente_id'] for p in pag_ant_r.json()}
        pagos, pendentes, atrasados = [], [], []
        for c in clientes_list:
            p = pagamentos.get(c['id'], {})
            is_atrasado = p.get('atrasado', False) or (c['id'] in atrasados_ant and not p)
            if is_atrasado and not p.get('pago'):
                atrasados.append(c['nome'])
            elif p.get('pago'):
                pagos.append(c['nome'])
            else:
                pendentes.append(c['nome'])
        fat_recebido = sum(float(c['valor']) for c in clientes_list if pagamentos.get(c['id'], {}).get('pago'))
        fat_total = sum(float(c['valor']) for c in clientes_list if not (pagamentos.get(c['id'], {}).get('atrasado') or c['id'] in atrasados_ant))
        return len(clientes_list), (
            'FATURAMENTO ' + mes_atual + ':\n'
            'Total esperado: R$' + str(round(fat_total)) + '\n'
            'Recebido: R$' + str(round(fat_recebido)) + '\n'
            'Clientes pagos (' + str(len(pagos)) + '): ' + (', '.join(pagos) if pagos else 'nenhum') + '\n'
            'Clientes pendentes (' + str(len(pendentes)) + '): ' + (', '.join(pendentes) if pendentes else 'nenhum') + '\n'
            'Clientes ATRASADOS (' + str(len(atrasados)) + '): ' + (', '.join(atrasados) if atrasados else 'nenhum') + '\n'
        )
    except Exception as e:
        print('FAT ERROR:', traceback.format_exc())
        return 29, 'Dados de faturamento indisponiveis.\n'

# ── Auth ──
@app.route('/login')
def login_page():
    return send_from_directory('static', 'login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        body = request.json or {}
        senha = body.get('senha', '')
        hash_input = hashlib.sha256(senha.encode()).hexdigest()
        if hash_input == PASSWORD_HASH:
            session['autenticado'] = True
            session.permanent = True
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'Senha incorreta'}), 401
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ── Ads ──
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
        return jsonify({'ok': True, 'kpis': {'spend': round(total_spend, 2), 'results': total_results,
            'leads': total_leads, 'msg': total_msg, 'cpl': cpl_avg, 'active': active, 'total': len(data)}, 'accounts': data})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Chat ──
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
        alertas = sorted([d for d in ads_data if d['cpl'] and d['cpl'] > 15 and d['spend'] > 0], key=lambda x: x['cpl'], reverse=True)
        top5_lines = '\n'.join(['- ' + d['account_name'] + ': R$' + str(round(d['spend'])) + ', ' + str(d['total']) + ' resultados, CPL R$' + str(d['cpl'] or 0) for d in ads_data[:5]])
        alert_lines = '\n'.join(['- ' + d['account_name'] + ': CPL R$' + str(d['cpl']) for d in alertas[:6]]) if alertas else 'Nenhuma conta com CPL alto.'
        total_clientes, fat_info = get_fat_info()
        system = (
            'Voce e o assistente da agencia Mobilli Digital de Andre Mota. '
            'Responda sempre em portugues de forma direta e objetiva. '
            'Use emojis moderadamente. Nunca invente dados.\n\n'
            'DADOS DA AGENCIA:\n'
            'Clientes ativos: ' + str(total_clientes) + '\n'
            'Historico 2026: Jan R$16000, Fev R$10500, Mar R$19250, Abr R$16550, Mai R$31300, Jun R$20550\n\n'
            + fat_info + '\n'
            'META ADS ULTIMOS 30 DIAS:\n'
            'Investimento total: R$' + str(round(total_spend)) + '\n'
            'Resultados: ' + str(total_results) + ' (' + str(total_leads) + ' leads + ' + str(total_msg) + ' conversas)\n'
            'CPL medio: R$' + str(cpl_avg) + '\n\n'
            'TOP 5 CONTAS:\n' + top5_lines + '\n\n'
            'ALERTAS CPL ACIMA R$15:\n' + alert_lines
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

# ── Clientes ──
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
        now = datetime.utcnow().isoformat()
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json={'ativo': False, 'inativado_em': now})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>/dia', methods=['PATCH'])
def update_dia_pagamento(id):
    try:
        body = request.json
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json={'dia_pagamento': body.get('dia_pagamento')})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/movimento', methods=['GET'])
def get_movimento():
    try:
        mes = request.args.get('mes', datetime.utcnow().strftime('%Y-%m'))
        inicio = mes + '-01T00:00:00'
        ano, m = int(mes[:4]), int(mes[5:])
        fim = str(ano) + '-' + str(m+1).zfill(2) + '-01T00:00:00' if m < 12 else str(ano+1) + '-01-01T00:00:00'
        r_novos = requests.get(SUPABASE_URL + '/rest/v1/clientes?created_at=gte.' + inicio + '&created_at=lt.' + fim, headers=supa_headers())
        novos = r_novos.json()
        r_perdidos = requests.get(SUPABASE_URL + '/rest/v1/clientes?inativado_em=gte.' + inicio + '&inativado_em=lt.' + fim, headers=supa_headers())
        perdidos = r_perdidos.json()
        return jsonify({'ok': True, 'novos': novos, 'perdidos': perdidos,
            'total_novos': len(novos), 'total_perdidos': len(perdidos),
            'valor_novos': sum(float(c.get('valor', 0)) for c in novos),
            'valor_perdidos': sum(float(c.get('valor', 0)) for c in perdidos)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Pagamentos ──
@app.route('/api/config/<chave>', methods=['GET'])
def get_config(chave):
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/config?chave=eq.' + chave, headers=supa_headers())
        data = r.json()
        if data:
            return jsonify({'ok': True, 'valor': data[0]['valor']})
        return jsonify({'ok': False, 'error': 'Chave nao encontrada'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/config/<chave>', methods=['PATCH'])
def set_config(chave):
    try:
        body = request.json
        r = requests.get(SUPABASE_URL + '/rest/v1/config?chave=eq.' + chave, headers=supa_headers())
        existing = r.json()
        if existing:
            requests.patch(SUPABASE_URL + '/rest/v1/config?chave=eq.' + chave, headers=supa_headers(), json={'valor': body.get('valor')})
        else:
            requests.post(SUPABASE_URL + '/rest/v1/config', headers=supa_headers(), json={'chave': chave, 'valor': body.get('valor')})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/pagamentos/<mes>', methods=['GET'])
def get_pagamentos(mes):
    try:
        clientes_r = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true&order=nivel.asc,valor.desc', headers=supa_headers())
        clientes = clientes_r.json()
        pag_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes, headers=supa_headers())
        pagamentos = {p['cliente_id']: p for p in pag_r.json()}
        ano, m = int(mes[:4]), int(mes[5:])
        mes_ant = str(ano) + '-' + str(m-1).zfill(2) if m > 1 else str(ano-1) + '-12'
        pag_ant_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes_ant + '&atrasado=eq.true&pago=eq.false', headers=supa_headers())
        atrasados_ant = {p['cliente_id'] for p in pag_ant_r.json()}
        result = []
        for c in clientes:
            p = pagamentos.get(c['id'], {})
            is_atrasado = p.get('atrasado', False) or (c['id'] in atrasados_ant and not p)
            result.append({**c, 'pago': p.get('pago', False), 'atrasado': is_atrasado, 'pag_id': p.get('id')})
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/pagamentos/<mes>/<int:cliente_id>', methods=['POST'])
def set_pagamento(mes, cliente_id):
    try:
        body = request.json
        r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes + '&cliente_id=eq.' + str(cliente_id), headers=supa_headers())
        existing = r.json()
        if existing:
            requests.patch(SUPABASE_URL + '/rest/v1/pagamentos?id=eq.' + str(existing[0]['id']), headers=supa_headers(), json={**body, 'updated_at': datetime.utcnow().isoformat()})
        else:
            requests.post(SUPABASE_URL + '/rest/v1/pagamentos', headers=supa_headers(), json={'mes': mes, 'cliente_id': cliente_id, **body})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/historico', methods=['GET'])
def get_historico():
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?select=mes&order=mes.desc', headers=supa_headers())
        meses = list(dict.fromkeys([p['mes'] for p in r.json()]))
        resultado = []
        for mes in meses:
            pag_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes, headers=supa_headers())
            pags = pag_r.json()
            cli_r = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true', headers=supa_headers())
            clientes = {c['id']: c for c in cli_r.json()}
            total = sum(float(clientes[p['cliente_id']]['valor']) for p in pags if p['cliente_id'] in clientes)
            recebido = sum(float(clientes[p['cliente_id']]['valor']) for p in pags if p.get('pago') and p['cliente_id'] in clientes)
            atrasado = sum(float(clientes[p['cliente_id']]['valor']) for p in pags if p.get('atrasado') and not p.get('pago') and p['cliente_id'] in clientes)
            resultado.append({'mes': mes, 'total': total, 'recebido': recebido, 'atrasado': atrasado})
        return jsonify({'ok': True, 'data': resultado})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Tarefas ──
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
        now = datetime.utcnow().isoformat()
        requests.patch(SUPABASE_URL + '/rest/v1/tarefas?id=eq.' + str(id), headers=supa_headers(), json={'concluida': True, 'concluida_em': now})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/tarefas/historico', methods=['GET'])
def get_historico_tarefas():
    try:
        semana = request.args.get('semana', 'atual')
        hoje = datetime.utcnow()
        if semana == 'atual':
            inicio = hoje - timedelta(days=hoje.weekday())
            inicio = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
            fim = hoje
        else:
            inicio = hoje - timedelta(days=hoje.weekday() + 7)
            inicio = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
            fim = inicio + timedelta(days=7)
        r = requests.get(
            SUPABASE_URL + '/rest/v1/tarefas?concluida=eq.true&concluida_em=gte.' + inicio.isoformat() + '&concluida_em=lte.' + fim.isoformat() + '&order=concluida_em.desc',
            headers=supa_headers()
        )
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/tarefas/resetar', methods=['POST'])
def resetar_tarefas():
    try:
        now = datetime.utcnow().isoformat()
        requests.patch(SUPABASE_URL + '/rest/v1/tarefas?concluida=eq.false', headers=supa_headers(), json={'concluida': True, 'concluida_em': now})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Debug ──
@app.route('/api/debug/supabase')
def debug_supabase():
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/clientes?limit=3', headers=supa_headers())
        return jsonify({'ok': True, 'status': r.status_code, 'data': r.json(), 'key_prefix': SUPABASE_KEY[:20]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ── Pages ──
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
