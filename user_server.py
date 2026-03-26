"""
=====================================================================
PROJECT TITLE : Smart ATM Monitoring System
MODULE        : User Side ATM Finder
TECHNOLOGY    : Python Flask, SQLite
=====================================================================
"""

# ========================== IMPORTS ================================
from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import datetime
import logging
import socket
import requests
import time

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
# APPLICATION CONFIG
# ==============================================================

app = Flask(__name__)
app.secret_key = "supersecretkey"
DATABASE = "atm.db"
LOG_FILE = "user_server.log"

# Bank Server URL - Get from environment or use default
BANK_SERVER_URL = f"http://{MACHINE_IP}:5000/api/high-amount-alert"
HIGH_AMOUNT_LIMIT = 50000  # ₹50,000 limit

# ============================================================== 
# LOGGING SETUP
# ==============================================================

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logging.info("User Server Started")

# ============================================================== 
# DATABASE UTILITIES
# ==============================================================

def get_db_connection():
    """Create and return a database connection"""
    try:
        conn = sqlite3.connect(DATABASE)
        return conn
    except Exception as e:
        logging.error(f"Database connection error: {e}")
        return None

# ============================================================== 
# INITIALIZE DATABASE
# ==============================================================

def init_db():
    """Create users table if not exists and insert dummy users"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        account_no TEXT NOT NULL,
        card_id TEXT NOT NULL,
        mobile TEXT NOT NULL
    );
    """)
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    if count == 0:
        cur.execute("INSERT INTO users (username, account_no, card_id, mobile) VALUES (?, ?, ?, ?)",
                    ("rizswana", "1234567890", "CARD123", "9876543210"))
        cur.execute("INSERT INTO users (username, account_no, card_id, mobile) VALUES (?, ?, ?, ?)",
                    ("testuser", "9876543210", "CARD999", "9998887777"))
        conn.commit()
        logging.info("Dummy users inserted into users table")
    conn.close()

# ============================================================== 
# INPUT VALIDATION
# ==============================================================

def validate_amount(amount):
    """Validate amount entered by user"""
    try:
        amount = int(amount)
        return amount > 0
    except:
        return False

def validate_location(location):
    """Validate location string"""
    return location is None or len(location.strip()) <= 50

# ============================================================== 
# SEARCH LOGIC
# ==============================================================

def search_atms(amount, location):
    """Search ATM database for matching ATMs"""
    conn = get_db_connection()
    if conn is None:
        return []

    cur = conn.cursor()

    query = "SELECT atm_id, location, cash FROM atm WHERE cash >= ?"
    params = [amount]

    if location and location.strip():
        query += " AND location LIKE ?"
        params.append(f"%{location}%")

    try:
        cur.execute(query, params)
        results = cur.fetchall()
        logging.info(f"Search: Amount={amount}, Location={location}, Results={len(results)}")
    except Exception as e:
        logging.error(f"Search error: {e}")
        results = []

    conn.close()
    return results

# ============================================================== 
# FUNCTION TO SEND HIGH AMOUNT ALERT TO BANK SERVER (FIXED)
# ==============================================================

def send_high_amount_alert(username, amount, location):
    """Send alert to bank server with retry mechanism"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT username, account_no, card_id, mobile FROM users WHERE username=?",
            (username,)
        )
        user_details = cur.fetchone()
        conn.close()
        
        if user_details:
            alert_data = {
                "user_name": user_details[0],
                "account_no": user_details[1],
                "card_id": user_details[2],
                "mobile": user_details[3],
                "amount_requested": amount,
                "location": location if location else "Not specified",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            print(f"📤 Sending high amount alert to bank server: {alert_data}")
            
            # Try 3 times with delay
            max_retries = 3
            retry_delay = 1  # seconds
            
            for attempt in range(max_retries):
                try:
                    response = requests.post(BANK_SERVER_URL, json=alert_data, timeout=10)
                    if response.status_code == 200:
                        logging.info(f"✅ High amount alert sent for {username} - Amount: ₹{amount}")
                        print(f"✅ Alert sent successfully on attempt {attempt + 1}")
                        return True
                    else:
                        logging.warning(f"⚠️ Attempt {attempt + 1} failed: Status {response.status_code}")
                        print(f"⚠️ Attempt {attempt + 1} failed: Status {response.status_code}")
                except requests.exceptions.Timeout:
                    logging.warning(f"⚠️ Attempt {attempt + 1} timed out")
                    print(f"⚠️ Attempt {attempt + 1} timed out")
                except requests.exceptions.ConnectionError:
                    logging.warning(f"⚠️ Attempt {attempt + 1} - Connection error (Bank server not ready?)")
                    print(f"⚠️ Attempt {attempt + 1} - Connection error")
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
            
            logging.error(f"❌ Failed to send high amount alert after {max_retries} attempts")
            return False
            
    except Exception as e:
        logging.error(f"Error sending high amount alert: {e}")
        return False

# ============================================================== 
# ROUTES
# ==============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    if request.method == "POST":
        username   = (request.form.get("username") or "").strip()
        account_no = (request.form.get("account_no") or "").strip()
        card_id    = (request.form.get("card_id") or "").strip()
        mobile     = (request.form.get("mobile") or "").strip()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE username=? AND account_no=? AND card_id=? AND mobile=?",
            (username, account_no, card_id, mobile)
        )
        user = cur.fetchone()
        conn.close()

        if user:
            session["user"] = username
            logging.info(f"User {username} logged in successfully")
            return redirect(url_for("user_dashboard"))
        else:
            message = "❌ Invalid username, account number, card ID, or mobile!"

    return render_template("userlogin.html", message=message)

@app.route("/logout")
def logout():
    session.pop("user", None)
    logging.info("User logged out")
    return redirect(url_for("login"))

@app.route("/", methods=["GET", "POST"])
def user_dashboard():
    """Main user dashboard route"""
    if "user" not in session:
        return redirect(url_for("login"))

    results = []
    message = ""
    high_amount_notified = False

    if request.method == "POST":
        amount = (request.form.get("amount") or "").strip()
        location = (request.form.get("location") or "").strip()

        if not amount or not validate_amount(amount):
            message = "❌ Please enter a valid amount!"
            logging.warning("Invalid amount input")
        elif not validate_location(location):
            message = "❌ Invalid location input!"
        else:
            amount = int(amount)
            
            # Check if amount exceeds limit
            if amount > HIGH_AMOUNT_LIMIT and not high_amount_notified:
                username = session["user"]
                print(f"🔔 High amount detected: ₹{amount} by {username}")
                
                alert_sent = send_high_amount_alert(username, amount, location)
                
                if alert_sent:
                    message = f"⚠️ High amount request (₹{amount}) - Bank has been notified! "
                    print("✅ Alert sent successfully")
                else:
                    message = f"⚠️ High amount request (₹{amount}) - Could not notify bank immediately. Alert will be sent in background. "
                    print("❌ Alert failed - check if Bank Server is running")
                    
                    # Try one more time in background (optional)
                    import threading
                    threading.Thread(target=send_high_amount_alert, args=(username, amount, location), daemon=True).start()
                
                high_amount_notified = True
            
            results = search_atms(amount, location)
            
            if len(results) == 0:
                if not message:
                    message = "❌ No ATMs found with the requested amount in this location."
                else:
                    message += "❌ No ATMs found with the requested amount in this location."
            else:
                if not message:
                    message = f"✓ Found {len(results)} ATM(s) with ₹{amount}+"
                else:
                    message += f"✓ Found {len(results)} ATM(s) with ₹{amount}+"

    return render_template("user_dashboard.html", result=results, message=message, user=session["user"])

@app.route("/health")
def health():
    """Health check endpoint"""
    return {
        "status": "User server running",
        "time": datetime.datetime.now().isoformat(),
        "ip": MACHINE_IP,
        "bank_server_url": BANK_SERVER_URL
    }

@app.errorhandler(404)
def not_found(error):
    logging.warning("404 error occurred")
    return "<h3>Page not found</h3>", 404

@app.errorhandler(500)
def server_error(error):
    logging.error("500 server error occurred")
    return "<h3>Internal server error</h3>", 500

# ============================================================== 
# SERVER START
# ==============================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("💳 ATM FINDER - USER SERVER")
    print("="*60)
    print(f"✓ Server IP: {MACHINE_IP}")
    print(f"✓ Access URL: http://{MACHINE_IP}:5001")
    print(f"✓ High Amount Limit: ₹{HIGH_AMOUNT_LIMIT}")
    print(f"✓ Bank Server URL: {BANK_SERVER_URL}")
    print("="*60 + "\n")

    logging.info(f"User Server Running on {MACHINE_IP}:5001")

    init_db()

    app.run(host=MACHINE_IP, port=5001, debug=True)

"""
=====================================================================
END OF USER SERVER PROGRAM
=====================================================================
"""