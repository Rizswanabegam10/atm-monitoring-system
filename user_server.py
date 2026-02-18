"""
=====================================================================
PROJECT TITLE : Smart ATM Monitoring System
MODULE        : User Side ATM Finder
TECHNOLOGY    : Python Flask, SQLite
=====================================================================
"""

# ========================== IMPORTS ================================
from flask import Flask, render_template, request
import sqlite3
import datetime
import os
import logging
import sys
import socket

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
DATABASE = "atm.db"
LOG_FILE = "user_server.log"

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
# ROUTES
# ==============================================================

@app.route("/", methods=["GET", "POST"])
def user_dashboard():
    """Main user dashboard route"""
    results = []
    message = ""

    if request.method == "POST":
        amount = request.form.get("amount", "").strip()
        location = request.form.get("location", "").strip()

        if not amount or not validate_amount(amount):
            message = "❌ Please enter a valid amount!"
            logging.warning("Invalid amount input")
        elif not validate_location(location):
            message = "❌ Invalid location input!"
        else:
            amount = int(amount)
            results = search_atms(amount, location)

            if len(results) == 0:
                message = "❌ No ATMs found with the requested amount in this location."
            else:
                message = f"✓ Found {len(results)} ATM(s) with ₹{amount}+"

    return render_template("user_dashboard.html", result=results, message=message)

# ==============================================================
# HEALTH CHECK
# ==============================================================

@app.route("/health")
def health():
    """Health check endpoint"""
    return {
        "status": "User server running",
        "time": datetime.datetime.now().isoformat(),
        "ip": MACHINE_IP
    }

# ==============================================================
# ERROR HANDLERS
# ==============================================================

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
    print("="*60 + "\n")
    
    logging.info(f"User Server Running on {MACHINE_IP}:5001")
    app.run(host=MACHINE_IP, port=5001, debug=True)

"""
=====================================================================
END OF USER SERVER PROGRAM
=====================================================================
"""
