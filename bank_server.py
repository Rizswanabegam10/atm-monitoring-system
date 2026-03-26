"""
==============================================================
SMART ATM MONITORING SYSTEM - BANK SIDE SERVER (FIXED VERSION)
==============================================================
"""

from flask import Flask, render_template, request, redirect, session, send_file, jsonify
import sqlite3
import json
import csv
import threading
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt
import smtplib
from email.mime.text import MIMEText
import socket
import os
import random
from flask_cors import CORS

# ==============================================================
# GET MACHINE IP ADDRESS
# ==============================================================

def get_ip_address():
    """Get the local machine IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

MACHINE_IP = get_ip_address()

# ==============================================================
# APP CONFIG
# ==============================================================

app = Flask(__name__)
app.secret_key = "BANK_SECURE_SECRET_KEY"
CORS(app)
DATABASE = "atm.db"

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT   = 1883
MQTT_TOPIC  = "atm/data"

# ALERT THRESHOLDS
LOW_CASH_THRESHOLD = 200000
HIGH_TEMP_THRESHOLD = 35.0  # °C
LOW_TEMP_THRESHOLD = 10.0   # °C
MAINTENANCE_DAYS = 30  # Days between maintenance

# ==============================================================
# GLOBAL VARIABLES FOR LIVE DATA
# ==============================================================

live_atm_data = {
    "ATM001": {},
    "ATM002": {},
    "ATM003": {},
    "ATM004": {},
    "ATM005": {}
}

# Store high amount alerts from users
high_amount_alerts = []

# ==============================================================
# ATM LOCATION DATA & TEMPS
# ==============================================================

ATM_LOCATIONS = {
    "ATM001": "Main Branch",
    "ATM002": "Bus Stand",
    "ATM003": "Railway Station",
    "ATM004": "Shopping Mall",
    "ATM005": "Hospital Road"
}

# Base temperatures for each ATM location
ATM_BASE_TEMPS = {
    "ATM001": 25.5,
    "ATM002": 27.0,
    "ATM003": 26.5,
    "ATM004": 24.8,
    "ATM005": 28.2
}

# ==============================================================
# DATABASE INITIALIZATION
# ==============================================================

def init_database():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS atm (
        atm_id TEXT PRIMARY KEY,
        location TEXT,
        cash INTEGER,
        temperature REAL,
        vibration INTEGER,
        last_update TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS atm_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        atm_id TEXT,
        cash INTEGER,
        timestamp TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        atm_id TEXT,
        alert_type TEXT,
        message TEXT,
        severity TEXT,
        created_at TEXT,
        resolved INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS maintenance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        atm_id TEXT,
        maintenance_type TEXT,
        last_date TEXT,
        next_due TEXT,
        status TEXT,
        notes TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS high_amount_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT,
        account_no TEXT,
        card_id TEXT,
        mobile TEXT,
        amount_requested INTEGER,
        location TEXT,
        timestamp TEXT,
        status TEXT DEFAULT 'pending'
    )
    """)

    # Insert initial data if empty
    cur.execute("SELECT COUNT(*) FROM atm")
    if cur.fetchone()[0] == 0:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        initial_data = [
            ("ATM001", "Main Branch", 500000, 25.5, 0, current_time),
            ("ATM002", "Bus Stand", 420000, 27.0, 0, current_time),
            ("ATM003", "Railway Station", 350000, 26.5, 0, current_time),
            ("ATM004", "Shopping Mall", 550000, 24.8, 0, current_time),
            ("ATM005", "Hospital Road", 300000, 28.2, 0, current_time),
        ]
        cur.executemany("""
        INSERT INTO atm VALUES (?,?,?,?,?,?)
        """, initial_data)

    # Insert initial maintenance records
    cur.execute("SELECT COUNT(*) FROM maintenance")
    if cur.fetchone()[0] == 0:
        current_date = datetime.now().strftime("%Y-%m-%d")
        next_due = (datetime.now() + timedelta(days=MAINTENANCE_DAYS)).strftime("%Y-%m-%d")
        
        maintenance_data = [
            ("ATM001", "Regular Checkup", current_date, next_due, "Completed", ""),
            ("ATM002", "Regular Checkup", current_date, next_due, "Completed", ""),
            ("ATM003", "Regular Checkup", current_date, next_due, "Completed", ""),
            ("ATM004", "Regular Checkup", current_date, next_due, "Completed", ""),
            ("ATM005", "Regular Checkup", current_date, next_due, "Completed", ""),
        ]
        for atm_id, maint_type, last_date, next_date, status, notes in maintenance_data:
            cur.execute("""
            INSERT INTO maintenance (atm_id, maintenance_type, last_date, next_due, status, notes)
            VALUES (?,?,?,?,?,?)
            """, (atm_id, maint_type, last_date, next_date, status, notes))

    conn.commit()
    conn.close()

def populate_initial_history():
    """Populate history table with initial data if empty"""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM atm_history")
    count = cur.fetchone()[0]
    
    if count == 0:
        print("📊 Populating initial history data...")
        cur.execute("SELECT atm_id, cash FROM atm")
        atms = cur.fetchall()
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for atm_id, cash in atms:
            cur.execute("""
            INSERT INTO atm_history (atm_id, cash, timestamp)
            VALUES (?,?,?)
            """, (atm_id, cash, current_time))
            
            for days_ago in range(1, 8):
                past_time = (datetime.now() - timedelta(days=days_ago, hours=random.randint(0, 23))).strftime("%Y-%m-%d %H:%M:%S")
                variation = random.randint(-50000, 50000)
                past_cash = max(50000, cash + variation)
                
                cur.execute("""
                INSERT INTO atm_history (atm_id, cash, timestamp)
                VALUES (?,?,?)
                """, (atm_id, past_cash, past_time))
        
        conn.commit()
        print(f"✓ Initial history data populated")
    
    conn.close()

init_database()
populate_initial_history()

# ==============================================================
# EMAIL ALERT
# ==============================================================

def send_email_alert(subject, message):
    try:
        sender = "mohanapriyangap@gmail.com"
        password = "lelu lles ucdl ndjs"
        receiver = "rizswanabegam@gmail.com"

        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = receiver

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        print(f"✓ Alert sent: {subject}")

    except Exception as e:
        print(f"⚠ Email error: {e}")

# ==============================================================
# LOG ALERT TO DATABASE
# ==============================================================

def log_alert(atm_id, alert_type, message, severity="warning"):
    try:
        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cur.execute("""
        INSERT INTO alerts (atm_id, alert_type, message, severity, created_at)
        VALUES (?,?,?,?,?)
        """, (atm_id, alert_type, message, severity, current_time))
        
        conn.commit()
        conn.close()
        print(f"✓ Alert logged: {atm_id} - {alert_type}")
    except Exception as e:
        print(f"⚠ Error logging alert: {e}")

# ==============================================================
# CHECK MAINTENANCE DUE
# ==============================================================

def check_maintenance_due(atm_id):
    try:
        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()
        
        cur.execute("""
        SELECT next_due FROM maintenance WHERE atm_id=? ORDER BY id DESC LIMIT 1
        """, (atm_id,))
        
        row = cur.fetchone()
        conn.close()
        
        if row:
            next_due_date = datetime.strptime(row[0], "%Y-%m-%d")
            today = datetime.now()
            
            if today >= next_due_date:
                return True
        return False
    except:
        return False

# ==============================================================
# GENERATE REALISTIC TEMPERATURE VARIATION
# ==============================================================

def get_atm_temperature(atm_id, base_temp):
    variation = random.uniform(-1.5, 1.5)
    return round(base_temp + variation, 1)

# ==============================================================
# UPDATE LIVE DATA FROM DATABASE
# ==============================================================

def update_live_data():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM atm ORDER BY atm_id")
    rows = cur.fetchall()
    conn.close()

    for row in rows:
        atm_id = row[0]
        live_atm_data[atm_id] = {
            "atm_id": row[0],
            "location": row[1],
            "cash": row[2],
            "temperature": row[3],
            "vibration": row[4],
            "last_update": row[5],
            "maintenance_due": check_maintenance_due(atm_id)
        }

update_live_data()

# ==============================================================
# MQTT CALLBACKS
# ==============================================================

def on_connect(client, userdata, flags, rc):
    print("✓ MQTT Connected Successfully")
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        base_temp = float(data.get("temperature", 25.5))
        vibration = int(data.get("vibration", 0))
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()

        for atm_id in ["ATM001", "ATM002", "ATM003", "ATM004", "ATM005"]:
            atm_base_temp = ATM_BASE_TEMPS.get(atm_id, 25.5)
            if atm_id == "ATM001":
                atm_temp = get_atm_temperature(atm_id, base_temp)
            else:
                atm_temp = get_atm_temperature(atm_id, atm_base_temp)
            
            cur.execute("SELECT cash FROM atm WHERE atm_id=?", (atm_id,))
            result = cur.fetchone()
            if result:
                atm_cash = result[0]
                
                if atm_id == "ATM001":
                    cur.execute("""
                    UPDATE atm SET temperature=?, vibration=?, last_update=?
                    WHERE atm_id=?
                    """, (atm_temp, vibration, current_time, atm_id))
                else:
                    cur.execute("""
                    UPDATE atm SET temperature=?, last_update=?
                    WHERE atm_id=?
                    """, (atm_temp, current_time, atm_id))
                
                cur.execute("""
                INSERT INTO atm_history (atm_id, cash, timestamp)
                VALUES (?,?,?)
                """, (atm_id, atm_cash, current_time))

        conn.commit()
        
        cur.execute("SELECT cash, temperature FROM atm WHERE atm_id='ATM001'")
        atm001_cash, atm001_temp = cur.fetchone()
        conn.close()
        
        update_live_data()
        print(f"✓ MQTT Data Updated")

        if atm001_temp > HIGH_TEMP_THRESHOLD:
            alert_msg = f"High temperature detected: {atm001_temp}°C"
            log_alert("ATM001", "HIGH_TEMPERATURE", alert_msg, "critical")
            send_email_alert("🌡️ HIGH TEMPERATURE ALERT", alert_msg)

        if atm001_temp < LOW_TEMP_THRESHOLD:
            alert_msg = f"Low temperature detected: {atm001_temp}°C"
            log_alert("ATM001", "LOW_TEMPERATURE", alert_msg, "warning")
            send_email_alert("❄️ LOW TEMPERATURE ALERT", alert_msg)

        if atm001_cash < LOW_CASH_THRESHOLD:
            alert_msg = f"Cash below threshold: ₹{atm001_cash:,}"
            log_alert("ATM001", "LOW_CASH", alert_msg, "warning")
            send_email_alert("⚠ LOW CASH ALERT", alert_msg)

        if vibration == 1:
            alert_msg = "Abnormal vibration/tampering detected"
            log_alert("ATM001", "VIBRATION", alert_msg, "critical")
            send_email_alert("🚨 SECURITY ALERT", alert_msg)

        if check_maintenance_due("ATM001"):
            alert_msg = "Preventive maintenance is due"
            log_alert("ATM001", "MAINTENANCE_DUE", alert_msg, "warning")
            send_email_alert("🔧 MAINTENANCE DUE", alert_msg)

    except Exception as e:
        print(f"⚠ MQTT Error: {e}")

# ==============================================================
# MQTT THREAD START
# ==============================================================

try:
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
    threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()
    print("✓ MQTT Client Started")
except Exception as e:
    print(f"⚠ MQTT Connection Error: {e}")

# ==============================================================
# API ENDPOINTS
# ==============================================================

@app.route("/api/live-data", methods=["GET"])
def get_live_data():
    update_live_data()
    return jsonify(live_atm_data)

@app.route("/api/atm/<atm_id>", methods=["GET"])
def get_atm_live_data(atm_id):
    update_live_data()
    if atm_id in live_atm_data:
        return jsonify(live_atm_data[atm_id])
    return jsonify({"error": "ATM not found"}), 404

@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM alerts WHERE resolved=0 ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()

    alerts = []
    for row in rows:
        alerts.append({
            "id": row[0],
            "atm_id": row[1],
            "alert_type": row[2],
            "message": row[3],
            "severity": row[4],
            "created_at": row[5]
        })
    return jsonify(alerts)

@app.route("/api/history/<atm_id>", methods=["GET"])
def get_history(atm_id):
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    
    cur.execute("""
    SELECT cash, timestamp
    FROM atm_history
    WHERE atm_id=?
    ORDER BY timestamp DESC
    LIMIT 30
    """, (atm_id,))
    
    rows = cur.fetchall()
    conn.close()
    
    history = []
    for cash, timestamp in reversed(rows):
        history.append({
            "cash": cash,
            "timestamp": timestamp
        })
    
    return jsonify(history)

# ==============================================================
# HIGH AMOUNT ALERT API ENDPOINTS (FIXED)
# ==============================================================

@app.route("/api/high-amount-alert", methods=["POST"])
def high_amount_alert():
    try:
        data = request.get_json()
        print(f"📥 Received high amount alert: {data}")
        
        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()
        
        cur.execute("""
        INSERT INTO high_amount_alerts (user_name, account_no, card_id, mobile, amount_requested, location, timestamp, status)
        VALUES (?,?,?,?,?,?,?,?)
        """, (data.get("user_name"), data.get("account_no"), data.get("card_id"),
              data.get("mobile"), data.get("amount_requested"), data.get("location"),
              data.get("timestamp"), "pending"))
        
        alert_id = cur.lastrowid
        conn.commit()
        conn.close()
        
        alert_entry = {
            "id": alert_id,
            "user_name": data.get("user_name"),
            "account_no": data.get("account_no"),
            "card_id": data.get("card_id"),
            "mobile": data.get("mobile"),
            "amount_requested": data.get("amount_requested"),
            "location": data.get("location"),
            "timestamp": data.get("timestamp"),
            "status": "pending"
        }
        
        high_amount_alerts.insert(0, alert_entry)
        
        email_subject = f"⚠️ HIGH AMOUNT ALERT - ₹{data.get('amount_requested')}"
        email_body = f"""
        User: {data.get('user_name')}
        Account: {data.get('account_no')}
        Card ID: {data.get('card_id')}
        Amount: ₹{data.get('amount_requested')}
        Mobile: {data.get('mobile')}
        Location: {data.get('location')}
        Time: {data.get('timestamp')}
        """
        send_email_alert(email_subject, email_body)
        
        print(f"✓ High amount alert logged for {data.get('user_name')} with ID: {alert_id}")
        
        return jsonify({"status": "success", "id": alert_id}), 200
        
    except Exception as e:
        print(f"⚠ Error in high amount alert: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/high-amount-alerts", methods=["GET"])
def get_high_amount_alerts():
    """Get only PENDING alerts"""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM high_amount_alerts WHERE status='pending' ORDER BY timestamp DESC")
    rows = cur.fetchall()
    conn.close()
    
    alerts = []
    for row in rows:
        alerts.append({
            "id": row[0],
            "user_name": row[1],
            "account_no": row[2],
            "card_id": row[3],
            "mobile": row[4],
            "amount_requested": row[5],
            "location": row[6],
            "timestamp": row[7],
            "status": row[8]
        })
    
    print(f"📊 Returning {len(alerts)} pending alerts")
    return jsonify(alerts)


@app.route("/api/high-amount-alerts/resolve/<int:alert_id>", methods=["POST"])
def resolve_high_amount_alert(alert_id):
    print(f"🔧 Resolving alert ID: {alert_id}")
    
    for alert in high_amount_alerts:
        if alert["id"] == alert_id:
            alert["status"] = "reviewed"
            break
    
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("UPDATE high_amount_alerts SET status='reviewed' WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()
    
    print(f"✓ Alert {alert_id} resolved")
    return jsonify({"status": "success"})

# ==============================================================
# AUTHENTICATION
# ==============================================================

@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if username == "admin" and password == "bank123":
            session["logged_in"] = True
            return redirect("/")
        else:
            error = "Invalid credentials!"
    
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ==============================================================
# DASHBOARD
# ==============================================================

@app.route("/")
def dashboard():
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM atm ORDER BY atm_id")
    atms = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM alerts WHERE resolved=0")
    alert_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM maintenance WHERE next_due <= date('now')")
    maintenance_count = cur.fetchone()[0]
    
    conn.close()

    return render_template("bank_dashboard.html", atms=atms, alert_count=alert_count, maintenance_count=maintenance_count)

# ==============================================================
# ALERTS PAGE
# ==============================================================

@app.route("/alerts")
def alerts_page():
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 100")
    rows = cur.fetchall()
    conn.close()

    return render_template("alerts.html", alerts=rows)

@app.route("/alert/resolve/<int:alert_id>", methods=["POST"])
def resolve_alert(alert_id):
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("UPDATE alerts SET resolved=1 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()

    return redirect("/alerts")

# ==============================================================
# MAINTENANCE MANAGEMENT
# ==============================================================

@app.route("/maintenance")
def maintenance():
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM maintenance ORDER BY next_due ASC")
    rows = cur.fetchall()
    conn.close()

    return render_template("maintenance.html", maintenance_records=rows)

@app.route("/maintenance/update/<int:maint_id>", methods=["POST"])
def update_maintenance(maint_id):
    if not session.get("logged_in"):
        return redirect("/login")

    try:
        notes = request.form.get("notes", "")
        current_date = datetime.now().strftime("%Y-%m-%d")
        next_due = (datetime.now() + timedelta(days=MAINTENANCE_DAYS)).strftime("%Y-%m-%d")

        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()
        
        cur.execute("SELECT atm_id FROM maintenance WHERE id=?", (maint_id,))
        atm_id = cur.fetchone()[0]
        
        cur.execute("""
        UPDATE maintenance SET last_date=?, next_due=?, status=?, notes=?
        WHERE id=?
        """, (current_date, next_due, "Completed", notes, maint_id))
        conn.commit()
        conn.close()

        update_live_data()
        log_alert(atm_id, "MAINTENANCE_COMPLETED", f"Maintenance completed on {current_date}", "info")
        
        return redirect("/maintenance")
    except Exception as e:
        print(f"⚠ Error updating maintenance: {e}")
        return redirect("/maintenance")

# ==============================================================
# CASH MANAGEMENT
# ==============================================================

@app.route("/manage-cash", methods=["GET", "POST"])
def manage_cash():
    if not session.get("logged_in"):
        return redirect("/login")

    message = ""
    
    if request.method == "POST":
        try:
            conn = sqlite3.connect(DATABASE)
            cur = conn.cursor()
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for atm_id in ["ATM001", "ATM002", "ATM003", "ATM004", "ATM005"]:
                cash = request.form.get(f"cash_{atm_id}")
                
                if cash is not None and cash != "":
                    cash = int(cash)
                    cur.execute("""
                    UPDATE atm SET cash=?, last_update=?
                    WHERE atm_id=?
                    """, (cash, current_time, atm_id))
                    
                    cur.execute("""
                    INSERT INTO atm_history (atm_id, cash, timestamp)
                    VALUES (?,?,?)
                    """, (atm_id, cash, current_time))
                    
                    print(f"✓ Updated {atm_id} with cash: ₹{cash:,}")
                    
                    if cash < LOW_CASH_THRESHOLD:
                        log_alert(atm_id, "LOW_CASH", f"Cash below threshold: ₹{cash:,}", "warning")
                else:
                    cur.execute("SELECT cash FROM atm WHERE atm_id=?", (atm_id,))
                    current_cash = cur.fetchone()[0]
                    cur.execute("""
                    INSERT INTO atm_history (atm_id, cash, timestamp)
                    VALUES (?,?,?)
                    """, (atm_id, current_cash, current_time))

            conn.commit()
            conn.close()
            update_live_data()
            message = "✓ Cash amounts updated successfully!"
            
        except Exception as e:
            print("ERROR:", e)
            message = f"❌ Error updating cash: {str(e)}"

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM atm ORDER BY atm_id")
    atms = cur.fetchall()
    conn.close()

    return render_template("manage_cash.html", atms=atms, message=message)

# ==============================================================
# GRAPH ROUTE
# ==============================================================

@app.route("/graph/<atm_id>")
def graph(atm_id):
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute("""
    SELECT cash, timestamp
    FROM atm_history
    WHERE atm_id=?
    ORDER BY timestamp DESC
    LIMIT 30
    """, (atm_id,))

    rows = cur.fetchall()
    
    cur.execute("SELECT location, cash FROM atm WHERE atm_id=?", (atm_id,))
    atm_info = cur.fetchone()
    conn.close()

    data = list(reversed(rows))
    
    atm_data = {
        "location": atm_info[0] if atm_info else "Unknown",
        "current_cash": atm_info[1] if atm_info else 0
    }

    return render_template("graph.html", atm=atm_id, data=data, atm_data=atm_data)

# ==============================================================
# CSV EXPORT
# ==============================================================

@app.route("/download")
def download_csv():
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM atm")
    rows = cur.fetchall()
    conn.close()

    filename = "atm_report.csv"

    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ATM ID","Location","Cash","Temp","Vibration","Time"])
        writer.writerows(rows)

    return send_file(filename, as_attachment=True)

# ==============================================================
# JINJA TEMPLATE FILTERS
# ==============================================================

@app.template_filter('format_currency')
def format_currency(value):
    if not value:
        return "0"
    try:
        return f"{int(value):,}"
    except:
        return str(value)

# ==============================================================
# ERROR HANDLERS
# ==============================================================

@app.errorhandler(404)
def not_found(error):
    return "<h3>Page not found</h3>", 404

@app.errorhandler(500)
def server_error(error):
    return "<h3>Internal server error</h3>", 500

# ==============================================================
# RUN SERVER
# ==============================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🏦 BANK ATM MONITORING SYSTEM - BANK SERVER")
    print("="*60)
    print(f"✓ Server IP: {MACHINE_IP}")
    print(f"✓ Access URL: http://{MACHINE_IP}:5000")
    print(f"✓ Manage Cash: http://{MACHINE_IP}:5000/manage-cash")
    print(f"✓ Alerts: http://{MACHINE_IP}:5000/alerts")
    print(f"✓ Maintenance: http://{MACHINE_IP}:5000/maintenance")
    print(f"✓ Live Data API: http://{MACHINE_IP}:5000/api/live-data")
    print(f"✓ Login: admin / bank123")
    print("="*60)
    print("📊 HIGH AMOUNT ALERTS: Shows only pending requests")
    print("📊 When Resolve clicked, row disappears after 5 seconds")
    print("="*60 + "\n")
    
    app.run(host=MACHINE_IP, port=5000, debug=True)