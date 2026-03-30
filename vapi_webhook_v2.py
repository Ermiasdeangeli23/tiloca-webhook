#!/usr/bin/env python3
"""
TILOCA - Vapi Webhook Server v2
Processa le chiamate di Sara, salva structured outputs,
filtra lead caldi, logga appuntamenti.
Deploy: Railway.app
"""

from flask import Flask, request, jsonify
import csv
import os
import json
from datetime import datetime

app = Flask(__name__)

# File paths
CALLS_LOG = 'tutte_chiamate.csv'
LEADS_CALDI = 'lead_caldi.csv'
CALLBACKS = 'da_richiamare.csv'

# CSV field names
CALL_FIELDS = [
    'data', 'ora', 'telefono', 'durata_sec', 'esito',
    'ha_capannone', 'tetto_libero', 'interessato',
    'nome_referente', 'callback_time', 'note', 'call_id'
]

LEAD_FIELDS = [
    'data', 'ora', 'telefono', 'nome_referente',
    'note', 'call_id'
]

CALLBACK_FIELDS = [
    'data', 'ora', 'telefono', 'callback_time',
    'note', 'call_id'
]


def append_csv(filepath, row_dict, fieldnames):
    """Append a row to CSV, create file + header if needed."""
    file_exists = os.path.exists(filepath)
    with open(filepath, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        # Only write fields that exist in fieldnames
        filtered = {k: v for k, v in row_dict.items() if k in fieldnames}
        writer.writerow(filtered)


def extract_structured_outputs(analysis):
    """Extract structured outputs from Vapi analysis object."""
    result = {
        'esito': 'SCONOSCIUTO',
        'ha_capannone': '',
        'tetto_libero': '',
        'interessato': '',
        'nome_referente': '',
        'callback_time': '',
        'note': ''
    }

    if not analysis:
        return result

    # Structured outputs can be in different places
    structured = analysis.get('structuredData', {})
    if not structured:
        structured = analysis.get('structured_data', {})

    if structured:
        result['esito'] = structured.get('esito', 'SCONOSCIUTO')
        result['ha_capannone'] = str(structured.get('ha_capannon', ''))
        result['tetto_libero'] = str(structured.get('tetto_libero', ''))
        result['interessato'] = str(structured.get('interessato', ''))
        result['callback_time'] = structured.get('callback_time', '')
        result['note'] = structured.get('note', '')

    # Try to get summary as fallback for notes
    if not result['note']:
        result['note'] = analysis.get('summary', '')

    return result


def extract_phone(data):
    """Extract phone number from call data."""
    # Try customer number first
    customer = data.get('customer', {})
    if customer and customer.get('number'):
        return customer['number']
    # Try call object
    call = data.get('call', {})
    if call and call.get('customer', {}).get('number'):
        return call['customer']['number']
    return 'sconosciuto'


def extract_duration(data):
    """Extract call duration in seconds."""
    # Try direct duration
    if 'duration' in data:
        return round(data['duration'], 1)
    # Try calculating from timestamps
    call = data.get('call', {})
    started = call.get('startedAt', '')
    ended = call.get('endedAt', '')
    if started and ended:
        try:
            start_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(ended.replace('Z', '+00:00'))
            return round((end_dt - start_dt).total_seconds(), 1)
        except (ValueError, TypeError):
            pass
    return 0


# ============================================================
# ROUTES
# ============================================================

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'TILOCA Webhook v2 attivo',
        'endpoints': {
            '/webhook': 'POST - riceve dati da Vapi',
            '/stats': 'GET - statistiche chiamate',
            '/leads': 'GET - lista lead caldi',
            '/callbacks': 'GET - lista da richiamare',
            '/tutte': 'GET - tutte le chiamate'
        }
    })


@app.route('/webhook', methods=['POST'])
def webhook():
    """Riceve end-of-call report da Vapi."""
    try:
        data = request.json or {}

        # Vapi sends different message types
        msg_type = data.get('message', {}).get('type', '')

        # We only care about end-of-call-report
        if msg_type == 'end-of-call-report':
            message = data.get('message', data)
        elif 'analysis' in data:
            # Direct format
            message = data
        else:
            # Acknowledge other message types silently
            return jsonify({'status': 'ok', 'processed': False}), 200

        now = datetime.now()
        phone = extract_phone(message)
        duration = extract_duration(message)
        analysis = message.get('analysis', {})
        outputs = extract_structured_outputs(analysis)
        call_id = message.get('call', {}).get('id', '')

        # Build row
        row = {
            'data': now.strftime('%Y-%m-%d'),
            'ora': now.strftime('%H:%M'),
            'telefono': phone,
            'durata_sec': duration,
            'call_id': call_id,
            **outputs
        }

        # 1. Log ALL calls
        append_csv(CALLS_LOG, row, CALL_FIELDS)

        # 2. If LEAD_CALDO → save to leads file
        if outputs['esito'] == 'LEAD_CALDO':
            lead_row = {
                'data': row['data'],
                'ora': row['ora'],
                'telefono': phone,
                'nome_referente': outputs['nome_referente'],
                'note': outputs['note'],
                'call_id': call_id
            }
            append_csv(LEADS_CALDI, lead_row, LEAD_FIELDS)
            print(f"🔥 LEAD CALDO: {phone}")

        # 3. If RICHIAMARE → save to callbacks file
        if outputs['esito'] == 'RICHIAMARE':
            cb_row = {
                'data': row['data'],
                'ora': row['ora'],
                'telefono': phone,
                'callback_time': outputs['callback_time'],
                'note': outputs['note'],
                'call_id': call_id
            }
            append_csv(CALLBACKS, cb_row, CALLBACK_FIELDS)
            print(f"📞 DA RICHIAMARE: {phone} → {outputs['callback_time']}")

        print(f"✅ Chiamata salvata: {phone} | Esito: {outputs['esito']} | Durata: {duration}s")
        return jsonify({'status': 'ok', 'esito': outputs['esito']}), 200

    except Exception as e:
        print(f"❌ Errore webhook: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 200


@app.route('/stats', methods=['GET'])
def stats():
    """Statistiche in tempo reale."""
    if not os.path.exists(CALLS_LOG):
        return jsonify({
            'totale_chiamate': 0,
            'lead_caldi': 0,
            'da_richiamare': 0,
            'non_interessati': 0,
            'messaggio': 'Nessuna chiamata ancora registrata'
        })

    totale = 0
    caldi = 0
    richiamare = 0
    non_interessati = 0
    non_raggiunti = 0
    durata_totale = 0

    with open(CALLS_LOG, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            totale += 1
            esito = row.get('esito', '')
            if esito == 'LEAD_CALDO':
                caldi += 1
            elif esito == 'RICHIAMARE':
                richiamare += 1
            elif esito == 'NON_INTERESSATO':
                non_interessati += 1
            elif esito == 'NON_RAGGIUNTO':
                non_raggiunti += 1
            try:
                durata_totale += float(row.get('durata_sec', 0))
            except (ValueError, TypeError):
                pass

    tasso = round((caldi / totale * 100), 1) if totale > 0 else 0
    durata_media = round(durata_totale / totale, 1) if totale > 0 else 0
    costo_stimato = round(durata_totale / 60 * 0.12, 2)

    return jsonify({
        'totale_chiamate': totale,
        'lead_caldi': caldi,
        'da_richiamare': richiamare,
        'non_interessati': non_interessati,
        'non_raggiunti': non_raggiunti,
        'tasso_conversione': f'{tasso}%',
        'durata_media_sec': durata_media,
        'costo_stimato_usd': costo_stimato
    })


@app.route('/leads', methods=['GET'])
def leads():
    """Lista di tutti i lead caldi."""
    if not os.path.exists(LEADS_CALDI):
        return jsonify({'leads': [], 'totale': 0})

    leads_list = []
    with open(LEADS_CALDI, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads_list.append(row)

    return jsonify({'leads': leads_list, 'totale': len(leads_list)})


@app.route('/callbacks', methods=['GET'])
def callbacks():
    """Lista di chi ha chiesto di essere richiamato."""
    if not os.path.exists(CALLBACKS):
        return jsonify({'callbacks': [], 'totale': 0})

    cb_list = []
    with open(CALLBACKS, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cb_list.append(row)

    return jsonify({'callbacks': cb_list, 'totale': len(cb_list)})


@app.route('/tutte', methods=['GET'])
def tutte():
    """Tutte le chiamate."""
    if not os.path.exists(CALLS_LOG):
        return jsonify({'chiamate': [], 'totale': 0})

    all_calls = []
    with open(CALLS_LOG, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_calls.append(row)

    return jsonify({'chiamate': all_calls, 'totale': len(all_calls)})


# ============================================================
# RUN
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
