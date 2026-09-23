import os
import re
import requests
import traceback
import hashlib
import secrets
import string
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlencode
from flask import Flask, jsonify, send_from_directory, request, session, redirect
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)
app.secret_key = 'mobilli_secret_2026_xk9p'

WINDSOR_API_KEY = os.environ.get('WINDSOR_API_KEY', 'ab2a32d495a3d6c5f46565bd9ea6e0e3b6f9')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://uhbmbmqoivoxgqnaighr.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', 'https://novoclaude2026-1.onrender.com/api/google/callback')

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

def current_user():
    if not check_auth():
        return None
    return {'id': session.get('usuario_id'), 'nome': session.get('nome'),
            'role': session.get('role'), 'username': session.get('username')}

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def gerar_senha_temp(n=8):
    alfabeto = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alfabeto) for _ in range(n))

ADMIN_ONLY_PAGES = {'/', '/faturamento', '/financeiro', '/agenda', '/clientes', '/gestores'}
ADMIN_ONLY_API_PREFIXES = (
    '/api/despesas', '/api/financeiro', '/api/agenda', '/api/google',
    '/api/clientes', '/api/contas-anuncio', '/api/config', '/api/pagamentos',
    '/api/historico', '/api/debug', '/api/briefing', '/api/chat',
    '/api/usuarios', '/api/gestores'
)
ADMIN_ONLY_EXACT_API = {'/api/tarefas/resetar', '/api/data'}

@app.before_request
def require_login():
    public = ['/login', '/api/login', '/logout']
    if request.path in public or request.path.startswith('/static'):
        return None
    if check_auth() and not session.get('usuario_id'):
        # sessao antiga (do login por senha unica, antes dos usuarios por login) - forca novo login
        session.clear()
    if not check_auth():
        if request.path.startswith('/api/'):
            return jsonify({'ok': False, 'error': 'Nao autorizado'}), 401
        return redirect('/login')
    if session.get('role') != 'admin':
        if request.path in ADMIN_ONLY_PAGES or request.path.startswith('/cliente/'):
            return redirect('/painel')
        if request.path.startswith(ADMIN_ONLY_API_PREFIXES) or request.path in ADMIN_ONLY_EXACT_API:
            return jsonify({'ok': False, 'error': 'Acesso restrito'}), 403

def fetch_ads_data(date_preset=None, date_from=None, date_to=None):
    params = {'api_key': WINDSOR_API_KEY, 'fields': FIELDS}
    if date_from and date_to:
        params['date_from'] = date_from
        params['date_to'] = date_to
    else:
        params['date_preset'] = date_preset or 'last_30dT'
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

def get_ads_resumo():
    try:
        ads_data = fetch_ads_data(date_preset='last_30dT')
    except Exception:
        ads_data = []
    total_spend = sum(d['spend'] for d in ads_data)
    total_results = sum(d['total'] for d in ads_data)
    total_leads = sum(d['leads'] for d in ads_data)
    total_msg = sum(d['msg'] for d in ads_data)
    cpl_avg = round(total_spend / total_results, 2) if total_results else 0
    alertas = sorted([d for d in ads_data if d['cpl'] and d['cpl'] > 15 and d['spend'] > 0], key=lambda x: x['cpl'], reverse=True)
    top5_lines = '\n'.join(['- ' + d['account_name'] + ': R$' + str(round(d['spend'])) + ', ' + str(d['total']) + ' resultados, CPL R$' + str(d['cpl'] or 0) for d in ads_data[:5]]) or 'Sem dados.'
    alert_lines = '\n'.join(['- ' + d['account_name'] + ': CPL R$' + str(d['cpl']) for d in alertas[:6]]) if alertas else 'Nenhuma conta com CPL alto.'
    return (
        'META ADS ULTIMOS 30 DIAS (area do Bryan):\n'
        'Investimento total: R$' + str(round(total_spend)) + '\n'
        'Resultados: ' + str(total_results) + ' (' + str(total_leads) + ' leads + ' + str(total_msg) + ' conversas)\n'
        'CPL medio: R$' + str(cpl_avg) + '\n\n'
        'TOP 5 CONTAS:\n' + top5_lines + '\n\n'
        'ALERTAS CPL ACIMA R$15:\n' + alert_lines + '\n'
    )

def get_movimento_resumo():
    try:
        mes = datetime.utcnow().strftime('%Y-%m')
        ano, m = int(mes[:4]), int(mes[5:])
        inicio = mes + '-01T00:00:00'
        fim = str(ano) + '-' + str(m + 1).zfill(2) + '-01T00:00:00' if m < 12 else str(ano + 1) + '-01-01T00:00:00'
        r_novos = requests.get(SUPABASE_URL + '/rest/v1/clientes?created_at=gte.' + inicio + '&created_at=lt.' + fim, headers=supa_headers(), timeout=10)
        novos = [c['nome'] for c in r_novos.json()]
        r_perdidos = requests.get(SUPABASE_URL + '/rest/v1/clientes?inativado_em=gte.' + inicio + '&inativado_em=lt.' + fim, headers=supa_headers(), timeout=10)
        perdidos = [c['nome'] for c in r_perdidos.json()]
        return (
            'MOVIMENTO DE CLIENTES neste mes (area do Emerson):\n'
            'Novos (' + str(len(novos)) + '): ' + (', '.join(novos) if novos else 'nenhum') + '\n'
            'Perdidos/cancelados (' + str(len(perdidos)) + '): ' + (', '.join(perdidos) if perdidos else 'nenhum') + '\n'
        )
    except Exception:
        return 'Movimento de clientes indisponivel.\n'

def get_tarefas_resumo():
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/tarefas?concluida=eq.false&order=created_at.asc', headers=supa_headers(), timeout=10)
        tarefas = r.json()
        hoje = [t['titulo'] for t in tarefas if t.get('prazo') == 'hoje']
        amanha = [t['titulo'] for t in tarefas if t.get('prazo') == 'amanha']
        semana = [t['titulo'] for t in tarefas if t.get('prazo') == 'semana']
        return (
            'TAREFAS PENDENTES (area da Amy):\n'
            'Hoje (' + str(len(hoje)) + '): ' + (', '.join(hoje) if hoje else 'nenhuma') + '\n'
            'Amanha (' + str(len(amanha)) + '): ' + (', '.join(amanha) if amanha else 'nenhuma') + '\n'
            'Semana (' + str(len(semana)) + '): ' + (', '.join(semana) if semana else 'nenhuma') + '\n'
        )
    except Exception:
        return 'Tarefas indisponiveis.\n'

def build_dados_equipe():
    total_clientes, fat_info = get_fat_info()
    return (
        'Clientes ativos: ' + str(total_clientes) + '\n'
        'Historico faturamento 2026: Jan R$16000, Fev R$10500, Mar R$19250, Abr R$16550, Mai R$31300, Jun R$20550\n\n'
        + fat_info + '\n'
        + get_ads_resumo() + '\n'
        + get_movimento_resumo() + '\n'
        + get_tarefas_resumo() + '\n'
        + 'MARKETING INTERNO (area da Anna):\n'
          'Nenhuma metrica conectada ainda (sem dados de conteudo, social media ou crescimento visual).\n'
    )

TEAM_INTRO = (
    'Voce representa a equipe da agencia Mobilli Digital, de Andre Mota (agencia de trafego pago imobiliario MCMV). '
    'A equipe tem 5 especialistas, cada um dono de uma area. Ao responder, identifique de qual area e a pergunta '
    'e responda NA VOZ da pessoa responsavel, comecando o bloco com "**[Nome] (Area):**" antes do texto. '
    'Se a pergunta envolver mais de uma area, responda com um bloco por pessoa relevante, cada bloco comecando '
    'com o proprio "**[Nome] (Area):**". Nunca invente dados ou numeros fora do que estiver em DADOS DISPONIVEIS. '
    'Responda sempre em portugues, de forma direta e objetiva. Use emojis com moderacao.\n\n'
    'A EQUIPE:\n'
    '- Bryan (Trafego): Meta Ads, CPL, otimizacao de campanhas e investimento em midia paga.\n'
    '- Claudio (Financeiro): faturamento, cobranca, pagamentos, inadimplencia.\n'
    '- Emerson (Vendas e Expansao): novos clientes, churn, retencao, upsell.\n'
    '- Amy (Secretaria): tarefas, agenda e prioridades do dia a dia.\n'
    '- Anna (Marketing Interno): conteudo, social media e crescimento visual da propria Mobilli Digital. '
    'Ainda sem metricas conectadas -- atua como consultora estrategica quando perguntada, sem inventar numeros, '
    'e pode sugerir conectar Instagram/TikTok/YouTube organico via Windsor.ai no futuro.\n\n'
)

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
        username = (body.get('usuario') or '').strip().lower()
        senha = body.get('senha', '')
        if not username or not senha:
            return jsonify({'ok': False, 'error': 'Informe usuario e senha'}), 400
        r = requests.get(SUPABASE_URL + '/rest/v1/usuarios?username=eq.' + username + '&ativo=eq.true', headers=supa_headers(), timeout=10)
        rows = r.json()
        if not rows or rows[0]['senha_hash'] != hash_senha(senha):
            return jsonify({'ok': False, 'error': 'Usuario ou senha incorretos'}), 401
        u = rows[0]
        session['autenticado'] = True
        session['usuario_id'] = u['id']
        session['nome'] = u['nome']
        session['role'] = u['role']
        session['username'] = u['username']
        session.permanent = True
        return jsonify({'ok': True, 'role': u['role']})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/me')
def api_me():
    u = current_user()
    if not u:
        return jsonify({'ok': False}), 401
    return jsonify({'ok': True, 'usuario': u})

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ── Ads ──
@app.route('/api/data')
def api_data():
    period = request.args.get('period', '30')
    try:
        if period == 'hoje':
            hoje = datetime.utcnow().strftime('%Y-%m-%d')
            data = fetch_ads_data(date_from=hoje, date_to=hoje)
        elif period == 'ontem':
            ontem = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
            data = fetch_ads_data(date_from=ontem, date_to=ontem)
        else:
            preset = PRESETS.get(period, 'last_30dT')
            data = fetch_ads_data(date_preset=preset)
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
        system = TEAM_INTRO + 'DADOS DISPONIVEIS:\n\n' + build_dados_equipe()
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
        if resp.status_code >= 400:
            try:
                detalhe = resp.json()
            except Exception:
                detalhe = resp.text
            print('CHAT ERROR DETALHE:', resp.status_code, detalhe)
            return jsonify({'ok': False, 'error': str(resp.status_code) + ': ' + str(detalhe)}), 500
        return jsonify({'ok': True, 'reply': resp.json()['content'][0]['text']})
    except Exception as e:
        print('CHAT ERROR:', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Briefing da manha ──
@app.route('/api/briefing', methods=['GET'])
def api_briefing():
    try:
        dados = build_dados_equipe()
        system = (
            'Voce vai montar o briefing matinal da equipe da Mobilli Digital para o Andre Mota. '
            'Cada um dos 5 especialistas da um relato curto (2 a 4 linhas) da propria area, em primeira pessoa, '
            'cada bloco comecando com "**[Nome] (Area):**". Ordem fixa: Amy (Secretaria), Claudio (Financeiro), '
            'Bryan (Trafego), Emerson (Vendas e Expansao), Anna (Marketing Interno). '
            'Va direto ao ponto, cite numeros reais dos DADOS abaixo, e termine cada bloco apontando o que '
            'precisa de acao hoje (ou "nada urgente" se nao houver). Anna ainda nao tem dados conectados -- ela '
            'deve dizer isso em uma linha e sugerir uma ideia de conteudo do dia. Nunca invente dados. '
            'IMPORTANTE: nao inclua titulo, cabecalho, saudacao inicial nem linhas separadoras como "---" ou "===". '
            'Comece a resposta direto no primeiro bloco "**[Nome] (Area):**" e va direto para o proximo bloco '
            'em seguida, sem nenhum texto entre eles alem dos proprios blocos. '
            'Responda em portugues.\n\n'
            'DADOS:\n' + dados
        )
        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 1200, 'system': system,
                  'messages': [{'role': 'user', 'content': 'Monte o briefing de hoje.'}]},
            timeout=30
        )
        if resp.status_code >= 400:
            try:
                detalhe = resp.json()
            except Exception:
                detalhe = resp.text
            print('BRIEFING ERROR DETALHE:', resp.status_code, detalhe)
            return jsonify({'ok': False, 'error': str(resp.status_code) + ': ' + str(detalhe)}), 500
        return jsonify({'ok': True, 'briefing': resp.json()['content'][0]['text'], 'data': datetime.utcnow().strftime('%d/%m/%Y')})
    except Exception as e:
        print('BRIEFING ERROR:', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Financeiro ──
@app.route('/api/despesas', methods=['GET'])
def get_despesas():
    try:
        mes = request.args.get('mes', datetime.utcnow().strftime('%Y-%m'))
        r = requests.get(SUPABASE_URL + '/rest/v1/despesas?mes=eq.' + mes + '&order=categoria.asc,valor.desc', headers=supa_headers())
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/despesas', methods=['POST'])
def add_despesa():
    try:
        body = request.json
        r = requests.post(SUPABASE_URL + '/rest/v1/despesas', headers=supa_headers(), json=body)
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/despesas/<int:id>', methods=['PATCH'])
def update_despesa(id):
    try:
        body = request.json
        requests.patch(SUPABASE_URL + '/rest/v1/despesas?id=eq.' + str(id), headers=supa_headers(), json=body)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/despesas/<int:id>', methods=['DELETE'])
def delete_despesa(id):
    try:
        requests.delete(SUPABASE_URL + '/rest/v1/despesas?id=eq.' + str(id), headers=supa_headers())
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/financeiro/resumo', methods=['GET'])
def financeiro_resumo():
    try:
        mes = request.args.get('mes', datetime.utcnow().strftime('%Y-%m'))
        cli_r = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true', headers=supa_headers())
        clientes = {c['id']: c for c in cli_r.json()}
        pag_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes, headers=supa_headers())
        pagamentos = pag_r.json()
        entrada = sum(float(clientes[p['cliente_id']]['valor']) for p in pagamentos if p.get('pago') and p['cliente_id'] in clientes)
        esperado = sum(float(c['valor']) for c in clientes.values())

        desp_r = requests.get(SUPABASE_URL + '/rest/v1/despesas?mes=eq.' + mes, headers=supa_headers())
        despesas = desp_r.json()
        saida_total = sum(float(d['valor']) for d in despesas)
        por_categoria = {'fixo': 0.0, 'variavel': 0.0, 'salario': 0.0}
        for d in despesas:
            cat = d.get('categoria')
            if cat in por_categoria:
                por_categoria[cat] += float(d['valor'])
        saldo = entrada - saida_total
        return jsonify({
            'ok': True, 'mes': mes,
            'entrada': round(entrada, 2), 'esperado': round(esperado, 2),
            'saida': round(saida_total, 2), 'saldo': round(saldo, 2),
            'por_categoria': {k: round(v, 2) for k, v in por_categoria.items()},
            'despesas': despesas
        })
    except Exception as e:
        print('FINANCEIRO ERROR:', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Agenda / Google Calendar ──
def get_config_valor(chave):
    r = requests.get(SUPABASE_URL + '/rest/v1/config?chave=eq.' + chave, headers=supa_headers())
    data = r.json()
    return data[0]['valor'] if data else None

def set_config_valor(chave, valor):
    existing = get_config_valor(chave)
    if existing is not None:
        requests.patch(SUPABASE_URL + '/rest/v1/config?chave=eq.' + chave, headers=supa_headers(), json={'valor': valor})
    else:
        requests.post(SUPABASE_URL + '/rest/v1/config', headers=supa_headers(), json={'chave': chave, 'valor': valor})

@app.route('/api/google/login')
def google_login():
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'https://www.googleapis.com/auth/calendar',
        'access_type': 'offline',
        'prompt': 'consent'
    }
    return redirect('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params))

@app.route('/api/google/callback')
def google_callback():
    try:
        code = request.args.get('code')
        if not code:
            return redirect('/agenda?erro=1')
        resp = requests.post('https://oauth2.googleapis.com/token', data={
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code'
        }, timeout=15)
        tokens = resp.json()
        refresh_token = tokens.get('refresh_token')
        if refresh_token:
            set_config_valor('google_refresh_token', refresh_token)
        else:
            print('GOOGLE CALLBACK SEM REFRESH TOKEN:', tokens)
        return redirect('/agenda')
    except Exception as e:
        print('GOOGLE CALLBACK ERROR:', traceback.format_exc())
        return redirect('/agenda?erro=1')

def get_google_access_token():
    refresh_token = get_config_valor('google_refresh_token')
    if not refresh_token:
        return None
    resp = requests.post('https://oauth2.googleapis.com/token', data={
        'refresh_token': refresh_token,
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'grant_type': 'refresh_token'
    }, timeout=15)
    if resp.status_code >= 400:
        print('GOOGLE REFRESH ERROR:', resp.status_code, resp.text)
        return None
    return resp.json().get('access_token')

@app.route('/api/agenda/status')
def agenda_status():
    return jsonify({'ok': True, 'conectado': bool(get_config_valor('google_refresh_token'))})

@app.route('/api/agenda/desconectar', methods=['POST'])
def agenda_desconectar():
    try:
        requests.delete(SUPABASE_URL + '/rest/v1/config?chave=eq.google_refresh_token', headers=supa_headers())
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

def get_calendarios(token):
    try:
        resp = requests.get(
            'https://www.googleapis.com/calendar/v3/users/me/calendarList',
            headers={'Authorization': 'Bearer ' + token},
            timeout=15
        )
        if resp.status_code >= 400:
            print('CALENDARIOS ERROR:', resp.status_code, resp.text)
            return []
        return resp.json().get('items', [])
    except Exception:
        print('CALENDARIOS ERROR:', traceback.format_exc())
        return []

@app.route('/api/debug/calendarios')
def debug_calendarios():
    try:
        token = get_google_access_token()
        if not token:
            return jsonify({'ok': False, 'error': 'nao conectado'})
        cals = get_calendarios(token)
        return jsonify({'ok': True, 'calendarios': [
            {'id': c.get('id'), 'summary': c.get('summary'), 'primary': c.get('primary'),
             'selected': c.get('selected'), 'accessRole': c.get('accessRole')} for c in cals
        ]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/agenda/eventos', methods=['GET'])
def agenda_eventos():
    try:
        token = get_google_access_token()
        if not token:
            return jsonify({'ok': True, 'conectado': False, 'eventos': []})
        mes = request.args.get('mes')
        if mes:
            ano, m = int(mes[:4]), int(mes[5:])
            time_min = datetime(ano, m, 1).isoformat() + 'Z'
            time_max = datetime(ano + 1, 1, 1).isoformat() + 'Z' if m == 12 else datetime(ano, m + 1, 1).isoformat() + 'Z'
            params_base = {'timeMin': time_min, 'timeMax': time_max, 'maxResults': 250, 'singleEvents': 'true', 'orderBy': 'startTime'}
        else:
            agora = datetime.utcnow().isoformat() + 'Z'
            params_base = {'timeMin': agora, 'maxResults': 20, 'singleEvents': 'true', 'orderBy': 'startTime'}

        calendarios = get_calendarios(token)
        calendarios_usar = [c for c in calendarios if c.get('accessRole') in ('owner', 'writer', 'reader')] or calendarios
        if not calendarios_usar:
            calendarios_usar = [{'id': 'primary', 'summary': 'Principal'}]

        eventos = []
        for cal in calendarios_usar:
            cal_id = cal.get('id', 'primary')
            resp = requests.get(
                'https://www.googleapis.com/calendar/v3/calendars/' + requests.utils.quote(cal_id, safe='') + '/events',
                headers={'Authorization': 'Bearer ' + token},
                params=params_base,
                timeout=15
            )
            if resp.status_code >= 400:
                print('AGENDA EVENTOS ERROR (' + cal_id + '):', resp.status_code, resp.text)
                continue
            items = resp.json().get('items', [])
            for ev in items:
                eventos.append({
                    'id': ev.get('id'),
                    'titulo': ev.get('summary', '(sem titulo)'),
                    'inicio': (ev.get('start') or {}).get('dateTime') or (ev.get('start') or {}).get('date'),
                    'fim': (ev.get('end') or {}).get('dateTime') or (ev.get('end') or {}).get('date'),
                    'link': ev.get('htmlLink'),
                    'calendario': cal.get('summary', '')
                })
        eventos.sort(key=lambda e: e['inicio'] or '')
        return jsonify({'ok': True, 'conectado': True, 'eventos': eventos})
    except Exception as e:
        print('AGENDA ERROR:', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/agenda/eventos', methods=['POST'])
def agenda_criar_evento():
    try:
        token = get_google_access_token()
        if not token:
            return jsonify({'ok': False, 'error': 'Google Calendar nao conectado'}), 400
        body = request.json or {}
        data_inicio = body.get('inicio')
        data_fim = body.get('fim', data_inicio)
        payload = {
            'summary': body.get('titulo', '(sem titulo)'),
            'description': body.get('descricao', ''),
            'start': {'dateTime': data_inicio, 'timeZone': 'America/Sao_Paulo'},
            'end': {'dateTime': data_fim, 'timeZone': 'America/Sao_Paulo'}
        }
        resp = requests.post(
            'https://www.googleapis.com/calendar/v3/calendars/primary/events',
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
            json=payload, timeout=15
        )
        if resp.status_code >= 400:
            print('AGENDA CRIAR ERROR:', resp.status_code, resp.text)
            return jsonify({'ok': False, 'error': str(resp.status_code) + ': ' + resp.text}), 500
        return jsonify({'ok': True, 'data': resp.json()})
    except Exception as e:
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

@app.route('/api/clientes/<int:id>/valor', methods=['PATCH'])
def update_valor_cliente(id):
    try:
        body = request.json
        valor = float(body.get('valor'))
        if valor <= 0:
            return jsonify({'ok': False, 'error': 'Valor invalido'}), 400
        nivel = 'ouro' if valor >= 1500 else 'prata' if valor >= 1000 else 'bronze'
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json={'valor': valor, 'nivel': nivel})
        return jsonify({'ok': True, 'nivel': nivel})
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

# ── Ficha do cliente ──
OCUPACOES_VALIDAS = ['corretor', 'gerente', 'imobiliaria', 'superintendente', 'diretor', 'outro']

def calcular_risco_churn(ads_info, atrasado_atual, meses_atraso_recente):
    score = 0
    motivos = []
    if ads_info:
        cpl = ads_info.get('cpl')
        spend = ads_info.get('spend', 0)
        total = ads_info.get('total', 0)
        if spend == 0:
            score += 2
            motivos.append('Conta de anuncios sem investimento nos ultimos 30 dias')
        else:
            if cpl and cpl > 12:
                score += 1
                motivos.append('CPL acima de R$12 (R$' + str(cpl) + ')')
            if total < 5:
                score += 1
                motivos.append('Poucos resultados nos ultimos 30 dias (' + str(total) + ')')
    if atrasado_atual:
        score += 1
        motivos.append('Pagamento do mes atual em atraso')
    if meses_atraso_recente >= 2:
        score += 1
        motivos.append('Atrasou pagamento em pelo menos 2 dos ultimos 6 meses')
    nivel = 'alto' if score >= 3 else 'medio' if score >= 1 else 'baixo'
    return {'nivel': nivel, 'score': score, 'motivos': motivos}

@app.route('/api/clientes/<int:id>', methods=['GET'])
def get_cliente_detalhe(id):
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers())
        rows = r.json()
        if not rows:
            return jsonify({'ok': False, 'error': 'Cliente nao encontrado'}), 404
        cliente = rows[0]

        pag_r = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?cliente_id=eq.' + str(id) + '&order=mes.desc', headers=supa_headers())
        pagamentos = pag_r.json()
        meses_pagos = [p for p in pagamentos if p.get('pago')]
        valor_atual = float(cliente.get('valor') or 0)
        receita_total = round(valor_atual * len(meses_pagos), 2)

        mes_atual = datetime.utcnow().strftime('%Y-%m')
        pag_mes_atual = next((p for p in pagamentos if p.get('mes') == mes_atual), None)
        atrasado_atual = bool(pag_mes_atual and pag_mes_atual.get('atrasado') and not pag_mes_atual.get('pago'))
        meses_atraso_recente = len([p for p in pagamentos[:6] if p.get('atrasado') and not p.get('pago')])

        tempo_casa_dias = None
        if cliente.get('data_inicio'):
            try:
                d0 = datetime.strptime(cliente['data_inicio'][:10], '%Y-%m-%d')
                tempo_casa_dias = (datetime.utcnow() - d0).days
            except Exception:
                pass

        ads_info = None
        if cliente.get('conta_anuncio'):
            try:
                ads_data = fetch_ads_data(date_preset='last_30dT')
                ads_info = next((a for a in ads_data if a['account_name'] == cliente['conta_anuncio']), None)
            except Exception:
                ads_info = None

        risco = calcular_risco_churn(ads_info, atrasado_atual, meses_atraso_recente)

        return jsonify({'ok': True, 'data': {
            **cliente,
            'tempo_casa_dias': tempo_casa_dias,
            'receita_total': receita_total,
            'meses_pagos': len(meses_pagos),
            'atrasado_atual': atrasado_atual,
            'ads_info': ads_info,
            'risco_churn': risco
        }})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>/perfil', methods=['PATCH'])
def update_perfil_cliente(id):
    try:
        body = request.json or {}
        campos = {}
        for campo in ['nome', 'telefone', 'ocupacao', 'empresa', 'data_inicio', 'conta_anuncio']:
            if campo in body:
                campos[campo] = body[campo]
        if campos.get('ocupacao') and campos['ocupacao'] not in OCUPACOES_VALIDAS:
            return jsonify({'ok': False, 'error': 'Ocupacao invalida'}), 400
        if not campos:
            return jsonify({'ok': False, 'error': 'Nada para atualizar'}), 400
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json=campos)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>/indicacoes', methods=['PATCH'])
def update_indicacoes(id):
    try:
        body = request.json or {}
        delta = int(body.get('delta', 0))
        r = requests.get(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id) + '&select=indicacoes', headers=supa_headers())
        rows = r.json()
        if not rows:
            return jsonify({'ok': False, 'error': 'Cliente nao encontrado'}), 404
        atual = rows[0].get('indicacoes') or 0
        novo = max(0, atual + delta)
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json={'indicacoes': novo})
        return jsonify({'ok': True, 'indicacoes': novo})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/contas-anuncio', methods=['GET'])
def get_contas_anuncio():
    try:
        ads_data = fetch_ads_data(date_preset='last_30dT')
        return jsonify({'ok': True, 'data': [{'account_name': a['account_name']} for a in ads_data]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Usuarios / Gestores ──
@app.route('/api/usuarios', methods=['GET'])
def get_usuarios():
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/usuarios?ativo=eq.true&select=id,nome,username,role&order=id.asc', headers=supa_headers())
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/usuarios', methods=['POST'])
def add_usuario():
    try:
        body = request.json or {}
        nome = (body.get('nome') or '').strip()
        if not nome:
            return jsonify({'ok': False, 'error': 'Nome obrigatorio'}), 400
        base = re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', nome.lower()).encode('ascii', 'ignore').decode()) or 'gestor'
        username = base
        i = 1
        while True:
            check = requests.get(SUPABASE_URL + '/rest/v1/usuarios?username=eq.' + username, headers=supa_headers())
            if not check.json():
                break
            i += 1
            username = base + str(i)
        senha_temp = gerar_senha_temp()
        payload = {'nome': nome, 'username': username, 'senha_hash': hash_senha(senha_temp), 'role': 'gestor'}
        r = requests.post(SUPABASE_URL + '/rest/v1/usuarios', headers=supa_headers(), json=payload)
        novo = r.json()[0]
        return jsonify({'ok': True, 'data': {'id': novo['id'], 'nome': novo['nome'], 'username': novo['username'], 'senha_temp': senha_temp}})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/gestores/board', methods=['GET'])
def gestores_board():
    try:
        ur = requests.get(SUPABASE_URL + '/rest/v1/usuarios?ativo=eq.true&select=id,nome,username,role&order=id.asc', headers=supa_headers())
        usuarios = ur.json()
        cr = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true&select=id,nome,empresa,valor,nivel,gestor_id&order=nome.asc', headers=supa_headers())
        clientes = cr.json()
        return jsonify({'ok': True, 'usuarios': usuarios, 'clientes': clientes})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>/gestor', methods=['PATCH'])
def update_gestor_cliente(id):
    try:
        body = request.json or {}
        gestor_id = body.get('gestor_id')
        if not gestor_id:
            return jsonify({'ok': False, 'error': 'gestor_id obrigatorio'}), 400
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json={'gestor_id': gestor_id})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Meta Ads (visao limitada do gestor) ──
@app.route('/api/meta-ads/minhas', methods=['GET'])
def meta_ads_minhas():
    try:
        u = current_user()
        if not u:
            return jsonify({'ok': False, 'error': 'Nao autorizado'}), 401
        period = request.args.get('period', '30')
        cr = requests.get(SUPABASE_URL + '/rest/v1/clientes?gestor_id=eq.' + str(u['id']) + '&ativo=eq.true&select=conta_anuncio', headers=supa_headers())
        contas = {c['conta_anuncio'] for c in cr.json() if c.get('conta_anuncio')}
        if period == 'hoje':
            hoje = datetime.utcnow().strftime('%Y-%m-%d')
            data_all = fetch_ads_data(date_from=hoje, date_to=hoje)
        elif period == 'ontem':
            ontem = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
            data_all = fetch_ads_data(date_from=ontem, date_to=ontem)
        else:
            preset = PRESETS.get(period, 'last_30dT')
            data_all = fetch_ads_data(date_preset=preset)
        data = [d for d in data_all if d['account_name'] in contas]
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
        u = current_user()
        responsavel_id = u['id'] if u['role'] == 'gestor' else request.args.get('responsavel', 'todos')
        url = SUPABASE_URL + '/rest/v1/tarefas?concluida=eq.false&order=created_at.asc'
        if str(responsavel_id) != 'todos':
            url += '&responsavel_id=eq.' + str(responsavel_id)
        r = requests.get(url, headers=supa_headers())
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/tarefas', methods=['POST'])
def add_tarefa():
    try:
        u = current_user()
        body = request.json or {}
        responsavel_id = u['id'] if u['role'] == 'gestor' else (body.get('responsavel_id') or u['id'])
        payload = {'titulo': body.get('titulo'), 'prazo': body.get('prazo'), 'responsavel_id': responsavel_id}
        r = requests.post(SUPABASE_URL + '/rest/v1/tarefas', headers=supa_headers(), json=payload)
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/tarefas/<int:id>', methods=['DELETE'])
def delete_tarefa(id):
    try:
        u = current_user()
        if u['role'] == 'gestor':
            check = requests.get(SUPABASE_URL + '/rest/v1/tarefas?id=eq.' + str(id) + '&select=responsavel_id', headers=supa_headers())
            rows = check.json()
            if not rows or rows[0].get('responsavel_id') != u['id']:
                return jsonify({'ok': False, 'error': 'Nao autorizado'}), 403
        now = datetime.utcnow().isoformat()
        requests.patch(SUPABASE_URL + '/rest/v1/tarefas?id=eq.' + str(id), headers=supa_headers(), json={'concluida': True, 'concluida_em': now})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/tarefas/historico', methods=['GET'])
def get_historico_tarefas():
    try:
        u = current_user()
        responsavel_id = u['id'] if u['role'] == 'gestor' else request.args.get('responsavel', 'todos')
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
        url = (SUPABASE_URL + '/rest/v1/tarefas?concluida=eq.true&concluida_em=gte.' + inicio.isoformat() +
               '&concluida_em=lte.' + fim.isoformat() + '&order=concluida_em.desc')
        if str(responsavel_id) != 'todos':
            url += '&responsavel_id=eq.' + str(responsavel_id)
        r = requests.get(url, headers=supa_headers())
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

@app.route('/financeiro')
def financeiro_page():
    return send_from_directory('static', 'financeiro.html')

@app.route('/agenda')
def agenda_page():
    return send_from_directory('static', 'agenda.html')

@app.route('/clientes')
def clientes_page():
    return send_from_directory('static', 'clientes.html')

@app.route('/cliente/<int:id>')
def cliente_detalhe_page(id):
    return send_from_directory('static', 'cliente.html')

@app.route('/gestores')
def gestores_page():
    return send_from_directory('static', 'gestores.html')

@app.route('/painel')
def painel_gestor_page():
    if session.get('role') == 'admin':
        return redirect('/')
    return send_from_directory('static', 'painel_gestor.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
