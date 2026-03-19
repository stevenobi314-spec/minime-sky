import os
import time
import socket
import sqlite3
import hashlib
import pandas as pd
from datetime import datetime
from pathlib import Path
import streamlit as st
import threading

# -----------------------------
# CONFIG
# -----------------------------
st.set_page_config(page_title="MiniMeSky Ultimate Dashboard", layout="wide")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "minime.db"
QUEUE_FILE = DATA_DIR / "queue.txt"
LEDGER_FILE = DATA_DIR / "ledger.txt"
WORKER_LOG = LOG_DIR / "worker.log"

# -----------------------------
# DB CONNECTION
# -----------------------------
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)

# -----------------------------
# INIT TABLES
# -----------------------------
with get_connection() as conn:
    cursor = conn.cursor()

    cursor.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        amount REAL,
        party TEXT,
        status TEXT,
        upi_ref TEXT,
        logged_by TEXT
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        action TEXT,
        timestamp TEXT,
        location TEXT
    )""")

    conn.commit()

# -----------------------------
# UTIL
# -----------------------------
def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def get_location():
    try:
        return socket.gethostbyname(socket.gethostname())
    except:
        return "unknown"

def log_event(msg, file=LEDGER_FILE):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(file, "a", encoding="utf-8") as f:
        f.write(f"{ts} | {msg}\n")

def read_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def clear_queue():
    open(QUEUE_FILE, "w").close()

# -----------------------------
# DEFAULT USER
# -----------------------------
with get_connection() as conn:
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            ("AllFather", hash_password("MinimeNetwork"))
        )
        conn.commit()
    except:
        pass

# -----------------------------
# SESSION
# -----------------------------
if "user" not in st.session_state:
    st.session_state.user = None

# -----------------------------
# LOGIN
# -----------------------------
if not st.session_state.user:
    st.title("🔐 MiniMeSky Login")

    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login"):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT password FROM users WHERE username=?", (u,))
            data = cursor.fetchone()

        if data and data[0] == hash_password(p):
            st.session_state.user = u
            st.rerun()
        else:
            st.error("Invalid login")

    st.stop()

# =============================
# DASHBOARD
# =============================
st.title("🚀 MiniMeSky Ultimate Dashboard")
st.success(f"Logged in as: {st.session_state.user}")

# ===== METRICS =====
with get_connection() as conn:
    df = pd.read_sql("SELECT * FROM transactions", conn)

if not df.empty:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    total = df["amount"].sum()
    today = df[df["timestamp"].dt.date == datetime.now().date()]["amount"].sum()
    pending = df[df["status"] == "Pending"]["amount"].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("💰 Total", f"₹{total:,.0f}")
    c2.metric("📅 Today", f"₹{today:,.0f}")
    c3.metric("⏳ Pending", f"₹{pending:,.0f}")
else:
    st.info("No transactions yet")

# ===== MAIN AREA =====
left, right = st.columns([1, 2])

# ---- ADD PAYMENT ----
with left:
    st.subheader("💰 Add Payment")

    amount = st.number_input("Amount", min_value=0.0)
    party = st.text_input("Party")
    upi = st.text_input("UPI Ref")
    status = st.selectbox("Status", ["Confirmed", "Pending"])

    if st.button("Save Payment"):
        ts = datetime.now().isoformat()

        with get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "INSERT INTO transactions VALUES (NULL,?,?,?,?,?,?)",
                (ts, amount, party, status, upi, st.session_state.user)
            )

            cursor.execute(
                "INSERT INTO actions VALUES (NULL,?,?,?,?)",
                (st.session_state.user, f"{amount} → {party}", ts, get_location())
            )

            conn.commit()

        if amount > 10000:
            st.error("🚨 HIGH VALUE")

        st.success("Payment saved ✅")
        log_event(f"{st.session_state.user} added ₹{amount}")

        st.rerun()  # 🔥 THIS FIXES YOUR REFRESH

# ---- LEDGER ----
with right:
    st.subheader("📊 Ledger")

    search = st.text_input("Search")
    filter_status = st.selectbox("Filter", ["All", "Confirmed", "Pending"])

    with get_connection() as conn:
        df2 = pd.read_sql("SELECT * FROM transactions ORDER BY id DESC", conn)

    if search:
        df2 = df2[
            df2["party"].fillna("").str.contains(search, case=False) |
            df2["upi_ref"].fillna("").str.contains(search, case=False)
        ]

    if filter_status != "All":
        df2 = df2[df2["status"] == filter_status]

    st.dataframe(df2, use_container_width=True)

# ===== ADMIN =====
if st.session_state.user == "AllFather":
    st.subheader("👑 Admin")

    new_u = st.text_input("New Username")
    new_p = st.text_input("Password")

    if st.button("Add User"):
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    (new_u, hash_password(new_p))
                )
                conn.commit()
            st.success("User added ✅")
        except:
            st.error("User exists ❌")

    st.write("### Recent Actions")

    with get_connection() as conn:
        actions = pd.read_sql("SELECT * FROM actions ORDER BY id DESC LIMIT 10", conn)

    st.dataframe(actions, use_container_width=True)

# ===== LOGOUT =====
if st.button("Logout"):
    st.session_state.user = None
    st.rerun()

# ===== WORKER =====
def whatsapp_worker():
    log_event("Worker started", WORKER_LOG)

    while True:
        try:
            msgs = read_queue()

            for msg in msgs:
                ts = datetime.now().isoformat()

                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO actions VALUES (NULL,?,?,?,?)",
                        ("Worker", f"Sent: {msg}", ts, "server")
                    )
                    conn.commit()

                log_event(f"Processed: {msg}", WORKER_LOG)

            if msgs:
                clear_queue()

            time.sleep(10)

        except Exception as e:
            log_event(f"Worker error: {e}", WORKER_LOG)
            time.sleep(5)

if "worker" not in st.session_state:
    threading.Thread(target=whatsapp_worker, daemon=True).start()
    st.session_state.worker = True

st.subheader("🤖 WhatsApp Worker")
st.success("Running in background")