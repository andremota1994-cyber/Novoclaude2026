import os
import json
import re
import requests
import traceback
import hashlib
import base64
import secrets
import string
import unicodedata
import threading
from datetime import datetime, timedelta
from urllib.parse import urlencode
from flask import Flask, jsonify, send_from_directory, request, session, redirect, g
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
FIELDS = 'account_name,account_id,spend,actions_lead,actions_onsite_conversion_messaging_conversation_started_7d'
PRESETS = {'30': 'last_30dT', '15': 'last_15dT', '7': 'last_7dT'}

def supa_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_KEY,
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

# ── Notificacoes no celular (Web Push) ──
# Chaves VAPID e segredo do agendamento ficam em push_chaves (RLS ligado). Na primeira vez
# o proprio servidor gera e grava, para a chave privada nunca sair do banco.
_push = {'chaves': None}

def chaves_push():
    if _push['chaves']:
        return _push['chaves']
    url = SUPABASE_URL + '/rest/v1/push_chaves?id=eq.1'
    linhas = requests.get(url, headers=supa_headers(), timeout=10).json()
    if isinstance(linhas, list) and not linhas:
        from py_vapid import Vapid01
        from cryptography.hazmat.primitives import serialization
        v = Vapid01()
        v.generate_keys()
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
        nova = {'id': 1, 'segredo_cron': secrets.token_urlsafe(32),
                'vapid_privada': b64(v.private_key.private_numbers().private_value.to_bytes(32, 'big')),
                'vapid_publica': b64(v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))}
        requests.post(SUPABASE_URL + '/rest/v1/push_chaves', json=nova, timeout=10,
                      headers={**supa_headers(), 'Prefer': 'resolution=ignore-duplicates,return=minimal'})
        linhas = requests.get(url, headers=supa_headers(), timeout=10).json()
    if isinstance(linhas, list) and linhas:
        _push['chaves'] = linhas[0]
    return _push['chaves']

def _enviar_push(usuario_ids, titulo, corpo, link):
    try:
        from pywebpush import webpush, WebPushException
        chaves = chaves_push()
        ids = ','.join(str(int(i)) for i in set(usuario_ids) if i)
        if not chaves or not ids:
            return
        inscricoes = requests.get(SUPABASE_URL + '/rest/v1/push_inscricoes?usuario_id=in.(' + ids + ')', headers=supa_headers(), timeout=10).json()
        dados = json.dumps({'titulo': titulo, 'corpo': corpo, 'url': link or '/'})
        for s in inscricoes if isinstance(inscricoes, list) else []:
            try:
                webpush(subscription_info={'endpoint': s['endpoint'], 'keys': {'p256dh': s['p256dh'], 'auth': s['auth']}},
                        data=dados, vapid_private_key=chaves['vapid_privada'], ttl=86400,
                        vapid_claims={'sub': 'https://novoclaude2026-1.onrender.com'})
            except WebPushException as e:
                # Aparelho desinscrito ou trocado: remove para nao tentar de novo
                if e.response is not None and e.response.status_code in (404, 410):
                    requests.delete(SUPABASE_URL + '/rest/v1/push_inscricoes', params={'endpoint': 'eq.' + s['endpoint']}, headers=supa_headers(), timeout=10)
                else:
                    print('PUSH falhou:', repr(e)[:300])
    except Exception:
        print('PUSH ERROR:', traceback.format_exc())

def notificar(usuario_ids, titulo, corpo, link='/'):
    # Envia em segundo plano para nao atrasar a resposta da tela
    threading.Thread(target=_enviar_push, args=(list(usuario_ids), titulo, corpo, link), daemon=True).start()

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

ADMIN_ONLY_PAGES = {'/', '/faturamento', '/financeiro', '/agenda', '/clientes', '/gestores', '/negociacao', '/dashboards'}
ADMIN_ONLY_API_PREFIXES = (
    '/api/despesas', '/api/financeiro', '/api/agenda', '/api/google',
    '/api/clientes', '/api/contas-anuncio', '/api/config', '/api/pagamentos',
    '/api/historico', '/api/debug', '/api/briefing', '/api/chat',
    '/api/usuarios', '/api/gestores', '/api/faturamento', '/api/vendas', '/api/repasses', '/api/negociacoes', '/api/dashboards'
)
ADMIN_ONLY_EXACT_API = {'/api/tarefas/resetar', '/api/data'}

@app.before_request
def require_login():
    public = ['/login', '/api/login', '/logout', '/sw.js', '/manifest.webmanifest', '/api/cron/alertas']
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

# ── Historico de movimentacoes ──
# Toda acao que altera dados no painel vira uma linha legivel em movimentacoes
# (quem fez, quando, o que mudou de -> para). A IA consulta esse historico.
SEM_HISTORICO = {'api_login', 'api_chat', 'push_inscrever', 'push_cancelar', 'push_teste', 'cron_alertas'}
STATUS_TXT = {'ativo': 'ativo', 'pausado': 'pausado', 'inativo': 'inativo'}
PRAZO_TXT = {'hoje': 'hoje', 'amanha': 'amanhã', 'semana': 'essa semana'}
NEG_STATUS_TXT = {'especulacao': 'Especulação', 'em_contato': 'Em contato', 'reuniao_marcada': 'Reunião marcada',
                  'avaliando_proposta': 'Avaliando proposta', 'quente': 'Quente', 'frio': 'Frio', 'fechado': 'Fechado'}

def _brl(v):
    try:
        return 'R$ ' + '{:,.2f}'.format(float(v)).replace(',', 'X').replace('.', ',').replace('X', '.')
    except (TypeError, ValueError):
        return '—'

def _mes_txt(mes):
    try:
        return ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'][int(mes[5:]) - 1] + '/' + mes[:4]
    except (TypeError, ValueError, IndexError):
        return str(mes)

def _linha(tabela, id, campos='*'):
    r = requests.get(SUPABASE_URL + '/rest/v1/' + tabela + '?id=eq.' + str(id) + '&select=' + campos, headers=supa_headers(), timeout=10).json()
    return r[0] if isinstance(r, list) and r else None

def _nome_usuario(uid):
    if not uid:
        return ''
    if not hasattr(g, '_nomes'):
        try:
            g._nomes = {u['id']: u['nome'] for u in requests.get(SUPABASE_URL + '/rest/v1/usuarios?select=id,nome', headers=supa_headers(), timeout=10).json()}
        except Exception:
            g._nomes = {}
    return g._nomes.get(int(uid), 'usuário ' + str(uid))

def registrar(acao, descricao, cliente_id=None, cliente_nome=None, detalhes=None, usuario=None):
    # Grava uma movimentacao em segundo plano (nao atrasa a resposta da tela)
    u = usuario if usuario is not None else (current_user() or {})
    linha = {'acao': acao, 'descricao': descricao[:1000], 'cliente_id': cliente_id, 'cliente_nome': cliente_nome,
             'usuario_id': u.get('id'), 'usuario_nome': u.get('nome') or ('Sistema' if not u.get('id') else None),
             'detalhes': detalhes}
    def gravar():
        try:
            requests.post(SUPABASE_URL + '/rest/v1/movimentacoes', headers=supa_headers(), json=linha, timeout=10).raise_for_status()
        except Exception:
            print('HISTORICO ERROR:', traceback.format_exc())
    threading.Thread(target=gravar, daemon=True).start()

CAMPOS_CLIENTE = 'id,nome,valor,dia_pagamento,gestor_id,status,ativo,contas_anuncio,conta_anuncio,telefone,ocupacao,empresa,data_inicio,indicacoes'

@app.before_request
def capturar_antes():
    # Guarda como o dado estava antes da acao, para o historico registrar "de -> para"
    if request.method not in ('POST', 'PATCH', 'DELETE') or not request.path.startswith('/api/'):
        return
    ep, va = request.endpoint, request.view_args or {}
    if ep in SEM_HISTORICO or not check_auth():
        return
    try:
        if ep in ('update_status_cliente', 'delete_cliente', 'update_dia_pagamento', 'update_valor_cliente', 'update_contas_cliente',
                  'update_perfil_cliente', 'update_indicacoes', 'update_gestor_cliente'):
            g.antes = _linha('clientes', va['id'], CAMPOS_CLIENTE)
        elif ep == 'update_dashboard_cliente':
            g.antes = _linha('clientes', va['id'], 'id,nome,dashboard_url,dashboard_senha')
        elif ep == 'set_pagamento':
            g.antes = _linha('clientes', va['cliente_id'], 'id,nome,valor')
        elif ep == 'update_checklist_cliente':
            g.antes = _linha('clientes', va['id'], 'id,nome,checklist')
        elif ep == 'delete_tarefa':
            g.antes = _linha('tarefas', va['id'], 'id,titulo,responsavel_id,cliente_id,clientes(nome)')
        elif ep in ('update_venda', 'delete_venda'):
            g.antes = _linha('vendas', va['id'], 'id,produto,valor,pago,cliente_id,cliente_nome,clientes(nome)')
        elif ep in ('update_negociacao', 'delete_negociacao', 'fechar_negociacao'):
            g.antes = _linha('negociacoes', va['id'])
        elif ep in ('update_despesa', 'delete_despesa'):
            g.antes = _linha('despesas', va['id'])
        elif ep == 'nova_senha_usuario':
            g.antes = _linha('usuarios', va['id'], 'id,nome')
    except Exception:
        g.antes = None

def descrever_movimentacao(ep, body, va, antes, res):
    # (acao, descricao, cliente_id, cliente_nome) de cada tipo de acao do painel
    a = antes or {}
    cid, cnome = a.get('id'), a.get('nome')
    if ep == 'update_gestor_cliente':
        return 'cliente_transferido', 'Cliente %s transferido de %s para %s' % (cnome, _nome_usuario(a.get('gestor_id')) or 'ninguém', _nome_usuario(body.get('gestor_id'))), cid, cnome
    if ep == 'update_status_cliente':
        return 'cliente_situacao', 'Cliente %s: situação %s → %s' % (cnome, STATUS_TXT.get(a.get('status'), a.get('status')), STATUS_TXT.get(body.get('status'), body.get('status'))), cid, cnome
    if ep == 'delete_cliente':
        return 'cliente_situacao', 'Cliente %s inativado (removido)' % cnome, cid, cnome
    if ep == 'update_valor_cliente':
        return 'cliente_mensalidade', 'Cliente %s: mensalidade %s → %s' % (cnome, _brl(a.get('valor')), _brl(body.get('valor'))), cid, cnome
    if ep == 'update_dia_pagamento':
        return 'cliente_vencimento', 'Cliente %s: vencimento dia %s → dia %s' % (cnome, a.get('dia_pagamento') or '—', body.get('dia_pagamento') or '—'), cid, cnome
    if ep == 'update_indicacoes':
        return 'cliente_indicacoes', 'Cliente %s: indicações %s → %s' % (cnome, a.get('indicacoes') or 0, (res or {}).get('indicacoes')), cid, cnome
    if ep == 'update_checklist_cliente':
        return 'checklist', 'Cliente %s: "%s" %s' % (cnome, CHECKLIST_ITENS.get(body.get('item'), body.get('item')),
                                                      'marcado como feito' if body.get('feito') else 'desmarcado'), cid, cnome
    if ep == 'update_contas_cliente':
        antes_l, depois_l = contas_de(a), (res or {}).get('contas') or []
        partes = ['vinculou ' + c for c in depois_l if c not in antes_l] + ['desvinculou ' + c for c in antes_l if c not in depois_l]
        return 'cliente_contas', 'Cliente %s: %s' % (cnome, '; '.join(partes) or 'contas reordenadas'), cid, cnome
    if ep == 'update_perfil_cliente':
        mud = ['%s: %s → %s' % (k, a.get(k) or '—', v or '—') for k, v in body.items() if str(a.get(k) or '') != str(v or '')]
        return 'cliente_dados', 'Cliente %s: %s' % (cnome, '; '.join(mud) or 'dados salvos sem mudança'), cid, cnome
    if ep == 'update_dashboard_cliente':
        mud = []
        if 'url' in body and (a.get('dashboard_url') or '') != (body.get('url') or '').strip():
            mud.append('link do dashboard %s → %s' % (a.get('dashboard_url') or '—', (body.get('url') or '').strip() or '—'))
        if 'senha' in body and (a.get('dashboard_senha') or '') != (body.get('senha') or '').strip():
            mud.append('senha do dashboard alterada')  # a senha em si nao vai pro historico
        return 'cliente_dashboard', 'Cliente %s: %s' % (cnome, '; '.join(mud) or 'dashboard salvo sem mudança'), cid, cnome
    if ep == 'add_cliente':
        novo = (res or {}).get('data')
        novo = novo[0] if isinstance(novo, list) and novo else (novo or {})
        return 'cliente_novo', 'Cliente cadastrado: %s (%s/mês)' % (body.get('nome'), _brl(body.get('valor'))), novo.get('id'), body.get('nome')
    if ep == 'set_pagamento':
        mes = va.get('mes')
        if body.get('pago') and body.get('atrasado') is False:
            txt = 'pagamento em atraso quitado'
        elif body.get('pago'):
            txt = 'marcado como pago'
        elif body.get('atrasado'):
            txt = 'marcado como atrasado'
        else:
            txt = 'marcado como pendente'
        return 'pagamento', 'Mensalidade de %s (%s, %s): %s' % (cnome, _mes_txt(mes), _brl(a.get('valor')), txt), cid, cnome
    if ep == 'virar_mes':
        f = (res or {}).get('fechamento') or {}
        return 'virada_mes', 'Virada do faturamento para %s (fechamento: recebido %s de %s, atrasado %s)' % (
            _mes_txt((res or {}).get('mes')), _brl(f.get('recebido')), _brl(f.get('total')), _brl(f.get('atrasado'))), None, None
    if ep == 'add_tarefa':
        t = ((res or {}).get('data') or [{}])
        t = t[0] if isinstance(t, list) and t else {}
        cl = _linha('clientes', t['cliente_id'], 'nome') if t.get('cliente_id') else None
        return 'tarefa_criada', 'Tarefa criada para %s (%s): %s%s' % (_nome_usuario(t.get('responsavel_id')), PRAZO_TXT.get(t.get('prazo'), t.get('prazo')),
                                                                     t.get('titulo') or body.get('titulo'), ' · cliente ' + cl['nome'] if cl else ''), t.get('cliente_id'), cl and cl['nome']
    if ep == 'delete_tarefa':
        nome_cli = (a.get('clientes') or {}).get('nome')
        return 'tarefa_concluida', 'Tarefa concluída (de %s): %s%s' % (_nome_usuario(a.get('responsavel_id')), a.get('titulo'), ' · cliente ' + nome_cli if nome_cli else ''), a.get('cliente_id'), nome_cli
    if ep == 'resetar_tarefas':
        return 'tarefas_resetadas', 'Tarefas da semana resetadas', None, None
    if ep == 'add_venda':
        v = (res or {}).get('data') or {}
        return 'venda', 'Venda: %s para %s, %s (%s)' % (body.get('produto'), body.get('cliente_nome') or (_linha('clientes', body['cliente_id'], 'nome') or {}).get('nome') if body.get('cliente_id') else body.get('cliente_nome'),
                                                        _brl(body.get('valor')), 'paga' if body.get('pago') else 'a receber'), v.get('cliente_id'), None
    if ep == 'update_venda':
        quem = (a.get('clientes') or {}).get('nome') or a.get('cliente_nome')
        txt = ('marcada como paga' if body.get('pago') else 'marcada como pendente') if 'pago' in body else 'valor alterado para ' + _brl(body.get('valor'))
        return 'venda', 'Venda %s (%s, %s): %s' % (a.get('produto'), quem, _brl(a.get('valor')), txt), a.get('cliente_id'), quem
    if ep == 'delete_venda':
        quem = (a.get('clientes') or {}).get('nome') or a.get('cliente_nome')
        return 'venda', 'Venda excluída: %s para %s (%s)' % (a.get('produto'), quem, _brl(a.get('valor'))), a.get('cliente_id'), quem
    if ep == 'add_despesa':
        return 'despesa', 'Despesa lançada: %s (%s) %s em %s' % (body.get('descricao'), body.get('categoria'), _brl(body.get('valor')), _mes_txt(body.get('mes'))), None, None
    if ep == 'update_despesa':
        mud = ['%s: %s → %s' % (k, a.get(k), v) for k, v in body.items() if str(a.get(k)) != str(v)]
        return 'despesa', 'Despesa %s: %s' % (a.get('descricao'), '; '.join(mud) or 'sem mudança'), None, None
    if ep == 'delete_despesa':
        return 'despesa', 'Despesa excluída: %s (%s)' % (a.get('descricao'), _brl(a.get('valor'))), None, None
    if ep == 'marcar_repasses':
        total = sum(float(i.get('valor') or 0) for i in body.get('itens') or [])
        return 'repasse', 'Repasse de %s (%s): %s %s' % (_nome_usuario(body.get('gestor_id')), _mes_txt(body.get('mes')), _brl(total),
                                                         'marcado como pago' if body.get('pago', True) else 'desmarcado'), None, None
    if ep == 'add_negociacao':
        return 'negociacao', 'Negociação criada: %s (%s, %s/mês previsto)' % (body.get('nome'), NEG_STATUS_TXT.get(body.get('status'), body.get('status')), _brl(body.get('valor_previsto'))), None, None
    if ep == 'update_negociacao':
        mud = []
        for k, v in body.items():
            if str(a.get(k) or '') != str(v or ''):
                if k == 'status':
                    mud.append('status %s → %s' % (NEG_STATUS_TXT.get(a.get(k), a.get(k)), NEG_STATUS_TXT.get(v, v)))
                else:
                    mud.append('%s: %s → %s' % (k, a.get(k) or '—', v or '—'))
        return 'negociacao', 'Negociação %s: %s' % (a.get('nome'), '; '.join(mud) or 'sem mudança'), None, None
    if ep == 'fechar_negociacao':
        c = (res or {}).get('cliente') or {}
        return 'negociacao_fechada', 'Negociação fechada: %s virou cliente (%s/mês), com o gestor %s' % (a.get('nome'), _brl(body.get('valor') or a.get('valor_previsto')), (res or {}).get('gestor')), c.get('id'), c.get('nome')
    if ep == 'delete_negociacao':
        return 'negociacao', 'Negociação excluída: %s' % a.get('nome'), None, None
    if ep == 'add_usuario':
        return 'gestor', 'Gestor criado: %s' % body.get('nome'), None, None
    if ep == 'nova_senha_usuario':
        return 'gestor', 'Senha nova gerada para %s' % a.get('nome'), None, None
    if ep == 'set_config':
        chave = va.get('chave')
        valor = '' if 'token' in str(chave) or 'secret' in str(chave) else ' = ' + str(body.get('valor'))[:200]
        return 'configuracao', 'Configuração %s alterada%s' % (chave, valor), None, None
    if ep == 'agenda_criar_evento':
        return 'agenda', 'Evento criado na agenda: %s (%s)' % (body.get('titulo'), body.get('inicio')), None, None
    if ep == 'agenda_desconectar':
        return 'agenda', 'Agenda do Google desconectada', None, None
    return 'outro', '%s %s' % (request.method, request.path), None, None

@app.after_request
def registrar_historico(resp):
    try:
        if request.method not in ('POST', 'PATCH', 'DELETE') or not request.path.startswith('/api/') or resp.status_code >= 400:
            return resp
        ep = request.endpoint
        if ep in SEM_HISTORICO or not check_auth():
            return resp
        res = resp.get_json(silent=True) if resp.is_json else None
        if isinstance(res, dict) and res.get('ok') is False:
            return resp
        body = request.get_json(silent=True) or {}
        acao, desc, cid, cnome = descrever_movimentacao(ep, body, request.view_args or {}, getattr(g, 'antes', None), res)
        registrar(acao, desc, cid, cnome, detalhes={'rota': request.path, 'metodo': request.method})
    except Exception:
        print('HISTORICO DESCRICAO ERROR:', traceback.format_exc())
    return resp

@app.after_request
def sem_cache_api(resp):
    # Dados da API mudam a todo momento (ex.: troca de gestor); o navegador nao deve guardar
    if request.path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-store'
    return resp

def fetch_ads_data(date_preset=None, date_from=None, date_to=None):
    params = {'api_key': WINDSOR_API_KEY, 'fields': FIELDS}
    if date_from and date_to:
        params['date_from'] = date_from
        params['date_to'] = date_to
    else:
        params['date_preset'] = date_preset or 'last_30dT'
    r = requests.get(WINDSOR_BASE, params=params, timeout=60)
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
            agg[name] = {'account_name': name, 'account_id': str(row.get('account_id') or ''), 'spend': spend, 'leads': leads, 'msg': msg}
    result = []
    for v in agg.values():
        total = v['leads'] + v['msg']
        cpl = round(v['spend'] / total, 2) if total else None
        result.append({'account_name': v['account_name'], 'account_id': v['account_id'], 'spend': round(v['spend'], 2),
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
# ── Gestores: prioridade de clientes novos e quem cuida de cada conta ──
PRIORIDADE_DIAS = 30  # cliente novo fica em prioridade nos primeiros 30 dias de contrato

def eh_prioridade(cliente):
    try:
        inicio = datetime.strptime((cliente.get('data_inicio') or '')[:10], '%Y-%m-%d')
    except ValueError:
        return False
    return (datetime.utcnow() - timedelta(hours=3) - inicio).days < PRIORIDADE_DIAS

def mapa_contas():
    # {conta_anuncio: {cliente, cliente_id, gestor_id, gestor, prioridade}} dos clientes ativos
    clientes = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true&select=id,nome,conta_anuncio,contas_anuncio,gestor_id,data_inicio', headers=supa_headers(), timeout=10).json()
    usuarios = {u['id']: u['nome'] for u in requests.get(SUPABASE_URL + '/rest/v1/usuarios?select=id,nome', headers=supa_headers(), timeout=10).json()}
    mapa = {}
    for c in clientes:
        for conta in contas_de(c):
            mapa[conta] = {'cliente': c['nome'], 'cliente_id': c['id'], 'gestor_id': c.get('gestor_id'),
                                        'gestor': usuarios.get(c.get('gestor_id'), ''), 'prioridade': eh_prioridade(c)}
    return mapa

def com_gestor(contas):
    # Acrescenta cliente, gestor e prioridade em cada conta do Meta Ads
    try:
        mapa = mapa_contas()
    except Exception:
        mapa = {}
    vazio = {'cliente': '', 'cliente_id': None, 'gestor_id': None, 'gestor': '', 'prioridade': False}
    return [{**d, **mapa.get(d['account_name'], vazio)} for d in contas]

def contas_de(cliente):
    # Contas de anuncios do cliente (lista); conta_anuncio guarda so a primeira, por compatibilidade
    lista = [x for x in (cliente.get('contas_anuncio') or []) if x]
    if not lista and cliente.get('conta_anuncio'):
        lista = [cliente['conta_anuncio']]
    return lista

def contas_fora_do_painel():
    # Contas de anuncios de clientes pausados/inativos (e que nao estao em nenhum cliente ativo)
    clientes = requests.get(SUPABASE_URL + '/rest/v1/clientes?select=conta_anuncio,contas_anuncio,ativo', headers=supa_headers(), timeout=10).json()
    ativas = {conta for c in clientes if c.get('ativo') for conta in contas_de(c)}
    return {conta for c in clientes if not c.get('ativo') for conta in contas_de(c)} - ativas

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
        # Cliente pausado ou inativo: a conta dele sai da aba Meta Ads (e dos totais)
        try:
            fora = contas_fora_do_painel()
            data = [d for d in data if d['account_name'] not in fora]
        except Exception:
            print('CONTAS FORA ERROR:', traceback.format_exc())
        total_spend = sum(d['spend'] for d in data)
        total_results = sum(d['total'] for d in data)
        total_leads = sum(d['leads'] for d in data)
        total_msg = sum(d['msg'] for d in data)
        active = len([d for d in data if d['spend'] > 0])
        cpl_avg = round(total_spend / total_results, 2) if total_results else 0
        return jsonify({'ok': True, 'kpis': {'spend': round(total_spend, 2), 'results': total_results,
            'leads': total_leads, 'msg': total_msg, 'cpl': cpl_avg, 'active': active, 'total': len(data)}, 'accounts': com_gestor(data)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Chat ──
# ── Chat da equipe (IA com acesso ao sistema) ──
# A IA consulta o painel na hora por ferramentas (clientes, gestores, tarefas, Meta Ads,
# faturamento, financeiro, negociacoes) em vez de receber um resumo fixo.
IA_MODELO = 'claude-opus-5-5'
_ia_cliente = {'c': None}

def ia_cliente():
    if _ia_cliente['c'] is None:
        import anthropic
        _ia_cliente['c'] = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=110, max_retries=1)
    return _ia_cliente['c']

def _norm(t):
    return unicodedata.normalize('NFKD', str(t or '').lower()).encode('ascii', 'ignore').decode().strip()

def _chamar(view, caminho='/', *args):
    # Reaproveita a logica de uma rota do painel e devolve o JSON dela
    with app.test_request_context(caminho):
        r = view(*args)
    if isinstance(r, tuple):
        r = r[0]
    return r.get_json()

def _usuarios():
    return requests.get(SUPABASE_URL + '/rest/v1/usuarios?ativo=eq.true&select=id,nome,username,role&order=id.asc', headers=supa_headers(), timeout=10).json()

def _achar_usuario(nome):
    alvo = _norm(nome)
    us = _usuarios()
    if alvo in ('eu', 'admin', 'andre', 'mim'):
        return next((u for u in us if u['role'] == 'admin'), None)
    return next((u for u in us if _norm(u['nome']) == alvo), None) or next((u for u in us if alvo and alvo in _norm(u['nome'])), None)

def _mes_ou_atual(mes):
    return mes if mes and re.match(r'^\d{4}-\d{2}$', mes) else ler_config('mes_atual')

def ia_listar_clientes(status='ativo', gestor=None, busca=None):
    clientes = requests.get(SUPABASE_URL + '/rest/v1/clientes?select=id,nome,valor,nivel,status,ativo,dia_pagamento,data_inicio,gestor_id,telefone,ocupacao,conta_anuncio,contas_anuncio,checklist&order=nome.asc',
                            headers=supa_headers(), timeout=10).json()
    nomes = {u['id']: u['nome'] for u in _usuarios()}
    g = _achar_usuario(gestor) if gestor else None
    saida = []
    for c in clientes:
        st = 'ativo' if c.get('ativo') else (c.get('status') if c.get('status') in ('pausado', 'inativo') else 'inativo')
        if status != 'todos' and st != status:
            continue
        if g and c.get('gestor_id') != g['id']:
            continue
        if busca and _norm(busca) not in _norm(c['nome']):
            continue
        saida.append({'id': c['id'], 'nome': c['nome'], 'mensalidade': float(c.get('valor') or 0), 'situacao': st,
                      'gestor': nomes.get(c.get('gestor_id'), ''), 'contas_anuncio': contas_de(c),
                      'dia_vencimento': c.get('dia_pagamento'), 'inicio_contrato': c.get('data_inicio'),
                      'prioridade_cliente_novo': st == 'ativo' and eh_prioridade(c),
                      'checklist_pendente': [CHECKLIST_ITENS[k] for k in CHECKLIST_ITENS if not (c.get('checklist') or {}).get(k)]})
    return {'total': len(saida), 'soma_mensalidades': round(sum(x['mensalidade'] for x in saida), 2), 'clientes': saida}

def ia_ver_cliente(cliente):
    alvo = _norm(cliente)
    todos = requests.get(SUPABASE_URL + '/rest/v1/clientes?select=id,nome', headers=supa_headers(), timeout=10).json()
    achado = next((c for c in todos if str(c['id']) == alvo), None) or next((c for c in todos if _norm(c['nome']) == alvo), None) \
        or next((c for c in todos if alvo in _norm(c['nome'])), None)
    if not achado:
        return {'erro': 'Cliente nao encontrado: ' + str(cliente)}
    ficha = _chamar(get_cliente_detalhe, '/', achado['id'])
    d = ficha.get('data') or {}
    nomes = {u['id']: u['nome'] for u in _usuarios()}
    tarefas = requests.get(SUPABASE_URL + '/rest/v1/tarefas?cliente_id=eq.' + str(achado['id']) + '&concluida=eq.false&select=id,titulo,prazo,responsavel_id',
                           headers=supa_headers(), timeout=10).json()
    return {'id': d.get('id'), 'nome': d.get('nome'), 'mensalidade': d.get('valor'), 'situacao': d.get('status'),
            'gestor': nomes.get(d.get('gestor_id'), ''), 'inicio_contrato': d.get('data_inicio'), 'tempo_de_casa_dias': d.get('tempo_casa_dias'),
            'receita_total_gerada': d.get('receita_total'), 'meses_pagos': d.get('meses_pagos'), 'atrasado_agora': d.get('atrasado_atual'),
            'telefone': d.get('telefone'), 'ocupacao': d.get('ocupacao'), 'empresa': d.get('empresa'), 'indicacoes': d.get('indicacoes'),
            'contas_anuncio': d.get('contas_anuncio'), 'meta_ads_30_dias_total': d.get('ads_info'), 'meta_ads_30_dias_por_conta': d.get('ads_contas'),
            'risco_churn': d.get('risco_churn'),
            'checklist': {CHECKLIST_ITENS[k]: bool((d.get('checklist') or {}).get(k)) for k in CHECKLIST_ITENS},
            'onboarding': d.get('onboarding'),
            'tarefas_pendentes': [{'id': t['id'], 'titulo': t['titulo'], 'prazo': t['prazo'], 'responsavel': nomes.get(t['responsavel_id'], '')} for t in tarefas]}

def ia_listar_gestores():
    b = _chamar(gestores_board)
    regras = json.loads(ler_config('remuneracao_gestores') or '{}')
    saida = []
    for u in b.get('usuarios', []):
        meus = [c for c in b.get('clientes', []) if c.get('gestor_id') == u['id']]
        t = (b.get('tarefas') or {}).get(str(u['id']), {'total': 0, 'hoje': 0})
        saida.append({'id': u['id'], 'nome': u['nome'], 'papel': u['role'], 'usuario_login': u['username'],
                      'clientes': [c['nome'] for c in meus], 'qtd_clientes': len(meus),
                      'soma_mensalidades': round(sum(float(c.get('valor') or 0) for c in meus), 2),
                      'contas_anuncio': sorted({x for c in meus for x in (c.get('contas_anuncio') or [])}),
                      'clientes_prioridade': [c['nome'] for c in meus if c.get('prioridade')],
                      'tarefas_pendentes': t['total'], 'tarefas_para_hoje': t['hoje'],
                      'regra_remuneracao': regras.get(str(u['id']))})
    return {'gestores': saida}

def ia_listar_tarefas(responsavel='todos', situacao='pendentes'):
    nomes = {u['id']: u['nome'] for u in _usuarios()}
    url = SUPABASE_URL + '/rest/v1/tarefas?select=id,titulo,prazo,concluida,concluida_em,created_at,responsavel_id,clientes(nome)&order=created_at.asc'
    if situacao == 'concluidas_7_dias':
        desde = (datetime.utcnow() - timedelta(days=7)).isoformat()
        url += '&concluida=eq.true&concluida_em=gte.' + desde
    else:
        url += '&concluida=eq.false'
    if responsavel and _norm(responsavel) != 'todos':
        u = _achar_usuario(responsavel)
        if not u:
            return {'erro': 'Pessoa nao encontrada: ' + str(responsavel)}
        url += '&responsavel_id=eq.' + str(u['id'])
    tarefas = requests.get(url, headers=supa_headers(), timeout=10).json()
    return {'total': len(tarefas), 'tarefas': [{'id': t['id'], 'titulo': t['titulo'], 'prazo': t['prazo'], 'responsavel': nomes.get(t['responsavel_id'], ''),
                                                 'cliente': (t.get('clientes') or {}).get('nome'), 'criada_em': t.get('created_at'),
                                                 'concluida_em': t.get('concluida_em')} for t in tarefas]}

def ia_meta_ads(periodo='30', gestor=None, busca=None):
    if periodo not in ('hoje', 'ontem', '7', '15', '30'):
        periodo = '30'
    j = _chamar(api_data, '/x?period=' + periodo)
    if not j.get('ok'):
        return {'erro': j.get('error')}
    contas = j['accounts']
    if gestor:
        u = _achar_usuario(gestor)
        contas = [a for a in contas if u and a.get('gestor_id') == u['id']]
    if busca:
        contas = [a for a in contas if _norm(busca) in _norm(a['account_name']) or _norm(busca) in _norm(a.get('cliente'))]
    gasto = sum(a['spend'] for a in contas)
    resultados = sum(a['total'] for a in contas)
    return {'periodo': periodo, 'qtd_contas': len(contas), 'investimento': round(gasto, 2), 'resultados': resultados,
            'cpl_medio': round(gasto / resultados, 2) if resultados else None,
            'contas': [{'conta': a['account_name'], 'cliente': a.get('cliente'), 'gestor': a.get('gestor'), 'prioridade': a.get('prioridade'),
                        'investimento': a['spend'], 'leads': a['leads'], 'conversas': a['msg'], 'resultados': a['total'], 'cpl': a['cpl']}
                       for a in sorted(contas, key=lambda a: a['spend'], reverse=True)]}

def ia_faturamento(mes=None):
    mes = _mes_ou_atual(mes)
    j = _chamar(get_pagamentos, '/', mes)
    clientes = j.get('data') or []
    vendas = buscar_vendas('mes=eq.' + mes)
    pagos = [c for c in clientes if c.get('pago')]
    pendentes = [c for c in clientes if not c.get('pago')]
    atrasados = [c for c in clientes if c.get('atrasado')]
    soma = lambda l: round(sum(float(c.get('valor') or 0) for c in l), 2)
    return {'mes': mes, 'mes_do_faturamento_atual': ler_config('mes_atual'),
            'total_esperado_mensalidades': soma(clientes), 'recebido_mensalidades': soma(pagos),
            'a_receber_mensalidades': soma(pendentes), 'qtd_pagos': len(pagos), 'qtd_pendentes': len(pendentes),
            'pendentes': [{'cliente': c['nome'], 'valor': float(c['valor']), 'dia_vencimento': c.get('dia_pagamento')} for c in pendentes],
            'atrasados_do_mes_anterior': [{'cliente': c['nome'], 'valor': float(c['valor'])} for c in atrasados],
            'vendas_de_produtos': [{'produto': v['produto'], 'comprador': v['nome'], 'cliente_da_agencia': bool(v.get('cliente_id')),
                                    'valor': float(v['valor']), 'pago': v['pago']} for v in vendas],
            'fechamentos_de_meses_anteriores': ler_fechamentos()}

def ia_financeiro(mes=None):
    mes = _mes_ou_atual(mes)
    j = _chamar(financeiro_resumo, '/x?mes=' + mes)
    if not j.get('ok'):
        return {'erro': j.get('error')}
    return {'mes': mes, 'entrada': j['entrada'], 'esperado': j['esperado'], 'saida': j['saida'], 'saldo': j['saldo'],
            'saida_por_categoria': j['por_categoria'],
            'despesas': [{'descricao': d['descricao'], 'categoria': d['categoria'], 'valor': float(d['valor']), 'pago': d.get('pago')} for d in j['despesas']],
            'repasses_gestores': [{'gestor': r['gestor'], 'regra': r['regra'], 'total': r['total'], 'pago': r['pago']} for r in j.get('repasses', [])]}

def ia_negociacoes():
    lista = requests.get(SUPABASE_URL + '/rest/v1/negociacoes?order=atualizado_em.desc', headers=supa_headers(), timeout=10).json()
    return {'negociacoes': [{'nome': n['nome'], 'status': n['status'], 'origem': n.get('origem'), 'cargo': n.get('cargo'),
                             'telefone': n.get('telefone'), 'mensalidade_prevista': n.get('valor_previsto'),
                             'previsao_entrada_mes': n.get('previsao_mes'), 'fechado_em': n.get('fechado_em')} for n in lista]}

def ia_historico(desde=None, ate=None, cliente=None, pessoa=None, tipo=None, limite=200):
    # Movimentacoes do painel (o que mudou, quem fez e quando), mais recentes primeiro
    hoje = (datetime.utcnow() - timedelta(hours=3)).date()
    def dia(t, padrao):
        t = (t or '').strip().lower()
        if t in ('', None):
            return padrao
        if t == 'hoje':
            return hoje
        if t == 'ontem':
            return hoje - timedelta(days=1)
        try:
            return datetime.strptime(t[:10], '%Y-%m-%d').date()
        except ValueError:
            return padrao
    d0, d1 = dia(desde, hoje - timedelta(days=7)), dia(ate, hoje)
    # Dias em horario de Brasilia -> intervalo em UTC
    ini = datetime(d0.year, d0.month, d0.day) + timedelta(hours=3)
    fim = datetime(d1.year, d1.month, d1.day) + timedelta(days=1, hours=3)
    params = {'select': 'quando,usuario_nome,acao,cliente_id,cliente_nome,descricao', 'order': 'quando.desc',
              'and': '(quando.gte.%s,quando.lt.%s)' % (ini.isoformat(), fim.isoformat()), 'limit': str(min(int(limite or 200), 500))}
    if tipo:
        params['acao'] = 'eq.' + tipo
    linhas = requests.get(SUPABASE_URL + '/rest/v1/movimentacoes', params=params, headers=supa_headers(), timeout=10).json()
    if not isinstance(linhas, list):
        return {'erro': str(linhas)}
    if cliente:
        linhas = [l for l in linhas if _norm(cliente) in _norm(l.get('cliente_nome')) or _norm(cliente) in _norm(l['descricao'])]
    if pessoa:
        linhas = [l for l in linhas if _norm(pessoa) in _norm(l.get('usuario_nome')) or _norm(pessoa) in _norm(l['descricao'])]
    for l in linhas:
        try:
            l['quando'] = (datetime.fromisoformat(l['quando'].replace('Z', '+00:00')) - timedelta(hours=3)).strftime('%d/%m/%Y %H:%M')
        except ValueError:
            pass
        l['feito_por'] = l.pop('usuario_nome')
    return {'periodo': '%s a %s' % (d0.strftime('%d/%m/%Y'), d1.strftime('%d/%m/%Y')), 'total': len(linhas), 'movimentacoes': linhas,
            'observacao': 'O historico comecou a ser gravado em 13/10/2026; acoes anteriores a isso nao foram registradas.'}

# ── Edicoes do cadastro de clientes pelo chat (so quando o Andre pedir) ──
def _cliente_unico(cliente):
    c = ia_ver_cliente(cliente)
    if c.get('erro'):
        return None, c
    return _linha('clientes', c['id'], CAMPOS_CLIENTE), None

def ia_contas_cliente(cliente, adicionar=None, remover=None):
    c, erro = _cliente_unico(cliente)
    if erro:
        return erro
    disponiveis = [a['account_name'] for a in (_chamar(get_contas_anuncio).get('data') or [])]
    atuais = contas_de(c)
    novas, avisos = list(atuais), []
    for pedido in adicionar or []:
        exata = next((n for n in disponiveis if _norm(n) == _norm(pedido)), None)
        if not exata:
            parecidas = [n for n in disponiveis if _norm(pedido) in _norm(n)]
            if len(parecidas) == 1:
                exata = parecidas[0]
            else:
                return {'erro': 'Conta "%s" %s. Pergunte ao Andre qual e a certa antes de vincular.' % (
                    pedido, 'e ambigua' if parecidas else 'nao encontrada no Meta'), 'opcoes': parecidas[:15]}
        if exata in novas:
            avisos.append('%s ja estava vinculada' % exata)
        else:
            novas.append(exata)
    for pedido in remover or []:
        alvo = next((n for n in novas if _norm(n) == _norm(pedido)), None) or next((n for n in novas if _norm(pedido) in _norm(n)), None)
        if alvo:
            novas.remove(alvo)
        else:
            avisos.append('%s nao estava vinculada' % pedido)
    if novas != atuais:
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.%d' % c['id'], headers=supa_headers(), timeout=10,
                       json={'contas_anuncio': novas, 'conta_anuncio': novas[0] if novas else None}).raise_for_status()
        partes = ['vinculou ' + n for n in novas if n not in atuais] + ['desvinculou ' + n for n in atuais if n not in novas]
        registrar('cliente_contas', 'Cliente %s (pelo chat): %s' % (c['nome'], '; '.join(partes)), c['id'], c['nome'])
    return {'ok': True, 'cliente': c['nome'], 'contas_antes': atuais, 'contas_agora': novas, 'avisos': avisos}

def ia_editar_cliente(cliente, mensalidade=None, dia_vencimento=None, telefone=None, ocupacao=None, empresa=None, inicio_contrato=None):
    c, erro = _cliente_unico(cliente)
    if erro:
        return erro
    dados, mud = {}, []
    if mensalidade is not None:
        v = float(mensalidade)
        if v <= 0:
            return {'erro': 'Mensalidade invalida'}
        dados.update(valor=v, nivel='ouro' if v >= 1500 else 'prata' if v >= 1000 else 'bronze')
        mud.append('mensalidade %s → %s' % (_brl(c.get('valor')), _brl(v)))
    if dia_vencimento is not None:
        d = int(dia_vencimento)
        if not 1 <= d <= 31:
            return {'erro': 'Dia de vencimento deve ser de 1 a 31'}
        dados['dia_pagamento'] = d
        mud.append('vencimento dia %s → dia %s' % (c.get('dia_pagamento') or '—', d))
    if ocupacao is not None:
        o = _norm(ocupacao).replace('imobiliária', 'imobiliaria')
        if o not in OCUPACOES_VALIDAS:
            return {'erro': 'Cargo deve ser um de: ' + ', '.join(OCUPACOES_VALIDAS)}
        dados['ocupacao'] = o
        mud.append('cargo %s → %s' % (c.get('ocupacao') or '—', o))
    for campo, valor, rotulo in (('telefone', telefone, 'telefone'), ('empresa', empresa, 'empresa')):
        if valor is not None:
            dados[campo] = str(valor).strip() or None
            mud.append('%s %s → %s' % (rotulo, c.get(campo) or '—', dados[campo] or '—'))
    if inicio_contrato is not None:
        try:
            dados['data_inicio'] = datetime.strptime(str(inicio_contrato)[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:
            return {'erro': 'Inicio do contrato no formato AAAA-MM-DD'}
        mud.append('início do contrato %s → %s' % (c.get('data_inicio') or '—', dados['data_inicio']))
    # Ignora o que ja estava com o mesmo valor
    iguais = {k for k, v in dados.items() if k != 'nivel' and str(c.get(k) if k != 'valor' else float(c.get('valor') or 0)) == str(v)}
    if 'valor' in iguais:
        dados.pop('nivel', None)
    mud = [m for m, k in zip(mud, [k for k in dados if k != 'nivel']) if k not in iguais]
    dados = {k: v for k, v in dados.items() if k not in iguais}
    if not dados:
        return {'ok': True, 'cliente': c['nome'], 'aviso': 'Nada mudou: os dados ja estavam assim'}
    requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.%d' % c['id'], headers=supa_headers(), json=dados, timeout=10).raise_for_status()
    registrar('cliente_dados', 'Cliente %s (pelo chat): %s' % (c['nome'], '; '.join(mud)), c['id'], c['nome'])
    return {'ok': True, 'cliente': c['nome'], 'alteracoes': mud}

def ia_transferir_cliente(cliente, gestor):
    c, erro = _cliente_unico(cliente)
    if erro:
        return erro
    u = _achar_usuario(gestor)
    if not u:
        return {'erro': 'Gestor nao encontrado: ' + str(gestor)}
    if c.get('gestor_id') == u['id']:
        return {'ok': True, 'aviso': '%s ja e cliente de %s' % (c['nome'], u['nome'])}
    requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.%d' % c['id'], headers=supa_headers(), json={'gestor_id': u['id']}, timeout=10).raise_for_status()
    de = _nome_usuario(c.get('gestor_id'))
    registrar('cliente_transferido', 'Cliente %s transferido de %s para %s (pelo chat)' % (c['nome'], de or 'ninguém', u['nome']), c['id'], c['nome'])
    if u['role'] == 'gestor':
        notificar([u['id']], '🆕 Novo cliente para você', c['nome'] + (' · 🔥 prioridade: cliente novo' if eh_prioridade(c) else ''), '/painel')
    return {'ok': True, 'cliente': c['nome'], 'de': de, 'para': u['nome']}

def ia_situacao_cliente(cliente, situacao):
    if situacao not in ('ativo', 'pausado', 'inativo'):
        return {'erro': 'Situacao deve ser ativo, pausado ou inativo'}
    c, erro = _cliente_unico(cliente)
    if erro:
        return erro
    antes = 'ativo' if c.get('ativo') else (c.get('status') or 'inativo')
    requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.%d' % c['id'], headers=supa_headers(), json=dados_status(situacao), timeout=10).raise_for_status()
    registrar('cliente_situacao', 'Cliente %s (pelo chat): situação %s → %s' % (c['nome'], antes, situacao), c['id'], c['nome'])
    return {'ok': True, 'cliente': c['nome'], 'de': antes, 'para': situacao}

def ia_marcar_pagamento(cliente, pago, mes=None):
    c, erro = _cliente_unico(cliente)
    if erro:
        return erro
    mes = _mes_ou_atual(mes)
    existe = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.%s&cliente_id=eq.%d' % (mes, c['id']), headers=supa_headers(), timeout=10).json()
    dados = {'pago': bool(pago), 'updated_at': datetime.utcnow().isoformat()}
    if existe:
        requests.patch(SUPABASE_URL + '/rest/v1/pagamentos?id=eq.%d' % existe[0]['id'], headers=supa_headers(), json=dados, timeout=10).raise_for_status()
    else:
        requests.post(SUPABASE_URL + '/rest/v1/pagamentos', headers=supa_headers(), json={'mes': mes, 'cliente_id': c['id'], **dados}, timeout=10).raise_for_status()
    registrar('pagamento', 'Mensalidade de %s (%s, %s): marcado como %s (pelo chat)' % (c['nome'], _mes_txt(mes), _brl(c.get('valor')), 'pago' if pago else 'pendente'), c['id'], c['nome'])
    return {'ok': True, 'cliente': c['nome'], 'mes': mes, 'pago': bool(pago)}

def ia_marcar_checklist(cliente, item, feito=True):
    c, erro = _cliente_unico(cliente)
    if erro:
        return erro
    r = marcar_checklist(c['id'], item, feito)
    if not r:
        return {'erro': 'Item invalido: ' + str(item)}
    if r['mudou']:
        registrar('checklist', 'Cliente %s: "%s" %s (pelo chat)' % (c['nome'], CHECKLIST_ITENS[item], 'marcado como feito' if feito else 'desmarcado'), c['id'], c['nome'])
    return {'ok': True, 'cliente': c['nome'], 'checklist': {CHECKLIST_ITENS[k]: v for k, v in r['checklist'].items()}}

def ia_criar_tarefa(titulo, responsavel, prazo='hoje', cliente=None, _autor=None):
    if prazo not in ('hoje', 'amanha', 'semana'):
        return {'erro': 'Prazo deve ser hoje, amanha ou semana'}
    u = _achar_usuario(responsavel)
    if not u:
        return {'erro': 'Responsavel nao encontrado: ' + str(responsavel)}
    payload = {'titulo': titulo.strip(), 'prazo': prazo, 'responsavel_id': u['id']}
    nome_cliente = None
    if cliente:
        c = ia_ver_cliente(cliente)
        if c.get('erro'):
            return c
        payload['cliente_id'] = c['id']
        nome_cliente = c['nome']
    r = requests.post(SUPABASE_URL + '/rest/v1/tarefas', headers=supa_headers(), json=payload, timeout=10)
    r.raise_for_status()
    if _autor and u['id'] != _autor:
        notificar([u['id']], '📋 Nova tarefa', payload['titulo'] + (' · ' + nome_cliente if nome_cliente else ''), '/tarefas')
    registrar('tarefa_criada', 'Tarefa criada pelo chat para %s (%s): %s%s' % (u['nome'], PRAZO_TXT.get(prazo, prazo), payload['titulo'],
              ' · cliente ' + nome_cliente if nome_cliente else ''), payload.get('cliente_id'), nome_cliente)
    return {'ok': True, 'tarefa_id': r.json()[0]['id'], 'responsavel': u['nome'], 'prazo': prazo, 'cliente': nome_cliente}

def ia_concluir_tarefa(tarefa_id):
    r = requests.patch(SUPABASE_URL + '/rest/v1/tarefas?id=eq.' + str(int(tarefa_id)) + '&concluida=eq.false', headers=supa_headers(), timeout=10,
                       json={'concluida': True, 'concluida_em': datetime.utcnow().isoformat()})
    r.raise_for_status()
    if not r.json():
        return {'erro': 'Tarefa nao encontrada ou ja concluida'}
    t = r.json()[0]
    registrar('tarefa_concluida', 'Tarefa concluída pelo chat (de %s): %s' % (_nome_usuario(t.get('responsavel_id')), t['titulo']), t.get('cliente_id'))
    avancar_onboarding(t, current_user())
    return {'ok': True, 'tarefa': t['titulo']}

IA_FERRAMENTAS = [
    {'name': 'listar_clientes', 'description': 'Lista os clientes da agencia com mensalidade, gestor responsavel, contas de anuncio, vencimento, inicio do contrato e se e prioridade (cliente novo). Filtra por situacao, gestor ou parte do nome.',
     'input_schema': {'type': 'object', 'properties': {
         'status': {'type': 'string', 'enum': ['ativo', 'pausado', 'inativo', 'todos'], 'description': 'Padrao: ativo'},
         'gestor': {'type': 'string', 'description': 'Nome do gestor (ex.: Kelmer). Use "eu" para o Andre.'},
         'busca': {'type': 'string', 'description': 'Parte do nome do cliente'}}}},
    {'name': 'ver_cliente', 'description': 'Ficha completa de um cliente: gestor, contrato, receita gerada, atraso, contas de anuncio e numeros do Meta Ads dos ultimos 30 dias, risco de churn e tarefas pendentes.',
     'input_schema': {'type': 'object', 'properties': {'cliente': {'type': 'string', 'description': 'Nome (ou parte) ou id do cliente'}}, 'required': ['cliente']}},
    {'name': 'listar_gestores', 'description': 'Gestores e a carteira de cada um: clientes, contas de anuncio, clientes prioridade, tarefas pendentes e regra de remuneracao.',
     'input_schema': {'type': 'object', 'properties': {}}},
    {'name': 'listar_tarefas', 'description': 'Tarefas pendentes (ou concluidas nos ultimos 7 dias) de uma pessoa ou de todos, com prazo, cliente e responsavel.',
     'input_schema': {'type': 'object', 'properties': {
         'responsavel': {'type': 'string', 'description': 'Nome da pessoa, "eu" para o Andre, ou "todos" (padrao)'},
         'situacao': {'type': 'string', 'enum': ['pendentes', 'concluidas_7_dias']}}}},
    {'name': 'meta_ads', 'description': 'Numeros do Meta Ads por conta (investimento, leads, conversas, resultados, CPL) com cliente e gestor de cada conta. So contas de clientes ativos e contas sem cliente vinculado.',
     'input_schema': {'type': 'object', 'properties': {
         'periodo': {'type': 'string', 'enum': ['hoje', 'ontem', '7', '15', '30'], 'description': 'Padrao: 30 dias'},
         'gestor': {'type': 'string', 'description': 'Filtra as contas de um gestor'},
         'busca': {'type': 'string', 'description': 'Parte do nome da conta ou do cliente'}}}},
    {'name': 'faturamento', 'description': 'Faturamento de um mes: total esperado, recebido, a receber, quem pagou e quem esta pendente (com vencimento), atrasados do mes anterior, vendas de produtos e fechamentos dos meses anteriores.',
     'input_schema': {'type': 'object', 'properties': {'mes': {'type': 'string', 'description': 'AAAA-MM. Padrao: mes atual do faturamento'}}}},
    {'name': 'financeiro', 'description': 'Financeiro de um mes: entrada, saida, saldo, despesas e repasses aos gestores.',
     'input_schema': {'type': 'object', 'properties': {'mes': {'type': 'string', 'description': 'AAAA-MM. Padrao: mes atual'}}}},
    {'name': 'negociacoes', 'description': 'Possiveis clientes em negociacao (status, origem, mensalidade prevista, previsao de entrada) e os ja fechados.',
     'input_schema': {'type': 'object', 'properties': {}}},
    {'name': 'historico', 'description': 'Historico de tudo que foi feito no painel: clientes transferidos entre gestores, cadastrados, pausados/inativados, mudancas de mensalidade, vencimento e contas, pagamentos marcados, virada de mes, tarefas criadas e concluidas, vendas, despesas, repasses, negociacoes e gestores. Cada linha diz o que mudou (de -> para), quem fez e quando.',
     'input_schema': {'type': 'object', 'properties': {
         'desde': {'type': 'string', 'description': 'AAAA-MM-DD, "hoje" ou "ontem". Padrao: 7 dias atras'},
         'ate': {'type': 'string', 'description': 'AAAA-MM-DD, "hoje" ou "ontem". Padrao: hoje'},
         'cliente': {'type': 'string', 'description': 'Filtra por cliente (parte do nome)'},
         'pessoa': {'type': 'string', 'description': 'Filtra por gestor/pessoa citada ou que fez a acao'},
         'tipo': {'type': 'string', 'enum': ['cliente_transferido', 'cliente_novo', 'cliente_situacao', 'cliente_mensalidade', 'cliente_vencimento',
                                             'cliente_contas', 'cliente_dados', 'cliente_indicacoes', 'pagamento', 'virada_mes', 'tarefa_criada',
                                             'tarefa_concluida', 'tarefas_resetadas', 'venda', 'despesa', 'repasse', 'negociacao', 'negociacao_fechada',
                                             'gestor', 'configuracao', 'agenda', 'onboarding', 'checklist']}}}},
    {'name': 'criar_tarefa', 'description': 'Cria uma tarefa no painel para uma pessoa (o gestor e avisado no celular). Use so quando o Andre pedir para criar.',
     'input_schema': {'type': 'object', 'properties': {
         'titulo': {'type': 'string'}, 'responsavel': {'type': 'string', 'description': 'Nome do gestor ou "eu"'},
         'prazo': {'type': 'string', 'enum': ['hoje', 'amanha', 'semana']},
         'cliente': {'type': 'string', 'description': 'Cliente ligado a tarefa (opcional)'}}, 'required': ['titulo', 'responsavel', 'prazo']}},
    {'name': 'contas_do_cliente', 'description': 'Vincula e/ou desvincula contas de anuncio do Meta de um cliente. Confere se a conta existe; se o nome for ambiguo devolve as opcoes para perguntar ao Andre. Use so quando o Andre pedir.',
     'input_schema': {'type': 'object', 'properties': {
         'cliente': {'type': 'string'},
         'adicionar': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Nomes das contas a vincular'},
         'remover': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Nomes das contas a desvincular'}}, 'required': ['cliente']}},
    {'name': 'editar_cliente', 'description': 'Altera dados do cadastro do cliente: mensalidade, dia de vencimento, telefone, cargo (ocupacao), empresa e inicio do contrato. Informe so o que muda. Use so quando o Andre pedir.',
     'input_schema': {'type': 'object', 'properties': {
         'cliente': {'type': 'string'}, 'mensalidade': {'type': 'number'},
         'dia_vencimento': {'type': 'integer', 'description': '1 a 31'}, 'telefone': {'type': 'string'},
         'ocupacao': {'type': 'string', 'enum': ['corretor', 'gerente', 'imobiliaria', 'superintendente', 'diretor', 'outro']},
         'empresa': {'type': 'string'}, 'inicio_contrato': {'type': 'string', 'description': 'AAAA-MM-DD'}}, 'required': ['cliente']}},
    {'name': 'transferir_cliente', 'description': 'Passa o cliente para outro gestor (o gestor e avisado). Use so quando o Andre pedir.',
     'input_schema': {'type': 'object', 'properties': {'cliente': {'type': 'string'}, 'gestor': {'type': 'string', 'description': 'Nome do gestor ou "eu"'}},
                      'required': ['cliente', 'gestor']}},
    {'name': 'situacao_cliente', 'description': 'Muda a situacao do cliente: ativo, pausado (parou por um tempo) ou inativo (saiu). Use so quando o Andre pedir.',
     'input_schema': {'type': 'object', 'properties': {'cliente': {'type': 'string'}, 'situacao': {'type': 'string', 'enum': ['ativo', 'pausado', 'inativo']}},
                      'required': ['cliente', 'situacao']}},
    {'name': 'marcar_pagamento', 'description': 'Marca a mensalidade de um cliente como paga ou pendente num mes (padrao: mes atual do faturamento). Use so quando o Andre pedir.',
     'input_schema': {'type': 'object', 'properties': {'cliente': {'type': 'string'}, 'pago': {'type': 'boolean'},
                                                      'mes': {'type': 'string', 'description': 'AAAA-MM'}}, 'required': ['cliente', 'pago']}},
    {'name': 'marcar_checklist', 'description': 'Marca ou desmarca um item do checklist do cliente: conta_integrada, relatorio_criativivo, grupo_whatsapp, asaas (cadastro no ASAAS). Use so quando o Andre pedir.',
     'input_schema': {'type': 'object', 'properties': {'cliente': {'type': 'string'},
                      'item': {'type': 'string', 'enum': ['conta_integrada', 'relatorio_criativivo', 'grupo_whatsapp', 'asaas']},
                      'feito': {'type': 'boolean', 'description': 'true = feito (padrao), false = desmarcar'}}, 'required': ['cliente', 'item']}},
    {'name': 'concluir_tarefa', 'description': 'Marca uma tarefa como concluida, pelo id (obtido em listar_tarefas). Use so quando o Andre pedir.',
     'input_schema': {'type': 'object', 'properties': {'tarefa_id': {'type': 'integer'}}, 'required': ['tarefa_id']}},
]

def ia_executar(nome, entrada, autor_id=None):
    try:
        if nome == 'listar_clientes':
            r = ia_listar_clientes(entrada.get('status') or 'ativo', entrada.get('gestor'), entrada.get('busca'))
        elif nome == 'ver_cliente':
            r = ia_ver_cliente(entrada['cliente'])
        elif nome == 'listar_gestores':
            r = ia_listar_gestores()
        elif nome == 'listar_tarefas':
            r = ia_listar_tarefas(entrada.get('responsavel') or 'todos', entrada.get('situacao') or 'pendentes')
        elif nome == 'meta_ads':
            r = ia_meta_ads(entrada.get('periodo') or '30', entrada.get('gestor'), entrada.get('busca'))
        elif nome == 'faturamento':
            r = ia_faturamento(entrada.get('mes'))
        elif nome == 'financeiro':
            r = ia_financeiro(entrada.get('mes'))
        elif nome == 'negociacoes':
            r = ia_negociacoes()
        elif nome == 'historico':
            r = ia_historico(entrada.get('desde'), entrada.get('ate'), entrada.get('cliente'), entrada.get('pessoa'), entrada.get('tipo'))
        elif nome == 'criar_tarefa':
            r = ia_criar_tarefa(entrada['titulo'], entrada['responsavel'], entrada.get('prazo') or 'hoje', entrada.get('cliente'), _autor=autor_id)
        elif nome == 'contas_do_cliente':
            r = ia_contas_cliente(entrada['cliente'], entrada.get('adicionar'), entrada.get('remover'))
        elif nome == 'editar_cliente':
            r = ia_editar_cliente(entrada['cliente'], entrada.get('mensalidade'), entrada.get('dia_vencimento'), entrada.get('telefone'),
                                  entrada.get('ocupacao'), entrada.get('empresa'), entrada.get('inicio_contrato'))
        elif nome == 'transferir_cliente':
            r = ia_transferir_cliente(entrada['cliente'], entrada['gestor'])
        elif nome == 'situacao_cliente':
            r = ia_situacao_cliente(entrada['cliente'], entrada['situacao'])
        elif nome == 'marcar_pagamento':
            r = ia_marcar_pagamento(entrada['cliente'], entrada['pago'], entrada.get('mes'))
        elif nome == 'marcar_checklist':
            r = ia_marcar_checklist(entrada['cliente'], entrada['item'], entrada.get('feito', True))
        elif nome == 'concluir_tarefa':
            r = ia_concluir_tarefa(entrada['tarefa_id'])
        else:
            return json.dumps({'erro': 'Ferramenta desconhecida'}), True
        return json.dumps(r, ensure_ascii=False, default=str), bool(isinstance(r, dict) and r.get('erro'))
    except Exception as e:
        print('IA FERRAMENTA ERROR:', nome, traceback.format_exc())
        return json.dumps({'erro': str(e)}), True

IA_INSTRUCOES = TEAM_INTRO + (
    'ACESSO AO SISTEMA: voce TEM acesso completo ao painel da agencia pelas ferramentas (clientes, gestores e a carteira '
    'de cada um, tarefas, Meta Ads por conta, faturamento, financeiro, repasses e negociacoes). Antes de responder qualquer '
    'pergunta sobre dados, consulte a ferramenta certa; nunca diga que nao tem acesso nem peca ao Andre dados que estao no '
    'sistema. Nao invente numeros: use so o que as ferramentas devolverem. Valores em reais no formato R$ 1.234,56. '
    'Voce tambem consegue ALTERAR o sistema: criar e concluir tarefas, vincular/desvincular contas de anuncio, editar dados do '
    'cliente (mensalidade, vencimento, telefone, cargo, empresa, inicio do contrato), transferir cliente de gestor, mudar a '
    'situacao (ativo/pausado/inativo), marcar pagamentos e marcar o checklist do cliente. Faca alteracoes so quando o Andre pedir explicitamente; nunca diga '
    'que nao consegue alterar algo que uma ferramenta faz. Se faltar informacao ou o nome for ambiguo (ex.: mais de uma conta '
    'parecida), pergunte antes de alterar. Depois de alterar, confirme exatamente o que mudou (de -> para). '
    'Para perguntas sobre o que aconteceu (transferencias, quem fez o que, mudancas, o que foi feito hoje/ontem), use a '
    'ferramenta historico.'
)

def ia_responder(historico, autor_id=None):
    # Laço de ferramentas: a IA consulta o sistema quantas vezes precisar e devolve a resposta final
    hoje = (datetime.utcnow() - timedelta(hours=3))
    contexto = 'Hoje e %s (horario de Brasilia). Mes atual do faturamento: %s.' % (hoje.strftime('%d/%m/%Y %H:%M'), ler_config('mes_atual'))
    mensagens = list(historico)
    for _ in range(8):
        resp = ia_cliente().beta.messages.create(
            model=IA_MODELO, max_tokens=16000,
            system=[{'type': 'text', 'text': IA_INSTRUCOES, 'cache_control': {'type': 'ephemeral'}},
                    {'type': 'text', 'text': contexto}],
            tools=IA_FERRAMENTAS, messages=mensagens,
            output_config={'effort': 'medium'},
            betas=['server-side-fallback-2026-07-01'], fallbacks='default')
        if resp.stop_reason == 'refusal':
            return 'Não consegui responder a esse pedido.'
        usos = [b for b in resp.content if b.type == 'tool_use']
        if resp.stop_reason != 'tool_use' or not usos:
            return '\n\n'.join(b.text for b in resp.content if b.type == 'text').strip() or 'Sem resposta.'
        mensagens.append({'role': 'assistant', 'content': resp.content})
        resultados = []
        for u in usos:
            conteudo, erro = ia_executar(u.name, u.input or {}, autor_id)
            resultados.append({'type': 'tool_result', 'tool_use_id': u.id, 'content': conteudo, 'is_error': erro})
        mensagens.append({'role': 'user', 'content': resultados})
    return 'Precisei consultar dados demais para essa pergunta. Pode detalhar um pouco mais?'

@app.route('/api/chat', methods=['POST'])
def api_chat():
    try:
        body = request.json or {}
        clean = []
        for m in body.get('messages', []):
            role, content = m.get('role', ''), m.get('content', '')
            if role in ('user', 'assistant') and content:
                clean.append({'role': role, 'content': str(content)})
        if not clean or clean[-1]['role'] != 'user':
            return jsonify({'ok': False, 'error': 'Mensagem vazia'}), 400
        if clean[0]['role'] != 'user':
            clean = [{'role': 'user', 'content': 'Ola'}] + clean
        # Ultimas mensagens da conversa, sempre comecando por uma do usuario
        recentes = clean[-20:]
        while recentes and recentes[0]['role'] != 'user':
            recentes = recentes[1:]
        return jsonify({'ok': True, 'reply': ia_responder(recentes, current_user()['id'])})
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
def despesas_do_mes(mes):
    url = SUPABASE_URL + '/rest/v1/despesas?mes=eq.' + mes + '&order=categoria.asc,valor.desc'
    despesas = requests.get(url, headers=supa_headers(), timeout=10).json()
    # Mes ainda vazio (ate o mes corrente): traz as despesas do mes anterior, como pendentes
    mes_corrente = (datetime.utcnow() - timedelta(hours=3)).strftime('%Y-%m')
    if despesas or mes > mes_corrente:
        return despesas
    ano, m = int(mes[:4]), int(mes[5:])
    mes_ant = str(ano - 1) + '-12' if m == 1 else str(ano) + '-' + str(m - 1).zfill(2)
    anteriores = requests.get(SUPABASE_URL + '/rest/v1/despesas?mes=eq.' + mes_ant, headers=supa_headers(), timeout=10).json()
    if not anteriores:
        return despesas
    copias = [{'mes': mes, 'descricao': d['descricao'], 'categoria': d['categoria'], 'valor': d['valor'],
               'recorrente': d.get('recorrente', False), 'pago': False} for d in anteriores]
    requests.post(SUPABASE_URL + '/rest/v1/despesas', headers=supa_headers(), json=copias, timeout=10).raise_for_status()
    return requests.get(url, headers=supa_headers(), timeout=10).json()

@app.route('/api/despesas', methods=['GET'])
def get_despesas():
    try:
        mes = request.args.get('mes', datetime.utcnow().strftime('%Y-%m'))
        return jsonify({'ok': True, 'data': despesas_do_mes(mes)})
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
        fechamento = ler_fechamentos().get(mes)
        if fechamento and mes != ler_config('mes_atual'):
            # Mes ja fechado: usa o que foi gravado na virada (ja inclui vendas a clientes)
            avulsas = fechamento.get('avulsas') or {}
            entrada = float(fechamento['recebido']) + float(avulsas.get('recebido') or 0)
            esperado = float(fechamento.get('total') or fechamento['recebido']) + float(avulsas.get('total') or 0)
        else:
            entrada = sum(float(clientes[p['cliente_id']]['valor']) for p in pagamentos if p.get('pago') and p['cliente_id'] in clientes)
            esperado = sum(float(c['valor']) for c in clientes.values())
            # Vendas de produtos do mes (clientes e avulsas)
            try:
                vendas = buscar_vendas('mes=eq.' + mes)
            except Exception:
                vendas = []
            entrada += sum(float(v['valor']) for v in vendas if v['pago'])
            esperado += sum(float(v['valor']) for v in vendas)

        despesas = despesas_do_mes(mes)
        saida_total = sum(float(d['valor']) for d in despesas)
        por_categoria = {'fixo': 0.0, 'variavel': 0.0, 'salario': 0.0, 'repasses': 0.0}
        for d in despesas:
            cat = d.get('categoria')
            if cat in por_categoria:
                por_categoria[cat] += float(d['valor'])
        # Repasses aos gestores: calculados pela regra de cada um e pelos clientes que ele tem hoje
        repasses = []
        try:
            regras = json.loads(ler_config('remuneracao_gestores') or '{}')
            nomes = {x['id']: x['nome'] for x in requests.get(SUPABASE_URL + '/rest/v1/usuarios?ativo=eq.true&select=id,nome', headers=supa_headers(), timeout=10).json()}
            hoje = (datetime.utcnow() - timedelta(hours=3)).strftime('%Y-%m-%d')
            for gid_txt, regra in regras.items():
                gid = int(gid_txt)
                if gid not in nomes:
                    continue
                texto, itens = calcular_repasses(gid, regra, mes, hoje)
                total = sum(float(i['valor']) for i in itens)
                pago = sum(float(i['valor']) for i in itens if i.get('pago'))
                repasses.append({'gestor_id': gid, 'gestor': nomes[gid], 'regra': texto, 'total': round(total, 2),
                                 'pago': round(pago, 2), 'itens': [{'chave': i['chave'], 'valor': i['valor']} for i in itens]})
        except Exception:
            print('REPASSES ERROR:', traceback.format_exc())
        total_repasses = sum(r['total'] for r in repasses)
        por_categoria['repasses'] = total_repasses
        saida_total += total_repasses
        saldo = entrada - saida_total
        return jsonify({
            'ok': True, 'mes': mes,
            'entrada': round(entrada, 2), 'esperado': round(esperado, 2),
            'saida': round(saida_total, 2), 'saldo': round(saldo, 2),
            'por_categoria': {k: round(v, 2) for k, v in por_categoria.items()},
            'despesas': despesas, 'repasses': repasses
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
        # ?todos=1 traz tambem pausados e inativos (aba Clientes); o resto do painel usa so os ativos
        filtro = '' if request.args.get('todos') else 'ativo=eq.true&'
        r = requests.get(SUPABASE_URL + '/rest/v1/clientes?' + filtro + 'order=nivel.asc,valor.desc', headers=supa_headers())
        return jsonify({'ok': True, 'data': [{**c, 'prioridade': bool(c.get('ativo')) and eh_prioridade(c)} for c in r.json()]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes', methods=['POST'])
def add_cliente():
    try:
        body = request.json
        r = requests.post(SUPABASE_URL + '/rest/v1/clientes', headers=supa_headers(), json=body)
        novo = r.json()
        if r.ok and isinstance(novo, list) and novo:
            criar_etapa_onboarding(novo[0]['id'], 1, current_user())
        return jsonify({'ok': True, 'data': novo})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Checklist do cliente (itens marcados a mao ou pelo onboarding) ──
CHECKLIST_ITENS = {'conta_integrada': 'Conta integrada', 'relatorio_criativivo': 'Relatório Criativivo',
                   'grupo_whatsapp': 'Grupo WhatsApp', 'asaas': 'Cadastrar cliente no ASAAS'}

def marcar_checklist(cliente_id, item, feito):
    c = _linha('clientes', cliente_id, 'id,nome,checklist')
    if not c or item not in CHECKLIST_ITENS:
        return None
    lista = {k: bool((c.get('checklist') or {}).get(k)) for k in CHECKLIST_ITENS}
    lista[item] = bool(feito)
    requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.%d' % int(cliente_id), headers=supa_headers(), json={'checklist': lista}, timeout=10).raise_for_status()
    return {'cliente': c['nome'], 'checklist': lista, 'mudou': bool((c.get('checklist') or {}).get(item)) != bool(feito)}

@app.route('/api/clientes/<int:id>/checklist', methods=['PATCH'])
def update_checklist_cliente(id):
    try:
        body = request.json or {}
        if body.get('item') not in CHECKLIST_ITENS:
            return jsonify({'ok': False, 'error': 'Item invalido'}), 400
        r = marcar_checklist(id, body['item'], body.get('feito'))
        if not r:
            return jsonify({'ok': False, 'error': 'Cliente nao encontrado'}), 404
        return jsonify({'ok': True, 'checklist': r['checklist']})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Onboarding de cliente novo ──
# Etapas em config.onboarding_etapas: [{titulo (com {cliente} e {gestor}), quem: admin|gestor, prazo}].
# Uma etapa por vez: ao concluir a tarefa da etapa N, a etapa N+1 e criada para a pessoa certa.
ONBOARDING_DIAS = 5  # o onboarding inteiro deve terminar em ate 5 dias

def etapas_onboarding():
    try:
        return json.loads(ler_config('onboarding_etapas') or '[]')
    except Exception:
        return []

def criar_etapa_onboarding(cliente_id, n, autor=None):
    etapas = etapas_onboarding()
    if n < 1 or n > len(etapas):
        return None
    e = etapas[n - 1]
    c = _linha('clientes', cliente_id, 'id,nome,gestor_id')
    if not c:
        return None
    usuarios = requests.get(SUPABASE_URL + '/rest/v1/usuarios?ativo=eq.true&select=id,nome,role&order=id.asc', headers=supa_headers(), timeout=10).json()
    admin = next((u for u in usuarios if u['role'] == 'admin'), None)
    gestor = next((u for u in usuarios if u['id'] == c.get('gestor_id')), None) or admin
    resp = gestor if e.get('quem') == 'gestor' else admin
    titulo = e['titulo'].replace('{cliente}', c['nome']).replace('{gestor}', gestor['nome'] if gestor else 'o gestor')
    tarefa = {'titulo': '🚀 ' + titulo, 'prazo': e.get('prazo') if e.get('prazo') in ('hoje', 'amanha', 'semana') else 'hoje',
              'responsavel_id': resp['id'], 'cliente_id': c['id'], 'onboarding_etapa': n}
    r = requests.post(SUPABASE_URL + '/rest/v1/tarefas', headers=supa_headers(), json=tarefa, timeout=10)
    r.raise_for_status()
    if not autor or resp['id'] != autor.get('id'):
        notificar([resp['id']], '🚀 Onboarding %s · etapa %d/%d' % (c['nome'], n, len(etapas)), titulo, '/tarefas')
    registrar('onboarding', 'Onboarding de %s: etapa %d/%d criada para %s: %s' % (c['nome'], n, len(etapas), resp['nome'], titulo),
              c['id'], c['nome'], usuario=autor if autor is not None else {})
    return r.json()[0]

def avancar_onboarding(tarefa, autor=None):
    # Chamado quando uma tarefa e concluida: se for etapa de onboarding, cria a proxima
    n = tarefa.get('onboarding_etapa')
    if not n or not tarefa.get('cliente_id'):
        return
    try:
        etapas = etapas_onboarding()
        item = etapas[n - 1].get('marca') if n <= len(etapas) else None
        if item:
            r = marcar_checklist(tarefa['cliente_id'], item, True)
            if r and r['mudou']:
                registrar('checklist', 'Cliente %s: "%s" marcado automaticamente ao concluir a etapa %d do onboarding' % (r['cliente'], CHECKLIST_ITENS[item], n),
                          tarefa['cliente_id'], r['cliente'], usuario=autor if autor is not None else {})
        total = len(etapas)
        if n < total:
            criar_etapa_onboarding(tarefa['cliente_id'], n + 1, autor)
        else:
            c = _linha('clientes', tarefa['cliente_id'], 'id,nome')
            registrar('onboarding', 'Onboarding de %s concluído (%d etapas)' % (c and c['nome'], total), tarefa['cliente_id'], c and c['nome'],
                      usuario=autor if autor is not None else {})
    except Exception:
        print('ONBOARDING ERROR:', traceback.format_exc())

def progresso_onboarding(cliente_id):
    etapas = etapas_onboarding()
    tarefas = requests.get(SUPABASE_URL + '/rest/v1/tarefas?cliente_id=eq.%d&onboarding_etapa=not.is.null&select=id,titulo,concluida,concluida_em,created_at,responsavel_id,onboarding_etapa&order=onboarding_etapa.asc' % int(cliente_id),
                           headers=supa_headers(), timeout=10).json()
    if not isinstance(tarefas, list) or not tarefas:
        return None
    por_etapa = {t['onboarding_etapa']: t for t in tarefas}
    c = _linha('clientes', cliente_id, 'nome,gestor_id') or {}
    saida = []
    for i, e in enumerate(etapas, 1):
        t = por_etapa.get(i)
        previsto = e['titulo'].replace('{cliente}', c.get('nome') or '').replace('{gestor}', _nome_usuario(c.get('gestor_id')) or 'o gestor')
        saida.append({'etapa': i, 'titulo': t['titulo'].replace('🚀 ', '', 1) if t else previsto,
                      'quem': e.get('quem'), 'situacao': 'concluida' if t and t['concluida'] else ('em_andamento' if t else 'aguardando'),
                      'responsavel': _nome_usuario(t['responsavel_id']) if t else None, 'concluida_em': t and t.get('concluida_em')})
    concluidas = sum(1 for s in saida if s['situacao'] == 'concluida')
    # Prazo do processo: ate 5 dias a partir da primeira etapa
    inicio = datetime.fromisoformat(str(por_etapa.get(1, tarefas[0])['created_at'])[:19]) - timedelta(hours=3)
    prazo = (inicio + timedelta(days=ONBOARDING_DIAS)).date()
    hoje = (datetime.utcnow() - timedelta(hours=3)).date()
    return {'total': len(etapas), 'concluidas': concluidas, 'etapas': saida, 'inicio': inicio.strftime('%Y-%m-%d'),
            'prazo_final': prazo.strftime('%Y-%m-%d'), 'atrasado': concluidas < len(etapas) and hoje > prazo,
            'dias_restantes': (prazo - hoje).days}

def dados_status(status):
    # 'ativo' continua sendo o campo que o resto do painel usa; status diz se esta pausado ou inativo
    agora = datetime.utcnow().isoformat()
    return {'status': status, 'ativo': status == 'ativo',
            'pausado_em': agora if status == 'pausado' else None,
            'inativado_em': agora if status == 'inativo' else None}

@app.route('/api/clientes/<int:id>/status', methods=['PATCH'])
def update_status_cliente(id):
    try:
        status = (request.json or {}).get('status')
        if status not in ('ativo', 'pausado', 'inativo'):
            return jsonify({'ok': False, 'error': 'Status invalido'}), 400
        r = requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json=dados_status(status), timeout=10)
        r.raise_for_status()
        if not r.json():
            return jsonify({'ok': False, 'error': 'Cliente nao encontrado'}), 404
        return jsonify({'ok': True, 'data': r.json()[0]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>', methods=['DELETE'])
def delete_cliente(id):
    try:
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json=dados_status('inativo'))
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

        ads_info, ads_contas = None, []
        contas = contas_de(cliente)
        if contas:
            try:
                ads_data = fetch_ads_data(date_preset='last_30dT')
                renomes = corrigir_vinculos_renomeados(set(contas), ads_data)
                contas = [renomes.get(c, c) for c in contas]
                por_nome = {a['account_name']: a for a in ads_data}
                ads_contas = [por_nome.get(c) or {'account_name': c, 'spend': 0, 'leads': 0, 'msg': 0, 'total': 0, 'cpl': None, 'sem_dados': True}
                              for c in contas]
                com_dados = [a for a in ads_contas if not a.get('sem_dados')]
                if com_dados:
                    spend = round(sum(a['spend'] for a in com_dados), 2)
                    total = sum(a['total'] for a in com_dados)
                    ads_info = {'spend': spend, 'leads': sum(a['leads'] for a in com_dados), 'msg': sum(a['msg'] for a in com_dados),
                                'total': total, 'cpl': round(spend / total, 2) if total else None}
            except Exception:
                ads_info = None
        cliente['contas_anuncio'] = contas

        risco = calcular_risco_churn(ads_info, atrasado_atual, meses_atraso_recente)

        return jsonify({'ok': True, 'data': {
            **cliente,
            'tempo_casa_dias': tempo_casa_dias,
            'receita_total': receita_total,
            'meses_pagos': len(meses_pagos),
            'atrasado_atual': atrasado_atual,
            'ads_info': ads_info,
            'ads_contas': ads_contas,
            'onboarding': progresso_onboarding(id),
            'risco_churn': risco
        }})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>/contas', methods=['PATCH'])
def update_contas_cliente(id):
    # Lista de contas de anuncios do cliente (sem repetir, na ordem escolhida)
    try:
        contas = []
        for c in (request.json or {}).get('contas') or []:
            c = str(c).strip()
            if c and c not in contas:
                contas.append(c[:200])
        r = requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), timeout=10,
                           json={'contas_anuncio': contas, 'conta_anuncio': contas[0] if contas else None})
        r.raise_for_status()
        if not r.json():
            return jsonify({'ok': False, 'error': 'Cliente nao encontrado'}), 404
        return jsonify({'ok': True, 'contas': contas})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>/perfil', methods=['PATCH'])
def update_perfil_cliente(id):
    try:
        body = request.json or {}
        campos = {}
        for campo in ['nome', 'telefone', 'ocupacao', 'empresa', 'data_inicio']:
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

_contas_cache = {'em': None, 'dados': []}

def fetch_contas_conectadas():
    # Todas as contas Meta conectadas no Windsor, mesmo sem gasto no periodo: [(id, nome)].
    # O nome desta lista pode estar desatualizado quando a conta e renomeada no Meta.
    agora = datetime.utcnow()
    if _contas_cache['em'] and agora - _contas_cache['em'] < timedelta(minutes=10):
        return _contas_cache['dados']
    r = requests.get('https://onboard.windsor.ai/api/common/ds-accounts',
                     params={'datasource': 'facebook', 'api_key': WINDSOR_API_KEY}, timeout=30)
    r.raise_for_status()
    dados = [(str(a.get('account_id') or ''), (a.get('account_name') or '').strip()) for a in r.json()]
    _contas_cache.update(em=agora, dados=dados)
    return dados

def contas_renomeadas(ads_data):
    # {nome antigo: nome atual}, comparando o id da conta na lista do Windsor com o dos dados
    atual = {a['account_id']: a['account_name'] for a in ads_data if a.get('account_id')}
    try:
        conectadas = fetch_contas_conectadas()
    except Exception:
        return {}
    return {nome: atual[i] for i, nome in conectadas if i in atual and nome and atual[i] != nome}

def corrigir_vinculos_renomeados(nomes_vinculados, ads_data):
    # Cliente vinculado ao nome antigo de uma conta renomeada passa a usar o nome atual
    renomes = {antigo: novo for antigo, novo in contas_renomeadas(ads_data).items() if antigo in nomes_vinculados}
    for antigo, novo in renomes.items():
        filtro = 'contas_anuncio.cs.{"' + antigo.replace('"', '\\"') + '"},conta_anuncio.eq."' + antigo.replace('"', '\\"') + '"'
        afetados = requests.get(SUPABASE_URL + '/rest/v1/clientes', params={'or': '(' + filtro + ')', 'select': 'id,conta_anuncio,contas_anuncio'},
                                headers=supa_headers(), timeout=10).json()
        for c in afetados if isinstance(afetados, list) else []:
            lista = [novo if x == antigo else x for x in contas_de(c)]
            requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(c['id']), headers=supa_headers(), timeout=10,
                           json={'contas_anuncio': lista, 'conta_anuncio': lista[0] if lista else None})
            registrar('cliente_contas', 'Conta "%s" foi renomeada no Meta para "%s"; vínculo do cliente atualizado automaticamente' % (antigo, novo),
                      c['id'], None, usuario={})
    return renomes

_contas_anuncio_cache = {'em': None, 'dados': None}

@app.route('/api/contas-anuncio', methods=['GET'])
def get_contas_anuncio():
    # Junta as contas conectadas com as que tiveram gasto em 30 dias,
    # para que contas novas ou pausadas tambem aparecam na busca.
    # O Windsor demora ate 1 min nessa consulta: guarda o resultado por 10 min.
    agora = datetime.utcnow()
    if _contas_anuncio_cache['em'] and agora - _contas_anuncio_cache['em'] < timedelta(minutes=10):
        return jsonify({'ok': True, 'data': _contas_anuncio_cache['dados']})
    erros = []
    try:
        ads_data = fetch_ads_data(date_preset='last_30dT')
    except Exception as e:
        ads_data, erros = [], erros + [str(e)]
    com_dados = {a['account_name'] for a in ads_data}
    com_gasto = {a['account_name'] for a in ads_data if a['spend'] > 0}
    atual = {a['account_id']: a['account_name'] for a in ads_data if a.get('account_id')}
    try:
        # Conta renomeada no Meta aparece so com o nome atual
        conectadas = {atual.get(i, nome) for i, nome in fetch_contas_conectadas()}
    except Exception as e:
        conectadas, erros = set(), erros + [str(e)]
    todas = sorted((conectadas | com_dados) - {''}, key=str.lower)
    if not todas and erros:
        return jsonify({'ok': False, 'error': '; '.join(erros)}), 500
    dados = [{'account_name': n, 'com_gasto': n in com_gasto} for n in todas]
    if not erros:
        _contas_anuncio_cache.update(em=agora, dados=dados)
    return jsonify({'ok': True, 'data': dados})

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

@app.route('/api/usuarios/<int:id>/nova-senha', methods=['POST'])
def nova_senha_usuario(id):
    # Admin gera uma senha nova para um gestor; ela e mostrada uma unica vez
    try:
        alvo = requests.get(SUPABASE_URL + '/rest/v1/usuarios?id=eq.' + str(id) + '&select=id,nome,username,role', headers=supa_headers(), timeout=10).json()
        if not alvo:
            return jsonify({'ok': False, 'error': 'Usuario nao encontrado'}), 404
        if alvo[0]['role'] != 'gestor':
            return jsonify({'ok': False, 'error': 'So e possivel gerar senha nova para gestores'}), 400
        senha = gerar_senha_temp()
        r = requests.patch(SUPABASE_URL + '/rest/v1/usuarios?id=eq.' + str(id), headers=supa_headers(), json={'senha_hash': hash_senha(senha)}, timeout=10)
        r.raise_for_status()
        if not r.json():
            return jsonify({'ok': False, 'error': 'O banco nao confirmou a troca'}), 500
        return jsonify({'ok': True, 'data': {'nome': alvo[0]['nome'], 'username': alvo[0]['username'], 'senha_temp': senha}})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/gestores/board', methods=['GET'])
def gestores_board():
    try:
        ur = requests.get(SUPABASE_URL + '/rest/v1/usuarios?ativo=eq.true&select=id,nome,username,role&order=id.asc', headers=supa_headers())
        usuarios = ur.json()
        cr = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true&select=id,nome,empresa,valor,nivel,gestor_id,conta_anuncio,contas_anuncio,data_inicio&order=nome.asc', headers=supa_headers())
        clientes = [{**c, 'contas_anuncio': contas_de(c), 'prioridade': eh_prioridade(c)} for c in cr.json()]
        # Tarefas pendentes de cada pessoa (total e para hoje)
        tr = requests.get(SUPABASE_URL + '/rest/v1/tarefas?concluida=eq.false&select=responsavel_id,prazo', headers=supa_headers(), timeout=10).json()
        tarefas = {}
        for t in tr if isinstance(tr, list) else []:
            p = tarefas.setdefault(str(t['responsavel_id']), {'total': 0, 'hoje': 0})
            p['total'] += 1
            p['hoje'] += t.get('prazo') == 'hoje'
        return jsonify({'ok': True, 'usuarios': usuarios, 'clientes': clientes, 'tarefas': tarefas})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>/gestor', methods=['PATCH'])
def update_gestor_cliente(id):
    try:
        body = request.json or {}
        gestor_id = body.get('gestor_id')
        if not gestor_id:
            return jsonify({'ok': False, 'error': 'gestor_id obrigatorio'}), 400
        r = requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(id), headers=supa_headers(), json={'gestor_id': gestor_id}, timeout=10)
        r.raise_for_status()
        # Confirma que o cliente realmente mudou de gestor (antes uma falha passava em silencio)
        if not r.json() or r.json()[0].get('gestor_id') != int(gestor_id):
            return jsonify({'ok': False, 'error': 'O banco nao confirmou a troca'}), 500
        c = r.json()[0]
        if int(gestor_id) != current_user()['id']:
            notificar([gestor_id], '🆕 Novo cliente para você', c['nome'] + (' · 🔥 prioridade: cliente novo' if eh_prioridade(c) else ''), '/painel')
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Meta Ads (visao limitada do gestor) ──
@app.route('/api/meta-ads/minhas-contas', methods=['GET'])
def meta_ads_minhas_contas():
    # Consulta leve (so banco): o painel do gestor chama a cada poucos segundos
    # para refletir na hora as trocas feitas no quadro Gestores
    try:
        u = current_user()
        cr = requests.get(SUPABASE_URL + '/rest/v1/clientes?gestor_id=eq.' + str(u['id']) + '&ativo=eq.true&select=conta_anuncio,contas_anuncio', headers=supa_headers(), timeout=10)
        cr.raise_for_status()
        contas = sorted({conta for c in cr.json() for conta in contas_de(c)}, key=str.lower)
        return jsonify({'ok': True, 'contas': contas})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/meta-ads/minhas', methods=['GET'])
def meta_ads_minhas():
    try:
        u = current_user()
        if not u:
            return jsonify({'ok': False, 'error': 'Nao autorizado'}), 401
        period = request.args.get('period', '30')
        cr = requests.get(SUPABASE_URL + '/rest/v1/clientes?gestor_id=eq.' + str(u['id']) + '&ativo=eq.true&select=conta_anuncio,contas_anuncio', headers=supa_headers())
        contas = {conta for c in cr.json() for conta in contas_de(c)}
        if period == 'hoje':
            hoje = datetime.utcnow().strftime('%Y-%m-%d')
            data_all = fetch_ads_data(date_from=hoje, date_to=hoje)
        elif period == 'ontem':
            ontem = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
            data_all = fetch_ads_data(date_from=ontem, date_to=ontem)
        else:
            preset = PRESETS.get(period, 'last_30dT')
            data_all = fetch_ads_data(date_preset=preset)
        renomes = corrigir_vinculos_renomeados(contas, data_all)
        contas = {renomes.get(n, n) for n in contas}
        data = [d for d in data_all if d['account_name'] in contas]
        # Contas vinculadas sem gasto no periodo tambem aparecem (zeradas), para bater com o quadro Gestores
        com_dados = {d['account_name'] for d in data}
        data += [{'account_name': n, 'spend': 0, 'leads': 0, 'msg': 0, 'total': 0, 'cpl': None}
                 for n in sorted(contas - com_dados, key=str.lower)]
        total_spend = sum(d['spend'] for d in data)
        total_results = sum(d['total'] for d in data)
        total_leads = sum(d['leads'] for d in data)
        total_msg = sum(d['msg'] for d in data)
        active = len([d for d in data if d['spend'] > 0])
        cpl_avg = round(total_spend / total_results, 2) if total_results else 0
        return jsonify({'ok': True, 'kpis': {'spend': round(total_spend, 2), 'results': total_results,
            'leads': total_leads, 'msg': total_msg, 'cpl': cpl_avg, 'active': active, 'total': len(data)}, 'accounts': com_gestor(data)})
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
            # 'atrasado' = ainda deve o mes anterior; nao depende do pagamento do mes atual
            result.append({**c, 'pago': p.get('pago', False), 'atrasado': c['id'] in atrasados_ant, 'pag_id': p.get('id')})
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

def ler_config(chave):
    r = requests.get(SUPABASE_URL + '/rest/v1/config?chave=eq.' + chave, headers=supa_headers(), timeout=10)
    data = r.json()
    return data[0]['valor'] if data else None

def gravar_config(chave, valor):
    if ler_config(chave) is None:
        requests.post(SUPABASE_URL + '/rest/v1/config', headers=supa_headers(), json={'chave': chave, 'valor': valor}, timeout=10).raise_for_status()
    else:
        requests.patch(SUPABASE_URL + '/rest/v1/config?chave=eq.' + chave, headers=supa_headers(), json={'valor': valor}, timeout=10).raise_for_status()

def ler_fechamentos():
    # Fechamento de cada mes ({mes: {total, recebido, atrasado}}), gravado na virada
    try:
        return json.loads(ler_config('faturamento_fechamentos') or '{}')
    except Exception:
        return {}

@app.route('/api/faturamento/fechamentos', methods=['GET'])
def get_fechamentos():
    try:
        return jsonify({'ok': True, 'data': ler_fechamentos()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Vendas de produtos (landing page, dashboard, agente de IA...) ──
# Venda com cliente_id soma no faturamento do cliente; sem cliente_id e avulsa (totais separados)
def buscar_vendas(filtro):
    r = requests.get(SUPABASE_URL + '/rest/v1/vendas?select=*,clientes(nome)&order=data.desc,id.desc&' + filtro, headers=supa_headers(), timeout=10)
    r.raise_for_status()
    vendas = r.json()
    for v in vendas:
        v['nome'] = (v.pop('clientes', None) or {}).get('nome') or v.get('cliente_nome') or ''
    return vendas

@app.route('/api/vendas', methods=['GET'])
def get_vendas():
    try:
        mes = request.args.get('mes') or ler_config('mes_atual')
        # Do mes + as que ficaram sem pagar em meses anteriores
        vendas = buscar_vendas('mes=eq.' + mes) + buscar_vendas('mes=lt.' + mes + '&pago=eq.false')
        return jsonify({'ok': True, 'data': vendas})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/vendas', methods=['POST'])
def add_venda():
    try:
        body = request.json or {}
        cliente_id = body.get('cliente_id') or None
        cliente_nome = (body.get('cliente_nome') or '').strip() or None
        produto = (body.get('produto') or '').strip()
        valor = float(body.get('valor') or 0)
        if not produto or valor <= 0 or not (cliente_id or cliente_nome):
            return jsonify({'ok': False, 'error': 'Informe produto, cliente e valor'}), 400
        payload = {'mes': ler_config('mes_atual'), 'produto': produto, 'valor': valor,
                   'descricao': (body.get('descricao') or '').strip() or None,
                   'cliente_id': int(cliente_id) if cliente_id else None,
                   'cliente_nome': None if cliente_id else cliente_nome,
                   'pago': bool(body.get('pago'))}
        if body.get('data'):
            payload['data'] = body['data']
        if payload['pago']:
            payload['pago_em'] = datetime.utcnow().isoformat()
        r = requests.post(SUPABASE_URL + '/rest/v1/vendas', headers=supa_headers(), json=payload, timeout=10)
        r.raise_for_status()
        return jsonify({'ok': True, 'data': r.json()[0]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/vendas/<int:id>', methods=['PATCH'])
def update_venda(id):
    try:
        body = request.json or {}
        dados = {}
        if 'pago' in body:
            dados['pago'] = bool(body['pago'])
            dados['pago_em'] = datetime.utcnow().isoformat() if body['pago'] else None
        if 'valor' in body:
            dados['valor'] = float(body['valor'])
        r = requests.patch(SUPABASE_URL + '/rest/v1/vendas?id=eq.' + str(id), headers=supa_headers(), json=dados, timeout=10)
        r.raise_for_status()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/vendas/<int:id>', methods=['DELETE'])
def delete_venda(id):
    try:
        requests.delete(SUPABASE_URL + '/rest/v1/vendas?id=eq.' + str(id), headers=supa_headers(), timeout=10).raise_for_status()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/faturamento/virar-mes', methods=['POST'])
def virar_mes():
    try:
        mes = ler_config('mes_atual')
        # Evita virar duas vezes (duplo clique ou duas abas abertas)
        if (request.json or {}).get('mes') != mes:
            return jsonify({'ok': False, 'error': 'O mes ja foi virado. Recarregue a pagina.'}), 409
        clientes = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true', headers=supa_headers(), timeout=10).json()
        pags = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=eq.' + mes, headers=supa_headers(), timeout=10).json()
        pagos = {p['cliente_id'] for p in pags if p.get('pago')}
        existentes = {p['cliente_id']: p['id'] for p in pags}
        total = recebido = atrasado = 0.0
        for c in clientes:
            valor = float(c.get('valor') or 0)
            total += valor
            if c['id'] in pagos:
                recebido += valor
                continue
            # Quem nao pagou fica atrasado; quem pagou continua marcado como pago
            atrasado += valor
            dados = {'pago': False, 'atrasado': True, 'updated_at': datetime.utcnow().isoformat()}
            if c['id'] in existentes:
                requests.patch(SUPABASE_URL + '/rest/v1/pagamentos?id=eq.' + str(existentes[c['id']]), headers=supa_headers(), json=dados, timeout=10).raise_for_status()
            else:
                requests.post(SUPABASE_URL + '/rest/v1/pagamentos', headers=supa_headers(), json={'mes': mes, 'cliente_id': c['id'], **dados}, timeout=10).raise_for_status()
        # Vendas de produtos do mes: as de clientes somam no faturamento, as avulsas ficam a parte
        vendas = buscar_vendas('mes=eq.' + mes)
        de_clientes = [v for v in vendas if v.get('cliente_id')]
        avulsas = [v for v in vendas if not v.get('cliente_id')]
        total += sum(float(v['valor']) for v in de_clientes)
        recebido += sum(float(v['valor']) for v in de_clientes if v['pago'])
        fechamentos = ler_fechamentos()
        fechamentos[mes] = {'total': round(total, 2), 'recebido': round(recebido, 2), 'atrasado': round(atrasado, 2),
                            'avulsas': {'total': round(sum(float(v['valor']) for v in avulsas), 2),
                                        'recebido': round(sum(float(v['valor']) for v in avulsas if v['pago']), 2)}}
        gravar_config('faturamento_fechamentos', json.dumps(fechamentos))
        ano, m = int(mes[:4]), int(mes[5:])
        novo_mes = str(ano + 1) + '-01' if m == 12 else str(ano) + '-' + str(m + 1).zfill(2)
        gravar_config('mes_atual', novo_mes)
        return jsonify({'ok': True, 'mes': novo_mes, 'fechamento': fechamentos[mes]})
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
        url = SUPABASE_URL + '/rest/v1/tarefas?concluida=eq.false&order=created_at.asc&select=*,clientes(nome,data_inicio)'
        if str(responsavel_id) != 'todos':
            url += '&responsavel_id=eq.' + str(responsavel_id)
        r = requests.get(url, headers=supa_headers())
        tarefas = []
        for t in r.json():
            c = t.pop('clientes', None) or {}
            tarefas.append({**t, 'cliente_nome': c.get('nome', ''), 'prioridade': bool(c) and eh_prioridade(c)})
        return jsonify({'ok': True, 'data': tarefas})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/tarefas', methods=['POST'])
def add_tarefa():
    try:
        u = current_user()
        body = request.json or {}
        responsavel_id = u['id'] if u['role'] == 'gestor' else (body.get('responsavel_id') or u['id'])
        payload = {'titulo': body.get('titulo'), 'prazo': body.get('prazo'), 'responsavel_id': responsavel_id}
        cliente_id = body.get('cliente_id')
        if cliente_id:
            cr = requests.get(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(int(cliente_id)) + '&select=gestor_id', headers=supa_headers(), timeout=10).json()
            # Gestor so vincula tarefa a cliente dele
            if cr and (u['role'] == 'admin' or cr[0].get('gestor_id') == u['id']):
                payload['cliente_id'] = int(cliente_id)
        r = requests.post(SUPABASE_URL + '/rest/v1/tarefas', headers=supa_headers(), json=payload)
        if responsavel_id != u['id']:
            corpo = payload['titulo'] or ''
            if payload.get('cliente_id'):
                cl = requests.get(SUPABASE_URL + '/rest/v1/clientes?id=eq.' + str(payload['cliente_id']) + '&select=nome', headers=supa_headers(), timeout=10).json()
                if cl:
                    corpo += ' · ' + cl[0]['nome']
            notificar([responsavel_id], '📋 Nova tarefa', corpo, '/tarefas')
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Financeiro do gestor (quanto cada gestor recebe no mes) ──
# Regras em config.remuneracao_gestores, por id do usuario:
#   fixo:              parcelas [{dia, valor}]           (Bruno: 500 dia 10 + 500 dia 20)
#   por_cliente_pago:  valor por cliente que pagou       (Kelmer: 100, recebe conforme o cliente paga)
#   por_cliente:       valor por cliente ativo, no dia X (Henrique: 100, todo dia 30)
def reais(v):
    return 'R$ ' + '{:,.0f}'.format(v).replace(',', '.')

def data_no_mes(mes, dia):
    ano, m = int(mes[:4]), int(mes[5:])
    proximo = datetime(ano + (m == 12), m % 12 + 1, 1)
    ultimo = (proximo - timedelta(days=1)).day
    return '%s-%02d' % (mes, min(int(dia), ultimo))

def data_br(iso):
    # timestamp do banco (UTC) -> data no horario de Brasilia
    try:
        return (datetime.strptime(iso[:19], '%Y-%m-%dT%H:%M:%S') - timedelta(hours=3)).strftime('%Y-%m-%d')
    except (TypeError, ValueError):
        return None

def calcular_repasses(gid, regra, mes, hoje):
    # Itens que o gestor tem a receber no mes, pela regra dele, ja marcando os que o admin pagou.
    # Usado na pagina Financeiro do gestor e nas despesas do Financeiro do admin.
    texto = ''
    itens = []
    # Antes do mes em que o gestor comecou nao ha nada a receber
    if regra.get('inicio') and mes < regra['inicio']:
        return texto, itens
    if regra['tipo'] == 'fixo':
        total = sum(p['valor'] for p in regra['parcelas'])
        texto = reais(total) + ' fixos por mês'
        for n, p in enumerate(regra['parcelas'], 1):
            itens.append({'chave': 'parcela-%d' % n, 'descricao': 'Parcela %d de %d' % (n, len(regra['parcelas'])), 'cliente': '',
                          'data': data_no_mes(mes, p['dia']), 'valor': p['valor'], 'status': 'previsto'})
    else:
        clientes = requests.get(SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true&gestor_id=eq.' + str(gid) +
                                '&select=id,nome,dia_pagamento&order=nome.asc', headers=supa_headers(), timeout=10).json()
        valor = regra['valor']
        if regra['tipo'] == 'por_cliente':
            texto = reais(valor) + ' por cliente, pago todo dia %d' % regra['dia']
            for c in clientes:
                itens.append({'chave': 'cliente-%d' % c['id'], 'descricao': 'Cliente ativo', 'cliente': c['nome'], 'data': data_no_mes(mes, regra['dia']),
                              'valor': valor, 'status': 'previsto'})
        else:
            texto = reais(valor) + ' por cliente, liberado quando o cliente paga'
            ano, m = int(mes[:4]), int(mes[5:])
            mes_ant = '%d-12' % (ano - 1) if m == 1 else '%d-%02d' % (ano, m - 1)
            nome_ant = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto',
                        'setembro', 'outubro', 'novembro', 'dezembro'][int(mes_ant[5:]) - 1]
            ids = ','.join(str(c['id']) for c in clientes) or '0'
            pags = requests.get(SUPABASE_URL + '/rest/v1/pagamentos?mes=in.(' + mes + ',' + mes_ant + ')&cliente_id=in.(' + ids + ')',
                                headers=supa_headers(), timeout=10).json()
            por_mes = {(p['mes'], p['cliente_id']): p for p in pags}
            for c in clientes:
                p = por_mes.get((mes, c['id']))
                venc = data_no_mes(mes, c['dia_pagamento']) if c.get('dia_pagamento') else None
                if p and p.get('pago'):
                    itens.append({'chave': 'cliente-%d' % c['id'], 'descricao': 'Mensalidade do mês', 'cliente': c['nome'], 'data': data_br(p.get('updated_at')),
                                  'valor': valor, 'status': 'liberado', 'vencimento': venc})
                else:
                    itens.append({'chave': 'cliente-%d' % c['id'], 'descricao': 'Mensalidade do mês', 'cliente': c['nome'], 'data': venc, 'valor': valor,
                                  'status': 'atrasado' if venc and venc < hoje else 'aguardando', 'vencimento': venc})
                # Mensalidade do mes anterior: em atraso, ou paga atrasada dentro deste mes
                pa = por_mes.get((mes_ant, c['id']))
                if pa and pa.get('atrasado') and not pa.get('pago'):
                    itens.append({'chave': 'cliente-%d-ant' % c['id'], 'descricao': 'Mensalidade de ' + nome_ant + ' (em atraso)', 'cliente': c['nome'], 'data': None,
                                  'valor': valor, 'status': 'atrasado', 'vencimento': None})
                elif pa and pa.get('pago') and (data_br(pa.get('updated_at')) or '')[:7] == mes:
                    # quitada so neste mes = paga com atraso, libera agora
                    itens.append({'chave': 'cliente-%d-ant' % c['id'], 'descricao': 'Mensalidade de ' + nome_ant + ' (paga com atraso)', 'cliente': c['nome'],
                                  'data': data_br(pa.get('updated_at')), 'valor': valor, 'status': 'liberado', 'vencimento': None})
    # Repasses que o admin ja marcou como pagos ao gestor
    pagos = requests.get(SUPABASE_URL + '/rest/v1/repasses_gestores?usuario_id=eq.' + str(gid) + '&mes=eq.' + mes,
                         headers=supa_headers(), timeout=10).json()
    pagos = {p['chave']: p for p in pagos} if isinstance(pagos, list) else {}
    for i in itens:
        if i['chave'] in pagos:
            i['pago'] = True
            i['pago_em'] = data_br((pagos[i['chave']].get('pago_em') or '').replace(' ', 'T'))
    return texto, itens

@app.route('/api/meu-financeiro', methods=['GET'])
def meu_financeiro():
    try:
        u = current_user()
        regras = json.loads(ler_config('remuneracao_gestores') or '{}')
        usuarios = requests.get(SUPABASE_URL + '/rest/v1/usuarios?ativo=eq.true&select=id,nome,role&order=id.asc', headers=supa_headers(), timeout=10).json()
        # Admin escolhe o gestor (para conferir); gestor so ve o proprio
        gid = u['id'] if u['role'] == 'gestor' else int(request.args.get('gestor_id') or 0)
        gestores = [{'id': x['id'], 'nome': x['nome']} for x in usuarios if str(x['id']) in regras]
        if u['role'] == 'admin' and not gid and gestores:
            gid = gestores[0]['id']
        gestor = next((x for x in usuarios if x['id'] == gid), None)
        mes = request.args.get('mes') or ler_config('mes_atual')
        hoje = (datetime.utcnow() - timedelta(hours=3)).strftime('%Y-%m-%d')
        resposta = {'ok': True, 'mes': mes, 'hoje': hoje, 'gestor': gestor and {'id': gestor['id'], 'nome': gestor['nome']},
                    'gestores': gestores if u['role'] == 'admin' else [], 'regra': None, 'itens': []}
        regra = regras.get(str(gid))
        if not gestor or not regra:
            return jsonify(resposta)

        resposta['regra'], resposta['itens'] = calcular_repasses(gid, regra, mes, hoje)
        return jsonify(resposta)

    except Exception as e:
        print('MEU FINANCEIRO ERROR:', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/repasses', methods=['POST'])
def marcar_repasses():
    # Admin marca (ou desmarca) itens do financeiro de um gestor como pagos
    try:
        body = request.json or {}
        gid, mes = int(body.get('gestor_id') or 0), body.get('mes') or ''
        itens = body.get('itens') or []
        if not gid or not re.match(r'^\d{4}-\d{2}$', mes) or not itens:
            return jsonify({'ok': False, 'error': 'Informe gestor, mes e itens'}), 400
        if body.get('pago', True):
            linhas = [{'usuario_id': gid, 'mes': mes, 'chave': str(i['chave'])[:60], 'valor': float(i.get('valor') or 0),
                       'pago_em': datetime.utcnow().isoformat()} for i in itens]
            h = {**supa_headers(), 'Prefer': 'resolution=merge-duplicates,return=representation'}
            requests.post(SUPABASE_URL + '/rest/v1/repasses_gestores?on_conflict=usuario_id,mes,chave', headers=h, json=linhas, timeout=10).raise_for_status()
        else:
            chaves = ','.join('"' + str(i['chave']).replace('"', '') + '"' for i in itens)
            requests.delete(SUPABASE_URL + '/rest/v1/repasses_gestores', headers=supa_headers(), timeout=10,
                            params={'usuario_id': 'eq.%d' % gid, 'mes': 'eq.' + mes, 'chave': 'in.(' + chaves + ')'}).raise_for_status()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/tarefas/clientes', methods=['GET'])
def tarefas_clientes():
    # Clientes que podem ser vinculados a uma tarefa: todos (admin) ou so os do gestor
    try:
        u = current_user()
        url = SUPABASE_URL + '/rest/v1/clientes?ativo=eq.true&select=id,nome,gestor_id,data_inicio&order=nome.asc'
        if u['role'] == 'gestor':
            url += '&gestor_id=eq.' + str(u['id'])
        clientes = requests.get(url, headers=supa_headers(), timeout=10).json()
        return jsonify({'ok': True, 'data': [{**c, 'prioridade': eh_prioridade(c)} for c in clientes]})
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
        r = requests.patch(SUPABASE_URL + '/rest/v1/tarefas?id=eq.' + str(id) + '&concluida=eq.false', headers=supa_headers(), json={'concluida': True, 'concluida_em': now})
        feitas = r.json() if r.ok else []
        if isinstance(feitas, list) and feitas:
            avancar_onboarding(feitas[0], current_user())
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

# ── Dashboards dos clientes (so admin) ──
# Clientes Prata e Ouro ganham um dashboard proprio (sites na Vercel). Link e senha
# ficam no cadastro do cliente (clientes.dashboard_url / dashboard_senha).
@app.route('/dashboards')
def dashboards_page():
    return send_from_directory('static', 'dashboards.html')

@app.route('/api/dashboards', methods=['GET'])
def listar_dashboards():
    try:
        clientes = requests.get(SUPABASE_URL + '/rest/v1/clientes', headers=supa_headers(), timeout=10, params={
            'select': 'id,nome,nivel,valor,status,ativo,gestor_id,dashboard_url,dashboard_senha',
            'or': '(nivel.in.(prata,ouro),dashboard_url.not.is.null)', 'order': 'nome.asc'}).json()
        nomes = {u['id']: u['nome'] for u in requests.get(SUPABASE_URL + '/rest/v1/usuarios?select=id,nome', headers=supa_headers(), timeout=10).json()}
        lista = []
        for c in clientes:
            # Inativo sem dashboard nao interessa; inativo com dashboard aparece (o site continua no ar)
            if (c.get('status') or ('ativo' if c.get('ativo') else 'inativo')) == 'inativo' and not c.get('dashboard_url'):
                continue
            c['gestor'] = nomes.get(c.get('gestor_id'))
            lista.append(c)
        return jsonify({'ok': True, 'clientes': lista})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clientes/<int:id>/dashboard', methods=['PATCH'])
def update_dashboard_cliente(id):
    body = request.json or {}
    campos = {}
    if 'url' in body:
        url = (body.get('url') or '').strip()
        if url and not url.startswith('http'):
            url = 'https://' + url
        campos['dashboard_url'] = url or None
    if 'senha' in body:
        campos['dashboard_senha'] = (body.get('senha') or '').strip() or None
    if not campos:
        return jsonify({'ok': False, 'error': 'Nada para atualizar'}), 400
    try:
        requests.patch(SUPABASE_URL + '/rest/v1/clientes?id=eq.%d' % id, headers=supa_headers(), json=campos, timeout=10).raise_for_status()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Em negociacao: possiveis clientes (so admin) ──
CAMPOS_NEGOCIACAO = ('nome', 'origem', 'telefone', 'cargo', 'valor_previsto', 'status', 'previsao_mes')
STATUS_NEGOCIACAO = ('especulacao', 'em_contato', 'reuniao_marcada', 'avaliando_proposta', 'quente', 'frio')  # 'fechado' so pela rota /fechar

def dados_negociacao(body):
    dados = {}
    for campo in CAMPOS_NEGOCIACAO:
        if campo not in body:
            continue
        v = body[campo]
        if isinstance(v, str):
            v = v.strip() or None
        if campo == 'valor_previsto' and v is not None:
            v = float(v)
        if campo == 'status' and v not in STATUS_NEGOCIACAO:
            raise ValueError('Status invalido')
        if campo == 'previsao_mes' and v is not None and not re.match(r'^\d{4}-\d{2}$', v):
            raise ValueError('Mes de previsao invalido')
        dados[campo] = v
    return dados

@app.route('/api/negociacoes', methods=['GET'])
def get_negociacoes():
    try:
        r = requests.get(SUPABASE_URL + '/rest/v1/negociacoes?order=atualizado_em.desc', headers=supa_headers(), timeout=10)
        r.raise_for_status()
        return jsonify({'ok': True, 'data': r.json()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/negociacoes', methods=['POST'])
def add_negociacao():
    try:
        dados = dados_negociacao(request.json or {})
        if not dados.get('nome'):
            return jsonify({'ok': False, 'error': 'Informe o nome'}), 400
        r = requests.post(SUPABASE_URL + '/rest/v1/negociacoes', headers=supa_headers(), json=dados, timeout=10)
        r.raise_for_status()
        return jsonify({'ok': True, 'data': r.json()[0]})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/negociacoes/<int:id>', methods=['PATCH'])
def update_negociacao(id):
    try:
        dados = dados_negociacao(request.json or {})
        if 'nome' in dados and not dados['nome']:
            return jsonify({'ok': False, 'error': 'Informe o nome'}), 400
        dados['atualizado_em'] = datetime.utcnow().isoformat()
        r = requests.patch(SUPABASE_URL + '/rest/v1/negociacoes?id=eq.' + str(id), headers=supa_headers(), json=dados, timeout=10)
        r.raise_for_status()
        if not r.json():
            return jsonify({'ok': False, 'error': 'Negociacao nao encontrada'}), 404
        return jsonify({'ok': True, 'data': r.json()[0]})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

OCUPACAO_POR_CARGO = {'corretor': 'corretor', 'gerente': 'gerente', 'imobiliaria': 'imobiliaria',
                      'superintendente': 'superintendente', 'diretor': 'diretor'}

@app.route('/api/negociacoes/<int:id>/fechar', methods=['POST'])
def fechar_negociacao(id):
    # Negociacao fechada vira cliente ativo (com o admin), e sai do quadro de negociacao
    try:
        n = requests.get(SUPABASE_URL + '/rest/v1/negociacoes?id=eq.' + str(id), headers=supa_headers(), timeout=10).json()
        if not n:
            return jsonify({'ok': False, 'error': 'Negociacao nao encontrada'}), 404
        n = n[0]
        if n.get('status') == 'fechado' and n.get('cliente_id'):
            return jsonify({'ok': False, 'error': 'Essa negociacao ja foi fechada'}), 409
        valor = float((request.json or {}).get('valor') or n.get('valor_previsto') or 0)
        if valor <= 0:
            return jsonify({'ok': False, 'error': 'Informe a mensalidade do cliente'}), 400
        cargo = unicodedata.normalize('NFKD', (n.get('cargo') or '').lower()).encode('ascii', 'ignore').decode().strip()
        hoje = (datetime.utcnow() - timedelta(hours=3)).strftime('%Y-%m-%d')
        gestor_id = int((request.json or {}).get('gestor_id') or 0) or current_user()['id']
        dia = (request.json or {}).get('dia_pagamento')
        dia = int(dia) if dia and 1 <= int(dia) <= 31 else None
        cliente = {'nome': n['nome'].strip().upper(), 'valor': valor,
                   'nivel': 'ouro' if valor >= 1500 else 'prata' if valor >= 1000 else 'bronze',
                   'telefone': n.get('telefone'), 'ocupacao': OCUPACAO_POR_CARGO.get(cargo, 'outro' if cargo else None),
                   'data_inicio': hoje, 'gestor_id': gestor_id, 'status': 'ativo', 'ativo': True, 'dia_pagamento': dia}
        r = requests.post(SUPABASE_URL + '/rest/v1/clientes', headers=supa_headers(), json=cliente, timeout=10)
        r.raise_for_status()
        novo = r.json()[0]
        agora = datetime.utcnow().isoformat()
        requests.patch(SUPABASE_URL + '/rest/v1/negociacoes?id=eq.' + str(id), headers=supa_headers(), timeout=10,
                       json={'status': 'fechado', 'cliente_id': novo['id'], 'fechado_em': agora, 'atualizado_em': agora,
                             'valor_previsto': valor}).raise_for_status()
        criar_etapa_onboarding(novo['id'], 1, current_user())
        if gestor_id != current_user()['id']:
            notificar([gestor_id], '🆕 Novo cliente para você', novo['nome'] + ' · 🔥 prioridade: cliente novo', '/painel')
        return jsonify({'ok': True, 'cliente': {'id': novo['id'], 'nome': novo['nome']}, 'gestor': _nome_usuario(gestor_id)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/negociacoes/<int:id>', methods=['DELETE'])
def delete_negociacao(id):
    try:
        requests.delete(SUPABASE_URL + '/rest/v1/negociacoes?id=eq.' + str(id), headers=supa_headers(), timeout=10).raise_for_status()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/negociacao')
def negociacao_page():
    return send_from_directory('static', 'negociacao.html')

# ── Notificacoes: inscricao do aparelho e alertas automaticos ──
@app.route('/api/push/chave', methods=['GET'])
def push_chave():
    chaves = chaves_push()
    if not chaves:
        return jsonify({'ok': False, 'error': 'Notificacoes indisponiveis'}), 503
    return jsonify({'ok': True, 'chave': chaves['vapid_publica']})

@app.route('/api/push/inscrever', methods=['POST'])
def push_inscrever():
    try:
        body = request.json or {}
        s = body.get('inscricao') or {}
        chaves = s.get('keys') or {}
        if not s.get('endpoint') or not chaves.get('p256dh') or not chaves.get('auth'):
            return jsonify({'ok': False, 'error': 'Inscricao invalida'}), 400
        linha = {'endpoint': s['endpoint'], 'usuario_id': current_user()['id'], 'p256dh': chaves['p256dh'],
                 'auth': chaves['auth'], 'aparelho': (body.get('aparelho') or '')[:290]}
        requests.post(SUPABASE_URL + '/rest/v1/push_inscricoes?on_conflict=endpoint', json=linha, timeout=10,
                      headers={**supa_headers(), 'Prefer': 'resolution=merge-duplicates,return=minimal'}).raise_for_status()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/push/cancelar', methods=['POST'])
def push_cancelar():
    endpoint = (request.json or {}).get('endpoint') or ''
    requests.delete(SUPABASE_URL + '/rest/v1/push_inscricoes', params={'endpoint': 'eq.' + endpoint, 'usuario_id': 'eq.%d' % current_user()['id']},
                    headers=supa_headers(), timeout=10)
    return jsonify({'ok': True})

@app.route('/api/push/teste', methods=['POST'])
def push_teste():
    u = current_user()
    notificar([u['id']], '🔔 Notificações ativadas', 'Pronto, ' + (u.get('nome') or '') + '! Você vai receber os avisos do painel aqui.', '/')
    return jsonify({'ok': True})

CPL_ALERTA = 20.0          # CPL do dia acima disso gera aviso
GASTO_MINIMO_ALERTA = 20.0  # so avalia contas que ja gastaram isso no dia

@app.route('/api/cron/alertas', methods=['GET', 'POST'])
def cron_alertas():
    # Chamado pelo agendamento do Supabase (pg_cron) a cada 30 min, com o segredo de push_chaves
    chaves = chaves_push()
    if not chaves or not secrets.compare_digest(request.headers.get('X-Segredo', ''), chaves['segredo_cron']):
        return jsonify({'ok': False, 'error': 'Nao autorizado'}), 401
    # Responde na hora e checa em segundo plano (a consulta ao Windsor pode passar de 30s)
    threading.Thread(target=checar_alertas, daemon=True).start()
    return jsonify({'ok': True, 'status': 'checando'})

def checar_alertas():
    checar_cpl()
    checar_sem_lead()

def _primeira_vez(chave):
    # Grava a chave em push_alertas_enviados; True so na primeira vez (evita aviso repetido)
    r = requests.post(SUPABASE_URL + '/rest/v1/push_alertas_enviados', json={'chave': chave}, timeout=10,
                      headers={**supa_headers(), 'Prefer': 'resolution=ignore-duplicates,return=representation'})
    return bool(r.ok and r.json())

def _inscritos_push():
    inscritos = requests.get(SUPABASE_URL + '/rest/v1/push_inscricoes?select=usuario_id', headers=supa_headers(), timeout=10).json()
    return {i['usuario_id'] for i in inscritos} if isinstance(inscritos, list) else set()

def _reais(v):
    return 'R$ ' + '{:,.2f}'.format(v).replace(',', 'X').replace('.', ',').replace('X', '.')

HORA_AVISO_SEM_LEAD = 8  # a partir das 8h avisa as contas que passaram o dia anterior inteiro sem lead

def checar_sem_lead():
    # Uma vez por dia, de manha: conta que gastou ontem e nao teve nenhum lead/conversa no dia inteiro
    try:
        agora = datetime.utcnow() - timedelta(hours=3)
        if agora.hour < HORA_AVISO_SEM_LEAD:
            return
        ontem = (agora - timedelta(days=1)).strftime('%Y-%m-%d')
        marca = 'semlead-rodou:' + ontem
        # Ja rodou hoje? Evita consultar o Windsor de novo a cada 30 min
        ja = requests.get(SUPABASE_URL + '/rest/v1/push_alertas_enviados', params={'chave': 'eq.' + marca, 'select': 'chave'},
                          headers=supa_headers(), timeout=10).json()
        if ja:
            return
        inscritos = _inscritos_push()
        contas = [d for d in com_gestor(fetch_ads_data(date_from=ontem, date_to=ontem))
                  if d['spend'] > 0 and not d['total'] and d.get('gestor_id') in inscritos]
        if not _primeira_vez(marca):
            return
        enviados = 0
        for d in contas:
            if not _primeira_vez('semlead:%s:%s' % (d.get('account_id') or d['account_name'], ontem)):
                continue
            notificar([d['gestor_id']], '🚫 Dia inteiro sem lead',
                      d['account_name'] + ': ontem gastou ' + _reais(d['spend']) + ' e não entrou nenhum lead nem conversa.', '/painel')
            enviados += 1
        print('CRON ALERTAS: %d aviso(s) de dia sem lead' % enviados)
    except Exception:
        print('CRON ALERTAS ERROR (sem lead):', traceback.format_exc())

def checar_cpl():
    try:
        hoje = (datetime.utcnow() - timedelta(hours=3)).strftime('%Y-%m-%d')
        contas = com_gestor(fetch_ads_data(date_from=hoje, date_to=hoje))
        # So avisa (e so marca como avisado) quem ja ativou as notificacoes em algum aparelho
        inscritos = _inscritos_push()
        enviados = 0
        for d in contas:
            if not d.get('gestor_id') or d['gestor_id'] not in inscritos or d['spend'] < GASTO_MINIMO_ALERTA:
                continue
            cpl = d['spend'] / d['total'] if d['total'] else None
            if cpl is not None and cpl <= CPL_ALERTA:
                continue
            # Um aviso por conta por dia
            if not _primeira_vez('cpl:%s:%s' % (d.get('account_id') or d['account_name'], hoje)):
                continue
            gasto = _reais(d['spend'])
            if cpl is None:
                corpo = d['account_name'] + ': ' + gasto + ' investidos hoje e nenhum resultado ainda.'
            else:
                corpo = d['account_name'] + ': CPL de hoje R$ ' + ('%.2f' % cpl).replace('.', ',') + ' (' + gasto + ', ' + str(d['total']) + ' resultados).'
            notificar([d['gestor_id']], '⚠️ CPL acima de R$ 20', corpo, '/painel')
            enviados += 1
        print('CRON ALERTAS: %d aviso(s) de CPL' % enviados)
    except Exception:
        print('CRON ALERTAS ERROR:', traceback.format_exc())

@app.route('/sw.js')
def service_worker():
    resp = send_from_directory('static', 'sw.js')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

@app.route('/manifest.webmanifest')
def manifesto():
    resp = send_from_directory('static', 'manifest.webmanifest')
    resp.headers['Content-Type'] = 'application/manifest+json'
    return resp

@app.route('/meu-financeiro')
def meu_financeiro_page():
    return send_from_directory('static', 'meu_financeiro.html')

@app.route('/painel')
def painel_gestor_page():
    if session.get('role') == 'admin':
        return redirect('/')
    return send_from_directory('static', 'painel_gestor.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
