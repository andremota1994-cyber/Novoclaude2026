import os
import requests
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)

WINDSOR_API_KEY = os.environ.get('WINDSOR_API_KEY', 'ab2a32d495a3d6c5f46565bd9ea6e0e3b6f9')
WINDSOR_BASE = 'https://connectors.windsor.ai/facebook'
FIELDS = 'account_name,spend,actions_lead,actions_onsite_conversion_messaging_conversation_started_7d'

PRESETS = {
    '30': 'last_30dT',
    '15': 'last_15dT',
    '7':  'last_7dT',
}

def fetch_data(preset):
    params = {
        'api_key': WINDSOR_API_KEY,
        'date_preset': preset,
        'fields': FIELDS,
    }
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

@app.route('/api/data')
def api_data():
    from flask import request
    period = request.args.get('period', '30')
    preset = PRESETS.get(period, 'last_30dT')
    try:
        data = fetch_data(preset)
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

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
