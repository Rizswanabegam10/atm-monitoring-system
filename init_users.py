import sqlite3

conn = sqlite3.connect("atm.db")
cur = conn.cursor()

# Drop old users table if it exists
cur.execute("DROP TABLE IF EXISTS users")

# Create new users table with correct columns
cur.execute("""
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    account_no TEXT NOT NULL,
    card_id TEXT NOT NULL,
    mobile TEXT NOT NULL
);
""")

# Insert dummy users
cur.execute("INSERT INTO users (username, account_no, card_id, mobile) VALUES (?, ?, ?, ?)",
            ("rizswana", "1234567890", "CARD123", "9876543210"))
cur.execute("INSERT INTO users (username, account_no, card_id, mobile) VALUES (?, ?, ?, ?)",
            ("testuser", "9876543210", "CARD999", "9998887777"))

conn.commit()
conn.close()

print("✅ users table recreated with correct columns and dummy data")