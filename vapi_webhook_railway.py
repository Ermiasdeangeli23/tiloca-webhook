"""
TILOCA — Vapi Webhook Handler
Deploy su Railway.app (gratuito) — gira sempre anche con il PC spento.

Setup:
1. Crea account su railway.app
2. New Project → Deploy from GitHub (o drag & drop questa cartella)
3. Railway ti dà un URL tipo https://tiloca-webhook.up.railway.app
4. Vai in Vapi → Assistant Sara → Advanced → Server URL → incolla l'URL + /webhook
"""

import os
import csv
import json
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# File CSV locale (su Railway persiste finché non fai redeploy)
LEADS_FILE = "lead_caldi.csv"
LOG_FILE = "tutte_chiamate.csv"

def init_files():
    if not os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "Data", "Ora", "Telefono", "Nome_Azienda",
                "Ha_Capannone", "Tetto_Libero", "Interessato",
                "Esito", "Durata_sec", "Summary"
            ])
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "Data", "Ora", "Telefono", "Durata_sec", "Esito", "Call_ID"
            ])

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "TILOCA Webhook attivo", "version": "1.0"})

@app.route("/webhook", methods=["POST"])
def webhook():
    """Riceve tutti gli eventi da Vapi."""
    
    payload = request.json or {}
    message = payload.get("message", {})
    msg_type = message.get("type", "")
    
    # Ignora tutto tranne end-of-call
    if msg_type != "end-of-call-report":
        return jsonify({"status": "ok"}), 200
    
    # Estrai dati chiamata
    call = message.get("call", {})
    analysis = message.get("analysis", {})
    artifact = message.get("artifact", {})
    
    call_id = call.get("id", "")
    telefono = call.get("customer", {}).get("number", "N/D")
    durata = call.get("endedAt", "")
    
    # Summary della chiamata
    summary = analysis.get("summary", "").lower()
    
    # Determina esito dal summary
    if any(x in summary for x in ["consulente", "ricontatterà", "24 ore", "interessato"]):
        esito = "LEAD_CALDO"
    elif any(x in summary for x in ["non interessato", "no grazie", "non disponibile"]):
        esito = "NON_INTERESSATO"
    else:
        esito = "NON_RAGGIUNTO"
    
    # Structured data (se configurato in Vapi Analysis)
    structured = analysis.get("structuredData", {})
    ha_capannone = structured.get("ha_capannone", "")
    tetto_libero = structured.get("tetto_libero", "")
    interessato = structured.get("interessato_valutazione", "")
    
    ora_now = datetime.now()
    data_str = ora_now.strftime("%Y-%m-%d")
    ora_str = ora_now.strftime("%H:%M:%S")
    
    # Log sempre tutte le chiamate
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            data_str, ora_str, telefono, durata, esito, call_id
        ])
    
    # Salva solo lead caldi
    if esito == "LEAD_CALDO":
        with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                data_str, ora_str, telefono, "",
                ha_capannone, tetto_libero, interessato,
                esito, durata, summary[:200]
            ])
        print(f"🔥 LEAD CALDO: {telefono} — {data_str} {ora_str}")
    else:
        print(f"📞 Chiamata: {telefono} → {esito}")
    
    return jsonify({"status": "ok", "esito": esito}), 200

@app.route("/leads", methods=["GET"])
def mostra_leads():
    """Mostra tutti i lead caldi in JSON."""
    leads = []
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            leads = list(reader)
    except:
        pass
    return jsonify({"totale": len(leads), "leads": leads})

@app.route("/stats", methods=["GET"])
def stats():
    """Statistiche rapide."""
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            righe = list(csv.DictReader(f))
        
        totali = len(righe)
        caldi = sum(1 for r in righe if r.get("Esito") == "LEAD_CALDO")
        
        return jsonify({
            "totali": totali,
            "lead_caldi": caldi,
            "non_interessati": sum(1 for r in righe if r.get("Esito") == "NON_INTERESSATO"),
            "non_raggiunti": sum(1 for r in righe if r.get("Esito") == "NON_RAGGIUNTO"),
            "conversione_%": round(caldi/totali*100, 1) if totali > 0 else 0
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    init_files()
    port = int(os.environ.get("PORT", 5000))
    print(f"🛰️ TILOCA Webhook su porta {port}")
    app.run(host="0.0.0.0", port=port)
