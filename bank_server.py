"""
==============================================================
SMART ATM MONITORING SYSTEM - BANK SIDE SERVER
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

init_database()

# ==============================================================
# EMAIL ALERT
# ==============================================================

def send_email_alert(subject, message):
    try:
        sender = "mohanapriyangap@gmail.com"  # Set your Gmail
        password = "lelu lles ucdl ndjs"  # Set your App Password
        receiver = "rizswanabegam@gmail.com" # Set recipient

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
        print(f"⚠ Email alerts disabled (configure in bank_server.py)")

# ==============================================================
# LOG ALERT TO DATABASE
# ==============================================================

def log_alert(atm_id, alert_type, message, severity="warning"):
    """Log alert to database"""
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
    """Check if maintenance is due for ATM"""
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
    """Generate realistic temperature with small variations"""
    variation = random.uniform(-1.5, 1.5)
    return round(base_temp + variation, 1)

# ==============================================================
# UPDATE LIVE DATA FROM DATABASE
# ==============================================================

def update_live_data():
    """Read from database and update live_atm_data"""
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

# Initial update
update_live_data()

# ==============================================================
# MQTT CALLBACKS
# ==============================================================

def on_connect(client, userdata, flags, rc):
    print("✓ MQTT Connected Successfully")
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    """
    Only update ATM001 temperature & vibration from MQTT
    CASH AMOUNT STAYS STATIC - Only change via manage-cash
    """
    try:
        data = json.loads(msg.payload.decode())

        # Only get temperature & vibration from MQTT
        base_temp   = float(data.get("temperature", 25.5))
        vibration   = int(data.get("vibration", 0))

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()

        # -------- UPDATE ATM001 ONLY (TEMP & VIBRATION) --------
        atm001_temp = get_atm_temperature("ATM001", base_temp)
        
        cur.execute("""
        UPDATE atm SET temperature=?, vibration=?, last_update=?
        WHERE atm_id='ATM001'
        """, (atm001_temp, vibration, current_time))

        # Update temperature for all other ATMs (keep cash static)
        for atm_id in ["ATM002", "ATM003", "ATM004", "ATM005"]:
            atm_base_temp = ATM_BASE_TEMPS.get(atm_id, 25.5)
            atm_temp = get_atm_temperature(atm_id, atm_base_temp)
            
            cur.execute("""
            UPDATE atm SET temperature=?, last_update=?
            WHERE atm_id=?
            """, (atm_temp, current_time, atm_id))

        conn.commit()
        conn.close()

        # Update live data
        update_live_data()

        print(f"✓ MQTT Data Updated: ATM001 Temp={atm001_temp}°C, Vibration={vibration}")

        # -------- TEMPERATURE ALERTS --------
        if atm001_temp > HIGH_TEMP_THRESHOLD:
            alert_msg = f"High temperature detected: {atm001_temp}°C (Threshold: {HIGH_TEMP_THRESHOLD}°C)"
            log_alert("ATM001", "HIGH_TEMPERATURE", alert_msg, "critical")
            send_email_alert("🌡️ HIGH TEMPERATURE ALERT - ATM001",
                             f"{alert_msg}\nTime: {current_time}\nImmediate cooling/maintenance required!")

        if atm001_temp < LOW_TEMP_THRESHOLD:
            alert_msg = f"Low temperature detected: {atm001_temp}°C (Threshold: {LOW_TEMP_THRESHOLD}°C)"
            log_alert("ATM001", "LOW_TEMPERATURE", alert_msg, "warning")
            send_email_alert("❄️ LOW TEMPERATURE ALERT - ATM001",
                             f"{alert_msg}\nTime: {current_time}\nCheck heating system!")

        # -------- CASH ALERT --------
        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()
        cur.execute("SELECT cash FROM atm WHERE atm_id='ATM001'")
        atm001_cash = cur.fetchone()[0]
        conn.close()

        if atm001_cash < LOW_CASH_THRESHOLD:
            alert_msg = f"Cash below threshold: ₹{atm001_cash}"
            log_alert("ATM001", "LOW_CASH", alert_msg, "warning")
            send_email_alert("⚠ LOW CASH ALERT - ATM001",
                             f"{alert_msg}\nImmediate refill required!")

        # -------- VIBRATION/THEFT ALERT --------
        if vibration == 1:
            alert_msg = "Abnormal vibration/tampering detected"
            log_alert("ATM001", "VIBRATION", alert_msg, "critical")
            send_email_alert("🚨 SECURITY ALERT - ATM001",
                             f"{alert_msg}\nTime: {current_time}\nPlease investigate immediately!")

        # -------- MAINTENANCE DUE ALERT --------
        if check_maintenance_due("ATM001"):
            alert_msg = "Preventive maintenance is due"
            log_alert("ATM001", "MAINTENANCE_DUE", alert_msg, "warning")
            send_email_alert("🔧 MAINTENANCE DUE - ATM001",
                             f"{alert_msg}\nSchedule maintenance visit now!")

    except Exception as e:
        print(f"⚠ MQTT Data Processing Error: {e}")

# ==============================================================
# MQTT THREAD START
# ==============================================================

try:
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
    threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()
except Exception as e:
    print(f"⚠ MQTT Connection Error: {e}")

# ==============================================================
# API ENDPOINTS FOR LIVE DATA
# ==============================================================

@app.route("/api/live-data", methods=["GET"])
def get_live_data():
    """Get all ATM live data as JSON"""
    update_live_data()
    return jsonify(live_atm_data)

@app.route("/api/atm/<atm_id>", methods=["GET"])
def get_atm_live_data(atm_id):
    """Get specific ATM live data"""
    update_live_data()
    if atm_id in live_atm_data:
        return jsonify(live_atm_data[atm_id])
    return jsonify({"error": "ATM not found"}), 404

@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    """Get all unresolved alerts"""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM alerts WHERE resolved=0 ORDER BY created_at DESC
    """)
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
    
    # Get alert count
    cur.execute("SELECT COUNT(*) FROM alerts WHERE resolved=0")
    alert_count = cur.fetchone()[0]
    
    # Get maintenance due count
    cur.execute("SELECT COUNT(*) FROM maintenance WHERE next_due <= date('now')")
    maintenance_count = cur.fetchone()[0]
    
    conn.close()

    return render_template("bank_dashboard.html", atms=atms, alert_count=alert_count, maintenance_count=maintenance_count)

# ==============================================================
# ALERTS PAGE
# ==============================================================

@app.route("/alerts")
def alerts_page():
    """View all alerts"""
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM alerts ORDER BY created_at DESC LIMIT 100
    """)
    rows = cur.fetchall()
    conn.close()

    return render_template("alerts.html", alerts=rows)

@app.route("/alert/resolve/<int:alert_id>", methods=["POST"])
def resolve_alert(alert_id):
    """Mark alert as resolved"""
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("""
    UPDATE alerts SET resolved=1 WHERE id=?
    """, (alert_id,))
    conn.commit()
    conn.close()

    return redirect("/alerts")

# ==============================================================
# MAINTENANCE MANAGEMENT
# ==============================================================

@app.route("/maintenance")
def maintenance():
    """View maintenance schedule"""
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM maintenance ORDER BY next_due ASC
    """)
    rows = cur.fetchall()
    conn.close()

    return render_template("maintenance.html", maintenance_records=rows)

@app.route("/maintenance/update/<int:maint_id>", methods=["POST"])
def update_maintenance(maint_id):
    """Update maintenance record"""
    if not session.get("logged_in"):
        return redirect("/login")

    try:
        notes = request.form.get("notes", "")
        current_date = datetime.now().strftime("%Y-%m-%d")
        next_due = (datetime.now() + timedelta(days=MAINTENANCE_DAYS)).strftime("%Y-%m-%d")

        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()
        cur.execute("""
        UPDATE maintenance SET last_date=?, next_due=?, status=?, notes=?
        WHERE id=?
        """, (current_date, next_due, "Completed", notes, maint_id))
        conn.commit()
        conn.close()

        update_live_data()
        return redirect("/maintenance")
    except Exception as e:
        print(f"⚠ Error updating maintenance: {e}")
        return redirect("/maintenance")

# ==============================================================
# CASH MANAGEMENT - UPDATE ATM CASH MANUALLY
# ==============================================================

@app.route("/manage-cash", methods=["GET", "POST"])
def manage_cash():
    """Manually update ATM cash amounts"""
    if not session.get("logged_in"):
        return redirect("/login")

    message = ""
    
    if request.method == "POST":
        try:
            conn = sqlite3.connect(DATABASE)
            cur = conn.cursor()
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Update each ATM cash amount
            for atm_id in ["ATM001", "ATM002", "ATM003", "ATM004", "ATM005"]:
                cash = request.form.get(f"cash_{atm_id}", "")
                
                if cash:
                    cash = int(cash)
                    cur.execute("""
                    UPDATE atm SET cash=?, last_update=?
                    WHERE atm_id=?
                    """, (cash, current_time, atm_id))
                    
                    cur.execute("""
                    INSERT INTO atm_history VALUES (?,?,?)
                    """, (atm_id, cash, current_time))

            conn.commit()
            conn.close()
            
            update_live_data()
            message = "✓ Cash amounts updated successfully!"
            print(f"✓ Admin updated cash amounts at {current_time}")
            
        except Exception as e:
            message = f"❌ Error updating cash: {str(e)}"

    # Get current ATM data
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
    LIMIT 10
    """, (atm_id,))

    rows = cur.fetchall()
    conn.close()

    data = list(reversed(rows))

    return render_template("graph.html", atm=atm_id, data=data)

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
    print("📊 ATM CASH: STATIC (Manual Update Only)")
    print("🌡️  TEMPERATURE: LIVE from MQTT (Alert > 35°C or < 10°C)")
    print("⚡ VIBRATION: LIVE from MQTT (Security Alert)")
    print("🔧 MAINTENANCE: Preventive (Every 30 days)")
    print("="*60 + "\n")
    
    app.run(host=MACHINE_IP, port=5000, debug=True)
