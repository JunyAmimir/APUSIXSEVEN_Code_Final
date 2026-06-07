from flask import Flask, json, request, redirect, render_template, send_from_directory, jsonify, session, url_for, send_file
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import qrcode
import io
import csv
import os
import re
import google.generativeai as genai
import tempfile
import shutil
import vouchr_db

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

app = Flask(__name__, template_folder="templates", static_folder="assets")
app.config.update(
    SECRET_KEY=os.getenv("VOUCHR_MAIN_SECRET_KEY", "vouchr_main_dev_secret_key"),
    SESSION_COOKIE_NAME="vouchr_main_session",
)

# ====================== GEMINI AI ======================
def refresh_ai_environment():
    """Reload local AI settings so key changes work without editing application code."""
    load_dotenv(BASE_DIR / ".env", override=True)

def get_gemini_api_key():
    refresh_ai_environment()
    return (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
        or os.getenv("GOOGLE_AI_API_KEY", "").strip()
    )

def get_openai_api_key():
    refresh_ai_environment()
    return os.getenv("OPENAI_API_KEY", "").strip()

GEMINI_API_KEY = get_gemini_api_key()
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ====================== CSV PATHS ======================
CSV_DIR = BASE_DIR / "CSV"
CSV_DIR.mkdir(exist_ok=True)
User_File = CSV_DIR / "users.csv"
Merchant_File = CSV_DIR / "merchants.csv"
NOTIFICATIONS_CSV = CSV_DIR / "notifications.csv"
BUDGET_CSV = CSV_DIR / "budget.csv"
BUDGET_SETTINGS_CSV = CSV_DIR / "budget_settings.csv"
FEEDBACK_CSV = CSV_DIR / "feedback.csv"
CSV_FIELDS = ["id", "role", "name", "email", "password","address","created_at"]
FEEDBACK_FIELDS = ["id", "user_name", "message", "category", "created_at"]
EMAIL_REGEX = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR = BASE_DIR / "templates"
vouchr_db.init_db()

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ====================== VALIDATION ======================
def is_valid_email(email):
    return re.match(EMAIL_REGEX, email) is not None

def ensure_base_csv_exists():
    if not User_File.exists():
        with User_File.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            writer.writeheader()

    if not Merchant_File.exists():
        with Merchant_File.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            writer.writeheader()

def get_merchant_csv_path(merchant_name):
    return CSV_DIR / f"{merchant_name}.csv"

def read_users():
    ensure_base_csv_exists()
    with User_File.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))

def save_user(name, email, password):
    users = read_users()
    next_id = str(len(users) + 1)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with User_File.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writerow({
            "id": next_id,
            "role": "user",
            "name": name,
            "email": email.lower().strip(),
            "password": password,
            "created_at": created_at,
        })
    vouchr_db.upsert_user(name, email, password, "customer", next_id, created_at)

def read_merchants():
    ensure_base_csv_exists()
    with Merchant_File.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))

def save_merchant(name, email, password,address):
    merchants = read_merchants()
    next_id = str(len(merchants) + 1)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with Merchant_File.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writerow({
            "id": next_id,
            "role": "merchant",
            "name": name,
            "email": email.lower().strip(),
            "password": password,
            "address": address,
            "created_at": created_at,
        })
    vouchr_db.upsert_merchant(name, email, password, address, next_id, created_at)

def auth_message(message):
    return redirect("/auth.html?message=" + quote(message))

@app.route("/")
def index():
    return send_from_directory(TEMPLATE_DIR, "index.html")

@app.route("/auth.html")
def auth():
    return send_from_directory(TEMPLATE_DIR, "auth.html")

@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(BASE_DIR / "assets", filename)

@app.route('/CSV/<filename>')
def serve_csv(filename):
    return send_from_directory(CSV_DIR, filename)

#========================== NOTIFICATION HELPERS ============================
def ensure_notifications_csv():
    if not NOTIFICATIONS_CSV.exists():
        with NOTIFICATIONS_CSV.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["id","type","icon","title","message","voucher_id","merchant_id","budget_percent","is_read","created_at"])
            writer.writeheader()
            now = datetime.now().isoformat(timespec="seconds")
            writer.writerow({"id": "seed_new_voucher_mcdonalds", "type": "merchant", "icon": "🎟", "title": "New voucher nearby", "message": "McDonald's 15% OFF is available 1.2 km away.", "voucher_id": "mcdonalds", "merchant_id": "mcdonalds", "budget_percent": "", "is_read": "false", "created_at": now})
            writer.writerow({"id": "seed_popular_pastamania", "type": "merchant", "icon": "🔥", "title": "Popular deal", "message": "Pastamania 20% OFF is getting more views today.", "voucher_id": "pastamania", "merchant_id": "pastamania", "budget_percent": "", "is_read": "false", "created_at": now})

def read_notifications():
    ensure_notifications_csv()
    with NOTIFICATIONS_CSV.open("r", newline="", encoding="utf-8") as file:
        notifications = list(csv.DictReader(file))
    notifications.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    for item in notifications:
        item["is_read"] = str(item.get("is_read", "")).lower() == "true"
        if not item.get("icon"):
            item["icon"] = get_notification_icon(item.get("type"))
    return notifications

def write_notifications(notifications):
    ensure_notifications_csv()
    with NOTIFICATIONS_CSV.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["id","type","icon","title","message","voucher_id","merchant_id","budget_percent","is_read","created_at"])
        writer.writeheader()
        for item in notifications:
            writer.writerow({
                "id": item.get("id", ""),
                "type": item.get("type", "general"),
                "icon": item.get("icon", get_notification_icon(item.get("type"))),
                "title": item.get("title", "Notification"),
                "message": item.get("message", ""),
                "voucher_id": item.get("voucher_id", item.get("voucherId", "")),
                "merchant_id": item.get("merchant_id", item.get("merchantId", "")),
                "budget_percent": item.get("budget_percent", item.get("budgetPercent", "")),
                "is_read": "true" if item.get("is_read") or item.get("isRead") else "false",
                "created_at": item.get("created_at", item.get("createdAt", datetime.now().isoformat(timespec="seconds")))
            })

def get_notification_icon(notification_type):
    icons = {"merchant": "🎟", "voucher": "🎟", "budget": "💰", "warning": "⚠️", "savings": "💸", "expiry": "⏰", "popular": "🔥", "general": "🔔"}
    return icons.get(notification_type, "🔔")

def create_notification(data):
    ensure_notifications_csv()
    notifications = read_notifications()
    notification_id = data.get("id") or f"notif_{int(datetime.now().timestamp() * 1000)}"
    for item in notifications:
        if item.get("id") == notification_id:
            return item
    notification = {
        "id": notification_id,
        "type": data.get("type", "general"),
        "icon": data.get("icon") or get_notification_icon(data.get("type", "general")),
        "title": data.get("title", "Notification"),
        "message": data.get("message", ""),
        "voucher_id": data.get("voucher_id", data.get("voucherId", "")),
        "merchant_id": data.get("merchant_id", data.get("merchantId", "")),
        "budget_percent": data.get("budget_percent", data.get("budgetPercent", "")),
        "is_read": False,
        "created_at": data.get("created_at", data.get("createdAt", datetime.now().isoformat(timespec="seconds")))
    }
    notifications.insert(0, notification)
    write_notifications(notifications[:50])
    return notification

# ====================== AUTH ======================
@app.route("/signup", methods=["POST"])
def signup():
    role = request.form.get("role", "user").strip().lower()
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    address = request.form.get("address", "").strip()

    if role not in ["user", "merchant"]:
        return auth_message("Please choose User or Merchant.")

    if not name or not email or not password or not confirm_password:
        return auth_message("Please fill in every sign-up field.")
    
    if not is_valid_email(email):
        return auth_message("Please enter a valid email address.")

    if password != confirm_password:
        return auth_message("Passwords do not match.")

    if role == "merchant":
        accounts = read_merchants()
    else:
        accounts = read_users()

    for account in accounts:
        if account["email"].lower().strip() == email:
            return auth_message("This email is already registered. Please login.")

    if role == "merchant":
        if not address:
            return auth_message("Please provide a proper address for your store.")
        save_merchant(name, email, password,address)

        uploaded_file = request.files.get('store_image')
        if uploaded_file and uploaded_file.filename != '':
            safe_merchant_name = name.replace(' ', '_')
            unique_filename = f"{safe_merchant_name}.jpg" 
            file_path = ASSETS_DIR / unique_filename
            uploaded_file.save(file_path)
        # ---------------------------------
            
    else:
        save_user(name, email, password)

    return auth_message("Account created successfully. You can now login.")
@app.route("/login", methods=["POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role", "user").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if role == "merchant":
            accounts = read_merchants()
        if role == "user":
            accounts = read_users()

        for account in accounts:
            correct_email = account["email"].lower().strip() == email
            correct_password = account["password"] == password

            if correct_email and correct_password:
                vouchr_db.touch_login(account["email"])
                if role == "merchant":
                    session["merchant_name"] = account["name"] 
                    session["role"] = "merchant" 
                    return redirect("/merchant-main-menu")
                if role == "user":
                    session["user_name"] = account["name"]
                    session["user_email"] = account["email"]
                    session["role"] = "user" 
                    return redirect("/main-menu")
    return render_template("auth.html", message="Login failed. Please check your role, email, and password.")

# ====================== USER PAGES ======================

@app.route("/main-menu")
@app.route("/main_menu")
@app.route("/main-menu.html")
def main_menu():
    if session.get("role") != "user":
        return redirect("/auth.html")
    
    vouchers = get_all_vouchers() 
    current_user_name = session.get("user_name", "User")
    
    return render_template("main_menu.html", user_name=current_user_name,vouchers=vouchers)

def slugify(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "voucher"

def format_voucher_date(raw_date):
    raw_date = str(raw_date or "").strip()
    if not raw_date or raw_date.lower() in ["none", "no expiry", "no-expiry"]:
        return "No expiry"
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw_date, fmt).strftime("%d %b %Y")
        except ValueError:
            pass
    return raw_date

def extract_offer_text(title):
    title = str(title or "Special Offer").strip()
    percent_match = re.search(r"\b\d+\s*%\s*(?:off)?", title, re.IGNORECASE)
    if percent_match:
        return percent_match.group(0).upper().replace(" ", "") if "%" in percent_match.group(0) else percent_match.group(0)
    rm_match = re.search(r"RM\s*\d+(?:\.\d{1,2})?", title, re.IGNORECASE)
    if rm_match:
        return rm_match.group(0).upper()
    return "Special Deal"

def build_voucher_object(row, merchant_name):
    title = str(row.get("VoucherTitle") or row.get("title") or "Special Offer").strip()
    merchant_name = str(merchant_name or row.get("MerchantName") or "Merchant").strip()
    address = str(row.get("Address") or "Selected outlets").strip()
    image_url = str(row.get("ImageUrl") or "").strip() or "/assets/default-logo.png"
    expiry_raw = str(row.get("ExpiryDate") or "").strip()
    voucher_id = f"{slugify(merchant_name)}-{slugify(title)}"

    return {
        "id": voucher_id,
        "merchant_id": slugify(merchant_name),
        "merchant_name": merchant_name,
        "name": merchant_name,
        "VoucherTitle": title,
        "offer": extract_offer_text(title),
        "description": f"Redeem this exclusive voucher from {merchant_name}: {title}.",
        "category": "Merchant Deal",
        "location": address,
        "Address": address,
        "valid": format_voucher_date(expiry_raw),
        "ExpiryDate": expiry_raw,
        "logo": image_url,
        "ImageUrl": image_url,
        "Status": str(row.get("Status") or "Active").strip(),
        "Redeemed": str(row.get("Redeemed") or "0"),
        "Total": str(row.get("Total") or "")
    }

def get_all_vouchers():
    all_vouchers = []
    for merchant in read_merchants():
        merchant_name = str(merchant.get("name") or "").strip()
        if merchant_name:
            all_vouchers.extend(get_specific_merchant_vouchers(merchant_name))

    all_vouchers.sort(key=lambda item: (item.get("merchant_name", ""), item.get("VoucherTitle", "")))
    return all_vouchers

@app.route("/ai-coach")
@app.route("/ai_money_coach.html")
def ai_money_coach():
    return render_template("ai_money_coach.html")
# ---------------------------
# Notification API
# ---------------------------

@app.route("/api/notifications", methods=["GET"])
def api_get_notifications():
    notifications = read_notifications()
    unread_count = sum(1 for item in notifications if not item.get("is_read"))

    return jsonify({
        "notifications": notifications,
        "unread_count": unread_count
    })


@app.route("/api/notifications", methods=["POST"])
def api_add_notification():
    data = request.get_json(silent=True) or {}
    notification = create_notification(data)

    return jsonify({
        "success": True,
        "notification": notification
    })


@app.route("/api/notifications/mark-read", methods=["POST"])
def api_mark_notifications_read():
    notifications = read_notifications()

    for item in notifications:
        item["is_read"] = True

    write_notifications(notifications)
    user_id, audience_role = current_announcement_identity()
    if user_id:
        vouchr_db.mark_all_active_announcements_read(user_id, audience_role)

    return jsonify({
        "success": True,
        "unread_count": 0
    })


@app.route("/api/notifications/<notification_id>/mark-read", methods=["POST"])
def api_mark_one_notification_read(notification_id):
    notifications = read_notifications()

    for item in notifications:
        if item.get("id") == notification_id:
            item["is_read"] = True

    write_notifications(notifications)

    return jsonify({
        "success": True
    })

@app.route("/api/notifications/<notification_id>/delete", methods=["DELETE", "POST"])
def api_delete_notification(notification_id):
    notifications = read_notifications()
    original_count = len(notifications)

    notifications = [
        item for item in notifications
        if item.get("id") != notification_id
    ]

    write_notifications(notifications)

    unread_count = sum(1 for item in notifications if not item.get("is_read"))

    return jsonify({
        "success": True,
        "deleted": len(notifications) < original_count,
        "unread_count": unread_count
    })


@app.route("/api/notifications/merchant", methods=["POST"])
def api_add_merchant_notification():
    data = request.get_json(silent=True) or {}

    voucher_id = data.get("voucher_id", data.get("voucherId", ""))
    merchant_id = data.get("merchant_id", data.get("merchantId", voucher_id))
    merchant_name = data.get("merchant_name", data.get("merchantName", "A merchant"))
    offer = data.get("offer", "a new voucher")

    notification = create_notification({
        "id": data.get("id") or f"merchant_{voucher_id}_{int(datetime.now().timestamp())}",
        "type": "merchant",
        "icon": data.get("icon", "🎟"),
        "title": data.get("title", "New voucher available"),
        "message": data.get("message", f"{merchant_name} added {offer}."),
        "voucher_id": voucher_id,
        "merchant_id": merchant_id
    })

    return jsonify({
        "success": True,
        "notification": notification
    })


@app.route("/api/notifications/budget-check", methods=["POST"])
def api_budget_check():
    data = request.get_json(silent=True) or {}

    monthly_budget = float(data.get("monthly_budget", data.get("monthlyBudget", 0)) or 0)
    spent_amount = float(data.get("spent_amount", data.get("spentAmount", 0)) or 0)

    if monthly_budget <= 0:
        return jsonify({
            "success": False,
            "message": "monthly_budget must be greater than 0"
        }), 400

    percent = round((spent_amount / monthly_budget) * 100)
    created = []

    rules = [
        {
            "key": "25",
            "threshold": 25,
            "type": "budget",
            "icon": "💰",
            "title": "25% budget used",
            "message": f"You have used 25% of your monthly budget. RM{spent_amount:.2f} / RM{monthly_budget:.2f} spent."
        },
        {
            "key": "50",
            "threshold": 50,
            "type": "budget",
            "icon": "💰",
            "title": "50% budget used",
            "message": f"You have used 50% of your monthly budget. RM{spent_amount:.2f} / RM{monthly_budget:.2f} spent."
        },
        {
            "key": "75",
            "threshold": 75,
            "type": "warning",
            "icon": "⚠️",
            "title": "75% budget used",
            "message": f"You have used 75% of your monthly budget. RM{spent_amount:.2f} / RM{monthly_budget:.2f} spent. Spend carefully."
        },
        {
            "key": "100",
            "threshold": 100,
            "type": "warning",
            "icon": "🚫",
            "title": "Budget limit reached",
            "message": f"You have reached or exceeded your monthly budget. RM{spent_amount:.2f} / RM{monthly_budget:.2f} spent."
        }
    ]

    month_key = datetime.now().strftime("%Y-%m")

    existing_ids = {item.get("id") for item in read_notifications()}

    for rule in rules:
        notification_id = f"budget_{rule['key']}_{month_key}"

        if percent >= rule["threshold"] and notification_id not in existing_ids:
            notification = create_notification({
                "id": notification_id,
                "type": rule["type"],
                "icon": rule["icon"],
                "title": rule["title"],
                "message": rule["message"],
                "budget_percent": percent
            })
            created.append(notification)

    return jsonify({
        "success": True,
        "budget_percent": percent,
        "created": created
    })
def get_specific_merchant_vouchers(merchant_name):
    vouchers = []
    merchant_csv = get_merchant_csv_path(merchant_name)

    if not merchant_csv.exists():
        return vouchers

    with merchant_csv.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            status = str(row.get("Status") or "").strip().lower()
            dismissed = str(row.get("Dismissed") or "False").strip().lower() == "true"

            if status == "active" and not dismissed:
                vouchers.append(build_voucher_object(row, merchant_name))

    return vouchers

@app.route("/api/all-vouchers")
def api_all_vouchers():
    return jsonify(get_all_vouchers())

@app.route("/voucher")
@app.route("/voucher.html")
def voucher():
    if session.get("role") != "user":
        return redirect("/auth.html")
    vouchers = get_all_vouchers()
    return render_template("voucher.html", vouchers=vouchers)

@app.route("/voucher-detail/<voucher_id>")
def voucher_detail(voucher_id):

    return render_template("voucher_detail.html")

@app.route("/map")
@app.route("/map.html")
def map_page():
    return render_template("map.html")

@app.route("/budget")
@app.route("/budget.html")
def budget_page():
    if session.get("role") != "user":
        return redirect("/auth.html")
    return render_template("budget.html")

# Budget CSV Database ApI
def ensure_budget_settings_csv():
    if not os.path.exists(BUDGET_SETTINGS_CSV):
        with open(BUDGET_SETTINGS_CSV, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["key", "value"])
            writer.writeheader()
            writer.writerow({
                "key": "monthly_budget",
                "value": "500"
            })

def get_monthly_budget():
    ensure_budget_settings_csv()

    with open(BUDGET_SETTINGS_CSV, "r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    for row in rows:
        if row.get("key") == "monthly_budget":
            try:
                return float(row.get("value", 500))
            except ValueError:
                return 500.0

    return 500.0

def set_monthly_budget(amount):
    ensure_budget_settings_csv()
    amount = float(amount)

    rows = []
    found = False

    with open(BUDGET_SETTINGS_CSV, "r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    for row in rows:
        if row.get("key") == "monthly_budget":
            row["value"] = str(amount)
            found = True

    if not found:
        rows.append({
            "key": "monthly_budget",
            "value": str(amount)
        })

    with open(BUDGET_SETTINGS_CSV, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerows(rows)

    return amount

def ensure_budget_csv():
    if not BUDGET_CSV.exists():
        with BUDGET_CSV.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=[
                "id",
                "date",
                "merchant",
                "category",
                "amount",
                "saved",
                "voucher_id"
            ])
            writer.writeheader()

def read_budget_expenses():
    ensure_budget_csv()

    with open(BUDGET_CSV, "r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    for row in rows:
        try:
            row["amount"] = float(row.get("amount", 0) or 0)
        except ValueError:
            row["amount"] = 0.0

        try:
            row["saved"] = float(row.get("saved", 0) or 0)
        except ValueError:
            row["saved"] = 0.0

    rows.sort(key=lambda item: item.get("date", ""), reverse=True)
    return rows

def write_budget_expenses(rows):
    with open(BUDGET_CSV, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "id",
            "date",
            "merchant",
            "category",
            "amount",
            "saved",
            "voucher_id"
        ])
        writer.writeheader()

        for row in rows:
            writer.writerow({
                "id": row.get("id", ""),
                "date": row.get("date", ""),
                "merchant": row.get("merchant", ""),
                "category": row.get("category", "food"),
                "amount": f"{float(row.get('amount', 0) or 0):.2f}",
                "saved": f"{float(row.get('saved', 0) or 0):.2f}",
                "voucher_id": row.get("voucher_id", row.get("voucherId", ""))
            })

def make_budget_summary():
    expenses = read_budget_expenses()
    monthly_budget = get_monthly_budget()

    total_spent = sum(float(item.get("amount", 0) or 0) for item in expenses)
    total_saved = sum(float(item.get("saved", 0) or 0) for item in expenses)
    remaining = max(monthly_budget - total_spent, 0)
    usage_percent = round((total_spent / monthly_budget) * 100, 1) if monthly_budget else 0

    category_names = {
        "food": "Food",
        "cafe": "Café",
        "drinks": "Drinks",
        "desserts": "Desserts"
    }

    category_icons = {
        "food": "🍔",
        "cafe": "☕",
        "drinks": "🥤",
        "desserts": "🍰"
    }

    categories = []

    for key in ["food", "cafe", "drinks", "desserts"]:
        amount = sum(float(item.get("amount", 0) or 0) for item in expenses if item.get("category") == key)
        percent = round((amount / total_spent) * 100, 1) if total_spent else 0

        categories.append({
            "key": key,
            "name": category_names[key],
            "icon": category_icons[key],
            "amount": round(amount, 2),
            "percent": percent
        })

    return {
        "monthly_budget": round(monthly_budget, 2),
        "spent": round(total_spent, 2),
        "saved": round(total_saved, 2),
        "remaining": round(remaining, 2),
        "usage_percent": usage_percent,
        "categories": categories,
        "recent": expenses[:6]
    }

def create_budget_threshold_notifications(monthly_budget, spent_amount):
    if monthly_budget <= 0:
        return []

    percent = round((spent_amount / monthly_budget) * 100)
    month_key = datetime.now().strftime("%Y-%m")
    existing_ids = {item.get("id") for item in read_notifications()}
    created = []

    rules = [
        {
            "key": "25",
            "threshold": 25,
            "type": "budget",
            "icon": "💰",
            "title": "25% budget used",
            "message": f"You have used 25% of your monthly budget. RM{spent_amount:.2f} / RM{monthly_budget:.2f} spent."
        },
        {
            "key": "50",
            "threshold": 50,
            "type": "budget",
            "icon": "💰",
            "title": "50% budget used",
            "message": f"You have used 50% of your monthly budget. RM{spent_amount:.2f} / RM{monthly_budget:.2f} spent."
        },
        {
            "key": "75",
            "threshold": 75,
            "type": "warning",
            "icon": "⚠️",
            "title": "75% budget used",
            "message": f"You have used 75% of your monthly budget. RM{spent_amount:.2f} / RM{monthly_budget:.2f} spent. Spend carefully."
        },
        {
            "key": "100",
            "threshold": 100,
            "type": "warning",
            "icon": "🚫",
            "title": "Budget limit reached",
            "message": f"You have reached or exceeded your monthly budget. RM{spent_amount:.2f} / RM{monthly_budget:.2f} spent."
        }
    ]

    for rule in rules:
        notification_id = f"budget_{rule['key']}_{month_key}"

        if percent >= rule["threshold"] and notification_id not in existing_ids:
            notification = create_notification({
                "id": notification_id,
                "type": rule["type"],
                "icon": rule["icon"],
                "title": rule["title"],
                "message": rule["message"],
                "budget_percent": percent
            })
            created.append(notification)

    return created

@app.route("/api/budget/summary", methods=["GET"])
def api_budget_summary():
    return jsonify(make_budget_summary())

@app.route("/api/budget/settings", methods=["POST"])
def api_budget_settings():
    data = request.get_json(silent=True) or {}
    monthly_budget = float(data.get("monthly_budget", data.get("monthlyBudget", 500)) or 500)
    set_monthly_budget(monthly_budget)

    summary = make_budget_summary()
    create_budget_threshold_notifications(summary["monthly_budget"], summary["spent"])

    return jsonify({
        "success": True,
        "summary": summary
    })

@app.route("/api/budget/expense", methods=["POST"])
def api_budget_add_expense():
    data = request.get_json(silent=True) or {}

    merchant = str(data.get("merchant", "")).strip()
    category = str(data.get("category", "food")).strip()
    amount = float(data.get("amount", 0) or 0)
    saved = float(data.get("saved", 0) or 0)
    voucher_id = str(data.get("voucher_id", data.get("voucherId", ""))).strip()

    if not merchant:
        return jsonify({
            "success": False,
            "message": "merchant is required"
        }), 400

    if amount <= 0:
        return jsonify({
            "success": False,
            "message": "amount must be greater than 0"
        }), 400

    rows = read_budget_expenses()
    now = datetime.now()

    new_expense = {
        "id": f"expense_{int(now.timestamp() * 1000)}",
        "date": data.get("date") or now.strftime("%Y-%m-%d"),
        "merchant": merchant,
        "category": category,
        "amount": amount,
        "saved": saved,
        "voucher_id": voucher_id
    }

    rows.insert(0, new_expense)
    write_budget_expenses(rows)

    summary = make_budget_summary()
    created_notifications = create_budget_threshold_notifications(summary["monthly_budget"], summary["spent"])

    return jsonify({
        "success": True,
        "expense": new_expense,
        "summary": summary,
        "created_notifications": created_notifications
    })
@app.route("/api/budget/expenses/<expense_id>/delete", methods=["DELETE", "POST"])
def api_delete_budget_expense(expense_id):
    try:
        expenses = read_budget_expenses()
        original_count = len(expenses)

        remaining_expenses = [
            expense for expense in expenses
            if str(expense.get("id", "")).strip() != str(expense_id).strip()
        ]

        write_budget_expenses(remaining_expenses)
        summary = make_budget_summary()

        return jsonify({
            "success": True,
            "deleted": len(remaining_expenses) < original_count,
            "summary": summary
        })
    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500\
    
def build_budget_ai_context(summary, expenses):
    monthly_budget = float(summary.get("monthly_budget", summary.get("monthlyBudget", summary.get("budget", 0))) or 0)

    total_spent = float(
        summary.get("spent",
            summary.get("total_spent",
                summary.get("totalSpent", 0)
            )
        ) or 0
    )

    remaining = float(summary.get("remaining", monthly_budget - total_spent) or 0)

    if "usage_percent" in summary:
        used_percent = round(float(summary.get("usage_percent") or 0))
    elif "used_percent" in summary:
        used_percent = round(float(summary.get("used_percent") or 0))
    elif monthly_budget > 0:
        used_percent = round((total_spent / monthly_budget) * 100)
    else:
        used_percent = 0

    category_totals = {}
    recent_expenses = []

    for expense in expenses:
        category = str(expense.get("category", "food") or "food").strip().lower()
        amount = float(expense.get("amount", 0) or 0)
        category_totals[category] = category_totals.get(category, 0) + amount

        recent_expenses.append({
            "date": expense.get("date", ""),
            "merchant": expense.get("merchant", ""),
            "category": category,
            "amount": amount,
            "saved": float(expense.get("saved", 0) or 0)
        })

    top_category = "none"
    top_category_amount = 0

    if category_totals:
        top_category, top_category_amount = max(category_totals.items(), key=lambda item: item[1])

    health_score = max(0, min(100, 100 - max(0, used_percent - 40)))

    if used_percent <= 50:
        mood = "happy"
        status = "On track"
        headline = "You are doing well so far."
    elif used_percent <= 75:
        mood = "thinking"
        status = "Watchful"
        headline = "You are still okay, but spending is picking up."
    elif used_percent <= 100:
        mood = "warning"
        status = "Careful"
        headline = "You are close to your budget limit."
    else:
        mood = "panic"
        status = "Over budget"
        headline = "You have exceeded your budget."

    if top_category == "none":
        tip = "Add your first expense and I can give smarter advice."
        challenge = "Start by tracking one meal today."
    elif used_percent > 100:
        tip = f"Pause non-essential spending. Your biggest category is {top_category.title()}."
        challenge = f"Try a no-spend challenge for {top_category.title()} tomorrow."
    elif used_percent >= 75:
        tip = f"Your {top_category.title()} spending is high. Try setting a smaller daily limit."
        challenge = f"Keep {top_category.title()} under RM20 for the next 2 days."
    else:
        tip = f"Nice. Your biggest category is {top_category.title()}, but your budget still looks healthy."
        challenge = "Save RM5 today by using a voucher or choosing a cheaper meal."

    return {
        "monthly_budget": monthly_budget,
        "total_spent": total_spent,
        "remaining": remaining,
        "used_percent": used_percent,
        "health_score": health_score,
        "mood": mood,
        "status": status,
        "headline": headline,
        "tip": tip,
        "challenge": challenge,
        "top_category": top_category,
        "top_category_amount": top_category_amount,
        "category_totals": category_totals,
        "recent_expenses": recent_expenses[:10]
    }

def get_gemini_model_candidates():
    configured_model = os.getenv("GEMINI_MODEL", "").strip()
    candidates = []

    if configured_model:
        candidates.append(configured_model)

    candidates.extend([
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash",
        "gemini-2.5-flash"
    ])

    unique_candidates = []
    for model_name in candidates:
        if model_name and model_name not in unique_candidates:
            unique_candidates.append(model_name)

    return unique_candidates

def call_gemini_text(prompt, label="AI"):
    api_key = get_gemini_api_key()

    if not api_key:
        return None, "GEMINI_API_KEY is missing"

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        last_error = None

        for model_name in get_gemini_model_candidates():
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                reply = getattr(response, "text", None)

                if reply:
                    return reply.strip(), None
            except Exception as error:
                last_error = error
                continue

        try:
            for available_model in genai.list_models():
                model_name = getattr(available_model, "name", "")
                methods = getattr(available_model, "supported_generation_methods", [])

                if "generateContent" not in methods:
                    continue

                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                reply = getattr(response, "text", None)

                if reply:
                    return reply.strip(), None
        except Exception as error:
            last_error = error

        return None, str(last_error or "Gemini returned no text")

    except Exception as error:
        print(f"Gemini {label} fallback:", error)
        return None, str(error)

def call_openai_text(system_prompt, user_payload, label="AI", max_tokens=220):
    api_key = get_openai_api_key()

    if not api_key:
        return None, "OPENAI_API_KEY is missing"

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False)
                }
            ],
            max_output_tokens=max_tokens
        )
        reply = getattr(response, "output_text", None)
        return (reply.strip(), None) if reply else (None, "OpenAI returned no text")

    except Exception as error:
        print(f"OpenAI {label} fallback:", error)
        return None, str(error)

def build_static_deal_vouchers():
    return [
        {
            "id": "good-burger",
            "merchant": "The Good Burger",
            "title": "30% OFF Total Bill",
            "offer": "30% OFF Total Bill",
            "category": "Burgers",
            "location": "Jalan Puchong Mesra",
            "keywords": "burger burgers fast food discount total bill"
        },
        {
            "id": "mcdonalds",
            "merchant": "McDonald's",
            "title": "15% OFF Total Bill",
            "offer": "15% OFF Total Bill",
            "category": "Fast Food",
            "location": "1.2 km away",
            "keywords": "mcd mcdonalds burger fries fast food"
        },
        {
            "id": "boost",
            "merchant": "Boost",
            "title": "10% OFF Smoothies",
            "offer": "10% OFF Smoothies",
            "category": "Drinks",
            "location": "1.6 km away",
            "keywords": "smoothie drink juice beverage"
        },
        {
            "id": "coffee-breaks",
            "merchant": "Coffee Breaks",
            "title": "RM5 OFF Cafe Picks",
            "offer": "RM5 OFF Cafe Picks",
            "category": "Cafe",
            "location": "Coffee and pastries",
            "keywords": "coffee cafe latte pastry"
        },
        {
            "id": "fresh-sushi",
            "merchant": "Fresh Sushi",
            "title": "18% OFF Sushi Sets",
            "offer": "18% OFF Sushi Sets",
            "category": "Sushi",
            "location": "Selected outlets",
            "keywords": "sushi japanese rolls salmon"
        },
        {
            "id": "sweet-treats",
            "merchant": "Sweet Treats",
            "title": "Up to 30% OFF",
            "offer": "Up to 30% OFF",
            "category": "Desserts",
            "location": "Cakes and waffles",
            "keywords": "dessert cake waffle sweet"
        }
    ]

def build_deal_ai_context():
    merchant_vouchers = []

    for voucher in get_all_vouchers():
        merchant_vouchers.append({
            "id": voucher.get("id"),
            "merchant": voucher.get("merchant_name") or voucher.get("name") or "Merchant",
            "title": voucher.get("VoucherTitle") or voucher.get("offer") or "Special Offer",
            "offer": voucher.get("offer") or "Special Deal",
            "category": voucher.get("category") or "Merchant Deal",
            "location": voucher.get("location") or voucher.get("Address") or "Selected outlets",
            "valid": voucher.get("valid") or voucher.get("ExpiryDate") or "No expiry",
            "keywords": "merchant voucher food deal"
        })

    return {
        "user_name": session.get("user_name", "User"),
        "vouchers": merchant_vouchers + build_static_deal_vouchers()
    }

def rule_based_deal_ai_reply(user_message, context):
    query = str(user_message or "").lower()
    vouchers = context.get("vouchers", [])

    def deal_score(voucher):
        text = " ".join([
            str(voucher.get("merchant", "")),
            str(voucher.get("title", "")),
            str(voucher.get("offer", "")),
            str(voucher.get("category", "")),
            str(voucher.get("location", "")),
            str(voucher.get("keywords", ""))
        ]).lower()

        score = 0
        tokens = [token for token in re.split(r"[^a-z0-9]+", query) if len(token) >= 3]
        for token in tokens:
            if token in text:
                score += 35

        percent_values = [int(match.group(1)) for match in re.finditer(r"(\d+)\s*%", text)]
        rm_values = [int(match.group(1)) for match in re.finditer(r"rm\s*(\d+)", text)]

        if percent_values:
            score += max(percent_values) * 2
        elif rm_values:
            score += min(max(rm_values) * 2, 60)

        if any(word in query for word in ["cheap", "under", "rm20", "budget"]) and any(word in text for word in ["mcd", "boost", "fast", "burger"]):
            score += 30

        return score

    ranked = sorted(vouchers, key=deal_score, reverse=True)
    best = ranked[0] if ranked else None

    if not best:
        return "I could not find available vouchers yet. Try asking for burger, coffee, dessert, drinks, sushi, or best discount."

    also = [item.get("merchant") for item in ranked[1:3] if item.get("merchant")]
    reason = "It matches what you asked and has one of the better savings in your app."

    return (
        f"My best pick is {best.get('merchant')}: {best.get('offer')}. "
        f"{reason}"
        + (f" You can also check {' or '.join(also)}." if also else "")
    )

def call_gemini_deal_assistant(user_message, context):
    prompt = (
        "You are Vouchr AI Deal Assistant. Your only job is to recommend the best food voucher/deal for the user. "
        "Use the available vouchers in the context. Compare discounts, food cravings, nearby wording, and budget wording. "
        "Keep the answer under 70 words. Name one best pick first, then optionally mention one backup. "
        "Do not give financial budgeting advice and do not troubleshoot app problems.\n\n"
        f"User request: {user_message or 'Recommend the best deal for me.'}\n\n"
        f"Available voucher context JSON: {json.dumps(context, ensure_ascii=False)}"
    )

    return call_gemini_text(prompt, "Deal Assistant")

def call_openai_deal_assistant(user_message, context):
    system_prompt = (
        "You are Vouchr AI Deal Assistant. Your only job is to recommend the best food voucher/deal for the user. "
        "Use the available vouchers in the context. Keep the answer under 70 words. "
        "Do not give financial budgeting advice and do not troubleshoot app problems."
    )
    return call_openai_text(
        system_prompt,
        {
            "user_request": user_message or "Recommend the best deal for me.",
            "available_vouchers": context
        },
        "Deal Assistant",
        190
    )

@app.route("/api/ai-deal-assistant", methods=["POST"])
def api_ai_deal_assistant():
    if session.get("role") not in ["user", "merchant"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_message = str(data.get("message", "") or "").strip()
    context = build_deal_ai_context()

    gemini_reply, gemini_error = call_gemini_deal_assistant(user_message, context)
    openai_reply, openai_error = (None, None)

    if not gemini_reply:
        openai_reply, openai_error = call_openai_deal_assistant(user_message, context)

    ai_reply = gemini_reply or openai_reply
    reply = ai_reply or rule_based_deal_ai_reply(user_message, context)

    return jsonify({
        "success": True,
        "ai_enabled": bool(ai_reply),
        "reply": reply,
        "provider": "gemini" if gemini_reply else ("openai" if openai_reply else "local"),
        "ai_error": None if ai_reply else (gemini_error or openai_error)
    })

def rule_based_money_coach_reply(user_message, context):
    message = str(user_message or "").lower()

    if "save" in message:
        return f"{context['tip']} My suggestion: {context['challenge']}"

    if "health" in message or "score" in message:
        return f"Your budget health score is {context['health_score']}/100. Status: {context['status']}. You have used {context['used_percent']}% of your monthly budget."

    if "biggest" in message or "category" in message or "spending" in message:
        return f"Your biggest spending category is {context['top_category'].title()} at RM{context['top_category_amount']:.2f}."

    if "challenge" in message or "goal" in message:
        return context["challenge"]

    if message:
        return f"{context['headline']} {context['tip']}"

    return context["headline"]
def call_gemini_money_coach(user_message, context):
    prompt = (
        "You are Vouchr AI Money Coach, a friendly budgeting coach for students in Malaysia. "
        "Give simple, practical, encouraging financial habit advice. "
        "Use the user's budget data provided. "
        "Do not provide investment, loan, tax, legal, insurance, or high-risk financial advice. "
        "Do not recommend stocks, crypto, borrowing money, or financial products. "
        "Keep the reply under 85 words. "
        "Use RM currency when mentioning money. "
        "Be specific and helpful. "
        "If the user asks something outside budgeting, gently bring it back to spending, saving, and habits.\n\n"
        f"User message: {user_message or 'Give me a budget health check.'}\n\n"
        f"Budget context JSON: {json.dumps(context, ensure_ascii=False)}"
    )

    return call_gemini_text(prompt, "AI Money Coach")

def call_openai_money_coach(user_message, context):
    system_prompt = (
        "You are Vouchr AI Money Coach, a friendly budgeting coach for students in Malaysia. "
        "Give simple, practical, encouraging financial habit advice. "
        "Use the user's budget data provided. "
        "Do not provide investment, loan, tax, legal, insurance, or high-risk financial advice. "
        "Do not recommend stocks, crypto, borrowing money, or financial products. "
        "Keep the reply under 85 words. "
        "Use RM currency when mentioning money. "
        "Be specific and helpful. "
        "If the user asks something outside budgeting, gently bring it back to spending, saving, and habits."
    )

    return call_openai_text(
        system_prompt,
        {
            "user_message": user_message or "Give me a budget health check.",
            "budget_context": context
        },
        "AI Money Coach",
        220
    )


@app.route("/api/ai-money-coach", methods=["GET", "POST"])
def api_ai_money_coach():
    summary = make_budget_summary()
    expenses = read_budget_expenses()
    context = build_budget_ai_context(summary, expenses)

    data = request.get_json(silent=True) or {}
    user_message = str(data.get("message", "") or "")

    gemini_reply, gemini_error = call_gemini_money_coach(user_message, context)
    openai_reply, openai_error = (None, None)

    if not gemini_reply:
        openai_reply, openai_error = call_openai_money_coach(user_message, context)

    ai_reply = gemini_reply or openai_reply
    reply = ai_reply or rule_based_money_coach_reply(user_message, context)

    quick_replies = [
        "How can I save more this week?",
        "Check my budget health",
        "What is my biggest spending?",
        "Give me a saving challenge"
    ]

    return jsonify({
        "success": True,
        "ai_enabled": bool(ai_reply),
        "provider": "gemini" if gemini_reply else ("openai" if openai_reply else "local"),
        "ai_error": None if ai_reply else (gemini_error or openai_error),
        "reply": reply,
        "mood": context["mood"],
        "status": context["status"],
        "headline": context["headline"],
        "tip": context["tip"],
        "challenge": context["challenge"],
        "health_score": context["health_score"],
        "monthly_budget": context["monthly_budget"],
        "total_spent": context["total_spent"],
        "remaining": context["remaining"],
        "used_percent": context["used_percent"],
        "top_category": context["top_category"],
        "top_category_amount": context["top_category_amount"],
        "quick_replies": quick_replies
    })

def build_help_center_context():
    summary = make_budget_summary()
    vouchers = get_all_vouchers()

    return {
        "user_name": session.get("user_name", "User"),
        "voucher_count": len(vouchers),
        "vouchers": [
            {
                "merchant": voucher.get("merchant_name") or voucher.get("name") or "Merchant",
                "title": voucher.get("VoucherTitle") or voucher.get("offer") or "Special Deal",
                "offer": voucher.get("offer") or "Special Deal",
                "location": voucher.get("location") or voucher.get("Address") or "Selected outlets",
                "valid": voucher.get("valid") or voucher.get("ExpiryDate") or "No expiry"
            }
            for voucher in vouchers[:15]
        ],
        "budget": {
            "monthly_budget": summary.get("monthly_budget", summary.get("monthlyBudget", summary.get("budget", 0))),
            "spent": summary.get("spent", summary.get("total_spent", summary.get("totalSpent", 0))),
            "remaining": summary.get("remaining", 0)
        },
        "app_sections": [
            "Main menu",
            "Voucher tab",
            "Map",
            "Budget",
            "Profile",
            "Notifications",
            "AI Money Coach"
        ]
    }

def find_help_voucher_matches(message, context):
    query = str(message or "").lower().strip()
    if len(query) < 2:
        return []

    stop_words = {"how", "what", "where", "when", "why", "can", "the", "and", "for", "find", "search", "voucher", "vouchers", "deal", "deals", "offer", "offers"}
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", query)
        if len(token) >= 3 and token not in stop_words
    ]
    matches = []
    for voucher in context.get("vouchers", []):
        searchable = " ".join([
            str(voucher.get("merchant", "")),
            str(voucher.get("title", "")),
            str(voucher.get("offer", "")),
            str(voucher.get("location", ""))
        ]).lower()

        if query in searchable or any(token in searchable for token in tokens):
            matches.append(voucher)

    return matches[:3]

def get_help_message_category(user_message):
    lowered = str(user_message or "").lower()

    if any(word in lowered for word in ["feedback", "suggestion", "suggest", "improve", "idea", "review"]):
        return "feedback"

    if any(word in lowered for word in ["problem", "issue", "bug", "error", "broken", "not working", "stuck", "crash", "wrong"]):
        return "problem"

    return "support"

def save_help_feedback(user_message, category):
    should_save = category in {"feedback", "problem"}

    if not should_save:
        return False

    file_exists = FEEDBACK_CSV.exists()

    with FEEDBACK_CSV.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FEEDBACK_FIELDS)

        if not file_exists:
            writer.writeheader()

        writer.writerow({
            "id": f"feedback_{int(datetime.now().timestamp())}",
            "user_name": session.get("user_name", "User"),
            "message": str(user_message or "").strip(),
            "category": category,
            "created_at": datetime.now().isoformat(timespec="seconds")
        })

    return True

def rule_based_help_center_reply(user_message, context):
    message = str(user_message or "").strip()
    lowered = message.lower()
    category = get_help_message_category(message)

    if not message:
        return "Tell me what is not working in Vouchr, or send feedback about what should be improved. I can help with login, profile, vouchers, notifications, search, budget pages, and app navigation."

    if category == "feedback":
        return "Thanks for the feedback. I saved it for review. If you can, include which page it happened on and what you expected to happen."

    if category == "problem":
        return "I saved this as an app issue. To narrow it down, tell me which page you were on, what button you pressed, and what happened after that."

    if any(word in lowered for word in ["redeem", "claim", "qr", "cashier", "use voucher"]):
        return "To redeem a voucher, open the voucher, tap Redeem Voucher, then show the QR code to the cashier. If you only see View, tap it first to open the voucher details."

    if any(word in lowered for word in ["budget", "spending", "expense", "spent", "remaining"]):
        return "For financial advice, open Budget and use AI Money Coach. This Help Center can still help if the Budget page is broken or confusing."

    if any(word in lowered for word in ["search", "find", "deal", "voucher", "discount", "offer"]):
        return "For best-deal recommendations, use the AI Deal Assistant on the Main page. If search or voucher buttons are not working, tell me what you searched and what went wrong."

    if any(word in lowered for word in ["notification", "alert", "new voucher", "bell"]):
        return "Tap the bell on the Main page to see voucher and budget notifications. In Profile, open Notifications to choose which alerts you want to receive."

    if any(word in lowered for word in ["profile", "name", "email", "password", "personal"]):
        return "Open Profile, then Personal Details. You can update your name, email, phone, profile picture, and password from there."

    if any(word in lowered for word in ["save", "saved", "favorite", "favourite"]):
        return "Open a voucher and tap Save Voucher. Saved vouchers are available from Profile under Saved Vouchers and from the Voucher tab."

    if any(word in lowered for word in ["map", "near", "nearby", "location"]):
        return "Open the Map tab to browse nearby deals and restaurant locations. You can also use Main search when you already know what you want."

    if any(word in lowered for word in ["ai", "coach", "money coach", "advice"]):
        return "There are three AIs: Main page AI recommends deals, Budget AI gives saving and spending advice, and this Help Center AI handles app problems and feedback."

    if any(word in lowered for word in ["merchant", "publish", "create voucher", "business"]):
        return "Merchants can create and publish vouchers from the merchant side. Published vouchers can appear in Main, Voucher search, and the voucher lists for users."

    return "I can help you fix app problems or give feedback. Tell me which page you are on, what you tapped, and what happened."

def call_gemini_help_center(user_message, context):
    prompt = (
        "You are Vouchr Help Center AI, a friendly in-app support assistant. "
        "Your job is app support, troubleshooting, and collecting feedback. "
        "Help users explain problems with Vouchr pages, buttons, voucher redemption, login, notifications, search, profile, map, and navigation. "
        "Do not act as the deal recommendation AI or the financial advice AI. "
        "If users ask for best deals, point them to AI Deal Assistant on Main. "
        "If users ask for saving or budget advice, point them to AI Money Coach on Budget. "
        "Keep replies under 90 words. Be clear, calm, and practical.\n\n"
        f"User question: {user_message}\n\n"
        f"Vouchr context JSON: {json.dumps(context, ensure_ascii=False)}"
    )

    return call_gemini_text(prompt, "Help Center")

def call_openai_help_center(user_message, context):
    system_prompt = (
        "You are Vouchr Help Center AI, a friendly in-app support assistant. "
        "Your job is app support, troubleshooting, and collecting feedback. "
        "Help users explain problems with Vouchr pages, buttons, voucher redemption, login, notifications, search, profile, map, and navigation. "
        "Do not act as the deal recommendation AI or the financial advice AI. "
        "If users ask for best deals, point them to AI Deal Assistant on Main. "
        "If users ask for saving or budget advice, point them to AI Money Coach on Budget. "
        "Keep replies under 90 words. Be clear and practical."
    )

    return call_openai_text(
        system_prompt,
        {
            "question": user_message,
            "context": context
        },
        "Help Center",
        220
    )

@app.route("/api/help-center", methods=["POST"])
def api_help_center():
    if session.get("role") not in {"user", "merchant"}:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_message = str(data.get("message", "") or "").strip()
    context = build_help_center_context()
    category = get_help_message_category(user_message)
    feedback_saved = save_help_feedback(user_message, category)

    gemini_reply, gemini_error = call_gemini_help_center(user_message, context)
    openai_reply, openai_error = (None, None)

    if not gemini_reply:
        openai_reply, openai_error = call_openai_help_center(user_message, context)

    ai_reply = gemini_reply or openai_reply
    reply = ai_reply or rule_based_help_center_reply(user_message, context)

    return jsonify({
        "success": True,
        "ai_enabled": bool(ai_reply),
        "feedback_saved": feedback_saved,
        "provider": "gemini" if gemini_reply else ("openai" if openai_reply else "local"),
        "ai_error": None if ai_reply else (gemini_error or openai_error),
        "reply": reply,
        "suggestions": [
            "Something is not working",
            "I want to give feedback",
            "How do I report a bug?",
            "How do notifications work?"
        ]
    })

@app.route("/api/announcements")
def api_announcements():
    return api_active_announcements()


@app.route("/api/announcements/active")
def api_active_announcements():
    user_id, audience_role = current_announcement_identity()
    announcements = vouchr_db.active_announcements_for_user(user_id, audience_role)
    return jsonify({
        "success": True,
        "announcements": announcements,
        "unread_count": len(announcements),
        "role": audience_role
    })

def current_db_user_id():
    """Return the database user id for the logged-in customer or merchant session."""
    role = session.get("role", "unknown")

    if role == "merchant":
        merchant_name = str(session.get("merchant_name", "") or "").strip()
        if merchant_name:
            merchant = vouchr_db.query_one(
                "SELECT id, user_id, business_name FROM merchants WHERE lower(business_name) = lower(?)",
                (merchant_name,),
            )
            if merchant and merchant.get("user_id"):
                return merchant["user_id"]

            # If the merchant exists in CSV but has not been synced into SQLite yet,
            # create/update the merchant login user first so live chat can be attached
            # to the real merchant account instead of a fallback customer account.
            for row in read_merchants():
                if str(row.get("name") or "").strip().lower() == merchant_name.lower():
                    return vouchr_db.upsert_merchant(
                        row.get("name") or merchant_name,
                        row.get("email") or "",
                        row.get("password") or "",
                        row.get("address") or "",
                        row.get("id"),
                        row.get("created_at"),
                    ) and vouchr_db.query_one(
                        "SELECT user_id FROM merchants WHERE lower(business_name) = lower(?)",
                        (merchant_name,),
                    )["user_id"]

            merchant_id = vouchr_db.upsert_merchant(merchant_name)
            merchant = vouchr_db.query_one("SELECT user_id FROM merchants WHERE id = ?", (merchant_id,))
            if merchant and merchant.get("user_id"):
                return merchant["user_id"]

    user = vouchr_db.get_user_by_email_or_name(
        session.get("user_email", ""),
        session.get("user_name", "User")
    )
    if user:
        return user["id"]
    return vouchr_db.ensure_user(session.get("user_name", "User"), session.get("user_email", ""))


def current_announcement_identity():
    role = session.get("role", "unknown")
    if role == "user":
        user = vouchr_db.get_user_by_email_or_name(
            session.get("user_email", ""),
            session.get("user_name", "User")
        )
        user_id = user["id"] if user else vouchr_db.ensure_user(
            session.get("user_name", "User"),
            session.get("user_email", "")
        )
        return user_id, "customer"

    if role == "merchant":
        # Use the merchant login account's database user_id so merchant announcements
        # can be filtered and marked as read just like customer announcements.
        return current_db_user_id(), "merchant"

    return None, "unknown"


def current_live_support_user():
    """Allow both customer and merchant sessions to open live support chats."""
    if session.get("role") not in {"user", "merchant"}:
        return None, jsonify({"success": False, "error": "Login required"}), 401

    user_id = current_db_user_id()
    user = vouchr_db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))

    if not user:
        return None, jsonify({"success": False, "error": "Account not found"}), 404

    return user, None, None


def customer_can_access_live_session(session_id, user_id):
    support_session = vouchr_db.get_live_support_session(session_id)
    if not support_session or support_session.get("user_id") != user_id:
        return None
    return support_session


@app.route("/api/announcements/<int:announcement_id>/read", methods=["POST"])
def api_mark_announcement_read(announcement_id):
    user_id, _ = current_announcement_identity()
    stored = vouchr_db.mark_announcement_read(announcement_id, user_id) if user_id else False
    return jsonify({
        "success": True,
        "stored": stored
    })


@app.route("/api/announcements/read-all", methods=["POST"])
def api_mark_all_announcements_read():
    user_id, audience_role = current_announcement_identity()
    marked = vouchr_db.mark_all_active_announcements_read(user_id, audience_role) if user_id else 0
    return jsonify({
        "success": True,
        "marked": marked
    })


@app.route("/api/live-support/session")
def api_live_support_session():
    user, error_response, status = current_live_support_user()
    if error_response:
        return error_response, status
    support_session = vouchr_db.get_active_live_support_session(user["id"])
    return jsonify({
        "success": True,
        "session": support_session,
        "agent_available": vouchr_db.live_support_agent_available()
    })


@app.route("/api/live-support/start", methods=["POST"])
def api_live_support_start():
    user, error_response, status = current_live_support_user()
    if error_response:
        return error_response, status

    data = request.get_json(silent=True) or {}
    subject = str(data.get("subject") or "Live Support").strip() or "Live Support"
    first_message = str(data.get("message") or "").strip()
    support_session = vouchr_db.start_live_support_session(user["id"], subject)
    if first_message:
        vouchr_db.add_live_support_message(support_session["id"], user["id"], user.get("role") or "customer", first_message)
        support_session = vouchr_db.get_live_support_session(support_session["id"])

    return jsonify({
        "success": True,
        "session": support_session,
        "session_id": support_session["id"],
        "agent_available": vouchr_db.live_support_agent_available()
    })


@app.route("/api/live-support/<int:session_id>/messages")
def api_live_support_messages(session_id):
    user, error_response, status = current_live_support_user()
    if error_response:
        return error_response, status
    support_session = customer_can_access_live_session(session_id, user["id"])
    if not support_session:
        return jsonify({"success": False, "error": "Chat not found"}), 404
    return jsonify({
        "success": True,
        "session": support_session,
        "messages": vouchr_db.get_live_support_messages(session_id),
        "agent_available": vouchr_db.live_support_agent_available()
    })


@app.route("/api/live-support/<int:session_id>/send", methods=["POST"])
def api_live_support_send(session_id):
    user, error_response, status = current_live_support_user()
    if error_response:
        return error_response, status
    support_session = customer_can_access_live_session(session_id, user["id"])
    if not support_session:
        return jsonify({"success": False, "error": "Chat not found"}), 404
    if support_session.get("status") in {"resolved", "ended"}:
        return jsonify({"success": False, "error": "This chat has ended"}), 400

    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400
    vouchr_db.add_live_support_message(session_id, user["id"], user.get("role") or "customer", message)
    return jsonify({
        "success": True,
        "session": vouchr_db.get_live_support_session(session_id),
        "messages": vouchr_db.get_live_support_messages(session_id)
    })


@app.route("/api/live-support/<int:session_id>/end", methods=["POST"])
def api_live_support_end(session_id):
    user, error_response, status = current_live_support_user()
    if error_response:
        return error_response, status
    support_session = customer_can_access_live_session(session_id, user["id"])
    if not support_session:
        return jsonify({"success": False, "error": "Chat not found"}), 404
    updated = vouchr_db.end_live_support_session(
        session_id,
        status="ended",
        actor_id=user["id"],
        message=("The merchant ended this live support chat." if user.get("role") == "merchant" else "The customer ended this live support chat.")
    )
    return jsonify({
        "success": True,
        "session": updated
    })


@app.route("/api/activity/save-voucher", methods=["POST"])
def api_activity_save_voucher():
    if session.get("role") != "user":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    voucher_id = str(data.get("voucher_id") or data.get("id") or "").strip()
    voucher_name = str(data.get("voucher_name") or data.get("name") or "Voucher").strip()
    voucher_title = str(data.get("voucher_title") or data.get("title") or "").strip()
    merchant_name = str(data.get("merchant_name") or data.get("merchant") or "").strip()

    def normalise(value):
        return slugify(str(value or ""))

    incoming_voucher_id = normalise(voucher_id)
    incoming_title = normalise(voucher_title)
    incoming_name = normalise(voucher_name)
    incoming_merchant = normalise(merchant_name)

    matched_voucher = None
    all_vouchers = get_all_vouchers()

    # 1) Best match: exact voucher id from the merchant CSV / DB.
    if incoming_voucher_id:
        for voucher in all_vouchers:
            if normalise(voucher.get("id")) == incoming_voucher_id:
                matched_voucher = voucher
                break

    # 2) Strong match: same merchant + same voucher title / offer.
    if not matched_voucher and incoming_merchant:
        for voucher in all_vouchers:
            merchant_candidates = {
                normalise(voucher.get("merchant_name")),
                normalise(voucher.get("name")),
            }
            title_candidates = {
                normalise(voucher.get("VoucherTitle")),
                normalise(voucher.get("offer")),
                normalise(voucher.get("description")),
            }
            incoming_titles = {incoming_title, incoming_name}
            if incoming_merchant in merchant_candidates and (title_candidates & incoming_titles):
                matched_voucher = voucher
                break

    # 3) Fallback match: voucher title / offer only.
    if not matched_voucher:
        for voucher in all_vouchers:
            title_candidates = {
                normalise(voucher.get("id")),
                normalise(voucher.get("VoucherTitle")),
                normalise(voucher.get("offer")),
            }
            incoming_titles = {incoming_voucher_id, incoming_title, incoming_name}
            if title_candidates & incoming_titles:
                matched_voucher = voucher
                break

    if matched_voucher:
        voucher_id = matched_voucher.get("id") or voucher_id or slugify(voucher_title or voucher_name)
        voucher_name = matched_voucher.get("merchant_name") or matched_voucher.get("name") or voucher_name or "Voucher"
        voucher_title = matched_voucher.get("VoucherTitle") or matched_voucher.get("offer") or voucher_title or voucher_name
        merchant_name = matched_voucher.get("merchant_name") or matched_voucher.get("name") or merchant_name or "Merchant"

    if not voucher_id:
        voucher_id = slugify(voucher_title or voucher_name)

    existing = vouchr_db.query_one("SELECT id, merchant_id FROM vouchers WHERE id = ?", (voucher_id,))
    if not existing:
        vouchr_db.upsert_voucher(merchant_name or "Demo Merchant", {
            "id": voucher_id,
            "VoucherTitle": voucher_title or voucher_name,
            "Status": "Active",
            "Total": matched_voucher.get("Total", 0) if matched_voucher else 0,
            "Redeemed": matched_voucher.get("Redeemed", 0) if matched_voucher else 0,
            "ExpiryDate": matched_voucher.get("ExpiryDate", "") if matched_voucher else "",
            "Address": matched_voucher.get("Address", matched_voucher.get("location", "")) if matched_voucher else "",
            "ImageUrl": matched_voucher.get("ImageUrl", matched_voucher.get("logo", "/assets/default-logo.png")) if matched_voucher else "/assets/default-logo.png",
        })
        existing = vouchr_db.query_one("SELECT id, merchant_id FROM vouchers WHERE id = ?", (voucher_id,))

    user_id = current_db_user_id()
    saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vouchr_db.execute(
        """
        INSERT OR IGNORE INTO saved_vouchers (user_id, voucher_id, saved_at)
        VALUES (?, ?, ?)
        """,
        (user_id, voucher_id, saved_at)
    )

    merchant_id = existing.get("merchant_id") if existing else None
    merchant_saves = 0
    if merchant_id:
        total_saves = vouchr_db.query_one(
            """
            SELECT COUNT(*) AS c
            FROM saved_vouchers sv
            JOIN vouchers v ON sv.voucher_id = v.id
            WHERE v.merchant_id = ?
            """,
            (merchant_id,)
        )
        merchant_saves = int(total_saves["c"] if total_saves else 0)

    return jsonify({
        "success": True,
        "voucher_id": voucher_id,
        "merchant_id": merchant_id,
        "merchant_saves": merchant_saves
    })

@app.route("/api/activity/redeem-voucher", methods=["POST"])
def api_activity_redeem_voucher():
    if session.get("role") != "user":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    voucher_id = str(data.get("voucher_id") or "").strip()
    voucher_name = str(data.get("voucher_name") or data.get("name") or "Voucher").strip()
    redemption_code = str(data.get("redemption_code") or "").strip()

    if not voucher_id:
        voucher_id = slugify(voucher_name)

    voucher = vouchr_db.query_one("SELECT id, merchant_id FROM vouchers WHERE id = ?", (voucher_id,))
    if not voucher:
        vouchr_db.upsert_voucher("Demo Merchant", {
            "id": voucher_id,
            "VoucherTitle": voucher_name,
            "Status": "Active",
            "Total": 0,
            "Redeemed": 0
        })
        voucher = vouchr_db.query_one("SELECT id, merchant_id FROM vouchers WHERE id = ?", (voucher_id,))

    user_id = current_db_user_id()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vouchr_db.execute(
        """
        INSERT INTO voucher_redemptions (user_id, voucher_id, merchant_id, redemption_code, redeemed_at, status)
        VALUES (?, ?, ?, ?, ?, 'redeemed')
        """,
        (user_id, voucher_id, voucher.get("merchant_id") if voucher else None, redemption_code, now)
    )
    vouchr_db.execute(
        "UPDATE vouchers SET redeemed_count = redeemed_count + 1, updated_at = ? WHERE id = ?",
        (now, voucher_id)
    )
    if voucher and voucher.get("merchant_id"):
        vouchr_db.log_merchant_activity(
            voucher.get("merchant_id"),
            None,
            "Voucher Redeemed",
            voucher_name,
            "redemption",
            voucher_id,
            now
        )
        repeated = vouchr_db.query_one(
            """
            SELECT COUNT(*) AS c
            FROM voucher_redemptions
            WHERE user_id = ? AND voucher_id = ? AND status = 'redeemed'
            """,
            (user_id, voucher_id)
        )
        if repeated and repeated.get("c", 0) >= 3:
            vouchr_db.flag_voucher_for_review(
                voucher_id,
                voucher.get("merchant_id"),
                "medium",
                "Same voucher repeatedly redeemed by same user",
                72,
                False
            )

    return jsonify({"success": True})

#======================End of Budget API====================

@app.route("/profile")
def profile():
    if session.get("role") != "user":
        return redirect("/auth.html")

    profile_path = os.path.join(app.root_path, "profile.html")
    template_path = os.path.join(app.root_path, "templates", "profile.html")
    user_name = session.get("user_name", "User")
    user_email = session.get("user_email", "")
    created_at = ""

    for user in read_users():
        same_email = user_email and user.get("email", "").lower().strip() == user_email.lower().strip()
        same_name = user.get("name") == user_name

        if same_email or same_name:
            user_email = user_email or user.get("email", "")
            created_at = user.get("created_at", "")
            break

    member_since = "2026"
    if created_at:
        try:
            member_since = datetime.strptime(created_at.split()[0], "%Y-%m-%d").strftime("%Y")
        except ValueError:
            member_since = created_at[:4] or member_since

    if os.path.exists(template_path):
        return render_template(
            "profile.html",
            user_name=user_name,
            user_email=user_email,
            member_since=member_since
        )

    if os.path.exists(profile_path):
        return send_from_directory(app.root_path, "profile.html")

    return "profile.html not found. Put profile.html beside app.py or inside templates folder.", 404

@app.route("/support", methods=["GET", "POST"])
def support():
    role = session.get("role")
    if role not in {"user", "merchant"}:
        return redirect("/auth.html")

    is_merchant = role == "merchant"

    if is_merchant:
        merchant_name = session.get("merchant_name", "Merchant")
        user_id = current_db_user_id()
        display_name = merchant_name
        back_href = "/merchant-profile"
    else:
        user = vouchr_db.get_user_by_email_or_name(
            session.get("user_email", ""),
            session.get("user_name", "User")
        )
        user_id = user["id"] if user else vouchr_db.ensure_user(
            session.get("user_name", "User"),
            session.get("user_email", "")
        )
        display_name = session.get("user_name", "User")
        back_href = "/profile"

    if request.method == "POST":
        action = request.form.get("action", "create")

        if action == "reply":
            ticket_id = request.form.get("ticket_id", "").strip()
            message = request.form.get("message", "").strip()
            ticket = vouchr_db.query_one(
                "SELECT id FROM support_tickets WHERE id = ? AND user_id = ?",
                (ticket_id, user_id)
            )
            if ticket and message:
                vouchr_db.add_ticket_message(ticket_id, user_id, "merchant" if is_merchant else "customer", message)
            return redirect(f"/support?ticket_id={ticket_id}")

        subject = request.form.get("subject", "").strip()
        issue_type = request.form.get("issue_type", "other").strip()
        priority = request.form.get("priority", "medium").strip()
        message = request.form.get("message", "").strip()

        if subject and message:
            ticket_id = vouchr_db.create_support_ticket(user_id, subject, issue_type, message, priority)
            return redirect(f"/support?ticket_id={ticket_id}")

    tickets = vouchr_db.list_support_tickets(user_id=user_id)
    selected_id = request.args.get("ticket_id") or (tickets[0]["id"] if tickets else None)
    selected_ticket = None
    messages = []

    if selected_id:
        selected_ticket, messages = vouchr_db.get_ticket(selected_id)
        if selected_ticket and selected_ticket["user_id"] != user_id:
            selected_ticket = None
            messages = []

    return render_template(
        "support.html",
        tickets=tickets,
        selected_ticket=selected_ticket,
        messages=messages,
        user_name=display_name,
        is_merchant=is_merchant,
        back_href=back_href
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/auth.html")

# ====================== MERCHANT PAGES =================================
@app.route("/merchant-main-menu")
def merchant_main_menu():
    merchant_name = session.get("merchant_name")
    if not merchant_name: 
        return redirect("/auth.html")
    
    auto_update_voucher_statuses(merchant_name)

    # Keep the SQLite voucher table aligned with the latest merchant CSV files
    # before calculating merchant analytics such as saves and redemptions.
    vouchr_db.sync_from_csv()
    merchant_row = vouchr_db.query_one(
        "SELECT id FROM merchants WHERE lower(business_name) = lower(?)",
        (merchant_name,),
    )
    merchant_id = merchant_row["id"] if merchant_row else vouchr_db.upsert_merchant(merchant_name)

    csv_filepath = get_merchant_csv_path(merchant_name)
    vouchers = []
    inactive_vouchers = []
    total_redeemed = 0
    active_promos = 0

    def clean_food_title(raw_title):
        clean = re.sub(r'[0-9\$%]', '', raw_title) 
        clean = re.sub(r'(?i)\b(off|free|discount|voucher|promo|buy one get one)\b', '', clean) 
        return clean.strip() or "delicious restaurant meal"

    if csv_filepath.exists():
        with csv_filepath.open(mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file, skipinitialspace=True)
            for row in reader:
                try:
                    title = str(row.get('VoucherTitle') or 'Unknown').strip()
                    status = str(row.get('Status') or 'Inactive').strip()
                    
                    # Check if this inactive voucher was dismissed
                    dismissed = str(row.get('Dismissed', 'False')).strip().lower() == 'true'
                    
                    try: 
                        redeemed = int(row.get('Redeemed') or 0)
                    except ValueError: 
                        redeemed = 0
                        
                    try: 
                        total = int(row.get('Total') or 1)
                    except ValueError: 
                        total = 1
                        
                    image_url = str(row.get('ImageUrl') or '').strip()
                    percentage = int((redeemed / total) * 100) if total > 0 else 0
                    
                    # --- NEW: Grab and format the Expiry Date ---
                    # --- Grab and format the Expiry Date ---
                    raw_date = str(row.get('ExpiryDate') or '').strip()
                    
                    if raw_date and raw_date.lower() not in ['none', 'no expiry']:
                        try:
                            # Convert the YYYY-MM-DD string from the CSV into a Python datetime object
                            dt = datetime.strptime(raw_date, "%Y-%m-%d")
                            # Format it beautifully (e.g., "24 Nov 2026")
                            expiry_date = dt.strftime("%d %b %Y")
                        except ValueError:
                            # If the date is formatted weirdly in the CSV, just use the raw text
                            expiry_date = raw_date
                    else:
                        expiry_date = "No Expiry"
                    # --------------------------------------------

                    voucher_data = {
                        'title': title,
                        'clean_title': clean_food_title(title),
                        'status': status,
                        'redeemed': redeemed,
                        'total': total,
                        'percentage': percentage,
                        'image_url': image_url,
                        'expiry_date': expiry_date,
                        'expiry_raw': raw_date
                    }
                    
                    vouchers.append(voucher_data)
                    total_redeemed += redeemed
                    
                    # Only show in Notifications if Inactive AND NOT dismissed
                    if status.lower() == 'active': 
                        active_promos += 1
                    elif not dismissed:
                        inactive_vouchers.append(voucher_data)
                        
                except Exception as e:
                    print(f"Skipped bad row: {row}, Error: {e}")

    today = datetime.now()
    graph_data = []
    chart_labels = []

    for i in range(6, -1, -1):
        target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        chart_labels.append((today - timedelta(days=i)).strftime("%d %b"))

        # Count actual redemptions for this specific merchant on this day.
        daily_count = vouchr_db.query_one(
            "SELECT COUNT(*) as c FROM voucher_redemptions WHERE merchant_id = ? AND substr(redeemed_at, 1, 10) = ?",
            (merchant_id, target_date)
        )
        graph_data.append(int(daily_count["c"] if daily_count else 0))

    def build_demo_weekly_redemptions(total_amount):
        """Return seven fake daily values whose sum never exceeds total_amount."""
        total_amount = max(0, int(total_amount or 0))
        if total_amount <= 0:
            return [0, 0, 0, 0, 0, 0, 0]

        # Keep the weekly demo realistic: recent seven days are a portion of total redemptions,
        # but still visible even when the merchant only has a few redemptions.
        weekly_total = min(total_amount, max(1, round(total_amount * 0.6)))
        weights = [1, 2, 1, 3, 2, 4, 3]
        values = [0] * 7

        for _ in range(weekly_total):
            index = max(range(7), key=lambda idx: weights[idx] / (values[idx] + 1))
            values[index] += 1

        return values

    # Use presentation-friendly fake daily numbers when the real redemption table has no entries.
    # The fake weekly total is capped so it never exceeds the Total Redeemed card.
    if not any(graph_data):
        if total_redeemed <= 0:
            total_redeemed = 8
        graph_data = build_demo_weekly_redemptions(total_redeemed)

    # Safety cap: even if database data is odd, the seven-day graph cannot exceed total redeemed.
    weekly_sum = sum(graph_data)
    if total_redeemed >= 0 and weekly_sum > total_redeemed:
        overflow = weekly_sum - total_redeemed
        for index in range(len(graph_data) - 1, -1, -1):
            remove_amount = min(graph_data[index], overflow)
            graph_data[index] -= remove_amount
            overflow -= remove_amount
            if overflow <= 0:
                break

    # 2. Calculate Funnel Metrics (Views -> Saves -> Redemptions)
    total_saves = vouchr_db.query_one(
        """
        SELECT COUNT(*) as c
        FROM saved_vouchers sv
        JOIN vouchers v ON sv.voucher_id = v.id
        WHERE v.merchant_id = ?
        """,
        (merchant_id,)
    )
    saves_count = int(total_saves["c"] if total_saves else 0)
    
    # Since we do not track pure view impressions yet, show a stronger presentation-friendly
    # estimate based on active voucher reach, saves, and actual redemptions.
    # This makes Total Views visibly higher than Voucher Saves and Actual Redemptions.
    views_count = (saves_count * 9) + (active_promos * 160) + (total_redeemed * 14)

    # Keep Voucher Saves as real database data so customer Save Voucher clicks
    # are reflected accurately in the merchant statistics.
    if views_count <= 0:
        views_count = 0
    else:
        views_count = max(views_count, saves_count, total_redeemed)

    funnel_data = {
        "views": views_count,
        "saves": saves_count,
        "redemptions": total_redeemed
    }

    return render_template('merchant_main_menu.html', 
                           merchant_name=merchant_name, 
                           total_redeemed=total_redeemed, 
                           active_promos=active_promos, 
                           vouchers=vouchers, 
                           inactive_vouchers=inactive_vouchers, 
                           graph_data=graph_data,
                           chart_labels=chart_labels,
                           funnel_data=funnel_data)


@app.route("/api/merchant/voucher-statistics")
def api_merchant_voucher_statistics():
    merchant_name = session.get("merchant_name")
    if not merchant_name:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    vouchr_db.sync_from_csv()
    merchant_row = vouchr_db.query_one(
        "SELECT id FROM merchants WHERE lower(business_name) = lower(?)",
        (merchant_name,),
    )
    merchant_id = merchant_row["id"] if merchant_row else vouchr_db.upsert_merchant(merchant_name)

    total_saves = vouchr_db.query_one(
        """
        SELECT COUNT(*) AS c
        FROM saved_vouchers sv
        JOIN vouchers v ON sv.voucher_id = v.id
        WHERE v.merchant_id = ?
        """,
        (merchant_id,)
    )
    total_redemptions = vouchr_db.query_one(
        "SELECT COALESCE(SUM(redeemed_count), 0) AS c FROM vouchers WHERE merchant_id = ?",
        (merchant_id,)
    )
    active_promos = vouchr_db.query_one(
        "SELECT COUNT(*) AS c FROM vouchers WHERE merchant_id = ? AND status = 'active'",
        (merchant_id,)
    )

    saves_count = int(total_saves["c"] if total_saves else 0)
    redemptions_count = int(total_redemptions["c"] if total_redemptions else 0)
    active_count = int(active_promos["c"] if active_promos else 0)
    views_count = max((saves_count * 9) + (active_count * 160) + (redemptions_count * 14), saves_count, redemptions_count)

    return jsonify({
        "success": True,
        "views": views_count,
        "saves": saves_count,
        "redemptions": redemptions_count
    })

@app.route("/api/qr/<path:data>")
def generate_qr(data):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    return send_file(buf, mimetype='image/png')

@app.route("/dismiss-notification/<string:voucher_title>", methods=["POST"])
def dismiss_notification(voucher_title):
    merchant_name = session.get("merchant_name")
    if not merchant_name: 
        return '', 401  # Unauthorized

    csv_filepath = get_merchant_csv_path(merchant_name)
    if not csv_filepath.exists():
        return '', 404

    updated_rows = []
    fieldnames = None

    with open(csv_filepath, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or ["VoucherTitle", "Status", "Redeemed", "Total", "ImageUrl", "Dismissed"]
        
        for row in reader:
            # Make sure Dismissed column exists
            if 'Dismissed' not in row:
                row['Dismissed'] = 'False'
            
            if str(row.get('VoucherTitle')).strip() == voucher_title:
                row['Dismissed'] = 'True'   # Mark as dismissed
            updated_rows.append(row)

    # Rewrite CSV with updated data
    with open(csv_filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    return '', 204  # Success, no content
def auto_update_voucher_statuses(merchant_name):
    """
    Scans the merchant's CSV. If Redeemed >= Total, it forces the Status to 'Inactive'.
    Now safely preserves the 'Dismissed' column.
    """
    csv_filepath = get_merchant_csv_path(merchant_name)
    if not csv_filepath.exists():
        return

    updated_rows = []
    status_changed = False
    fieldnames = None

    with open(csv_filepath, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        
        # Make sure Dismissed column exists
        if fieldnames and 'Dismissed' not in fieldnames:
            fieldnames = list(fieldnames) + ['Dismissed']

        for row in reader:
            try:
                redeemed = int(row.get('Redeemed', 0))
                total = int(row.get('Total', 1))
                current_status = row.get('Status', 'Active')

                # Auto-switch to Inactive if fully redeemed
                if redeemed >= total and current_status.lower() == 'active':
                    row['Status'] = 'Inactive'
                    status_changed = True

                # Ensure Dismissed field exists
                if 'Dismissed' not in row:
                    row['Dismissed'] = 'False'

            except ValueError:
                pass

            updated_rows.append(row)

    # Rewrite CSV with proper structure
    if fieldnames:
        with open(csv_filepath, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(updated_rows)


@app.route("/update-voucher/<string:voucher_title>", methods=["POST"])
def update_voucher(voucher_title):
    merchant_name = session.get("merchant_name")
    if not merchant_name:
        return redirect("/auth.html")

    csv_filepath = get_merchant_csv_path(merchant_name)
    if not csv_filepath.exists():
        return redirect("/merchant-main-menu")

    raw_total = str(request.form.get("total_supply", "")).strip()
    raw_expiry = str(request.form.get("expiry_date", "")).strip()

    try:
        total_supply = max(1, int(float(raw_total)))
    except (TypeError, ValueError):
        return redirect("/merchant-main-menu")

    if raw_expiry:
        try:
            datetime.strptime(raw_expiry, "%Y-%m-%d")
        except ValueError:
            raw_expiry = ""

    updated_rows = []
    fieldnames = []
    matched_row = None

    with open(csv_filepath, "r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file, skipinitialspace=True)
        fieldnames = list(reader.fieldnames or [])
        for required_field in ["VoucherTitle", "Status", "Redeemed", "Total", "ExpiryDate", "Address", "ImageUrl", "Dismissed"]:
            if required_field not in fieldnames:
                fieldnames.append(required_field)

        for row in reader:
            if str(row.get("VoucherTitle", "")).strip() == voucher_title:
                try:
                    redeemed = int(row.get("Redeemed") or 0)
                except ValueError:
                    redeemed = 0

                if total_supply < max(1, redeemed):
                    total_supply = max(1, redeemed)

                row["Total"] = str(total_supply)
                row["ExpiryDate"] = raw_expiry
                row["Dismissed"] = "False"

                # Keep the status synced after editing. Expired dates or fully redeemed vouchers become inactive.
                new_status = "Active"
                if raw_expiry:
                    try:
                        if datetime.strptime(raw_expiry, "%Y-%m-%d").date() < datetime.now().date():
                            new_status = "Inactive"
                    except ValueError:
                        pass
                if total_supply <= 0 or redeemed >= total_supply:
                    new_status = "Inactive"
                row["Status"] = new_status
                matched_row = dict(row)

            updated_rows.append(row)

    with open(csv_filepath, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(updated_rows)

    if matched_row:
        # Also keep the SQLite voucher table aligned so user-side voucher data updates immediately.
        created_voucher = build_voucher_object(matched_row, merchant_name)
        vouchr_db.upsert_voucher(merchant_name, {
            "id": created_voucher["id"],
            "VoucherTitle": matched_row.get("VoucherTitle", voucher_title),
            "Status": matched_row.get("Status", "Active"),
            "Redeemed": matched_row.get("Redeemed", 0),
            "Total": matched_row.get("Total", total_supply),
            "ExpiryDate": matched_row.get("ExpiryDate", raw_expiry),
            "Address": matched_row.get("Address", get_merchant_address(merchant_name)),
            "ImageUrl": matched_row.get("ImageUrl", "/assets/default-logo.png")
        }, log_activity=True)

    return redirect("/merchant-main-menu")

@app.route("/delete-voucher/<string:voucher_title>", methods=["POST"])
def delete_voucher(voucher_title):
    merchant_name = session.get("merchant_name")
    if not merchant_name: 
        return redirect("/auth.html")

    csv_filepath = get_merchant_csv_path(merchant_name)
    
    if csv_filepath.exists():
        updated_rows = []
        fieldnames = []
        
        with open(csv_filepath, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            fieldnames = reader.fieldnames
            for row in reader:
                # If this is NOT the voucher we are deleting, save it back to the list
                if str(row.get('VoucherTitle')).strip() != voucher_title:
                    updated_rows.append(row)
                else:
                    # --- NEW: Delete the physical image file ---
                    # We found the voucher to delete! Let's check its image URL.
                    image_url = str(row.get('ImageUrl', '')).strip()
                    
                    # Only delete if it's a local file in the assets folder 
                    # (We skip this if it's an external Pollinations AI link)
                    if image_url.startswith('/assets/'):
                        # Extract just the filename (e.g., "1716335123_pizza.jpg")
                        filename = image_url.split('/assets/')[-1]
                        file_path = ASSETS_DIR / filename
                        
                        try:
                            # If the file exists on the hard drive, delete it
                            if file_path.exists():
                                file_path.unlink()
                                print(f"Successfully deleted unused image: {filename}")
                        except Exception as e:
                            print(f"Warning: Could not delete image file {filename}. Error: {e}")
                    # -------------------------------------------
        
        if fieldnames:
            with open(csv_filepath, 'w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(updated_rows)
                
    return redirect("/merchant-main-menu")

@app.route("/create", methods=["GET", "POST"])
def create_voucher():
    merchant_name = session.get("merchant_name")
    if not merchant_name: return redirect("/auth.html")

    if request.method == 'POST':
        title = request.form.get('title')
        supply = request.form.get('supply')
        expiration = request.form.get('expiration')
        image_url = request.form.get('image_url', '')
        address=get_merchant_address(merchant_name)
        
        uploaded_file = request.files.get('voucher_image')
        if uploaded_file and uploaded_file.filename != '':
            clean_name = secure_filename(uploaded_file.filename)
            unique_filename = f"{int(datetime.now().timestamp())}_{clean_name}"
            file_path = ASSETS_DIR / unique_filename
            uploaded_file.save(file_path)
            image_url = f"/assets/{unique_filename}"

        csv_filepath = get_merchant_csv_path(merchant_name)
        voucher_fieldnames = ["VoucherTitle", "Status", "Redeemed", "Total", "ExpiryDate", "Address", "ImageUrl", "Dismissed"]
        file_already_existed = csv_filepath.exists()

        if file_already_existed:
            existing_rows = []
            existing_fieldnames = []
            with csv_filepath.open('r', newline='', encoding='utf-8-sig') as existing_file:
                reader = csv.DictReader(existing_file)
                existing_fieldnames = reader.fieldnames or []
                existing_rows = list(reader)

            # Older merchant CSV files did not have Dismissed. Normalize the file once
            # so future writes and reads always stay aligned with the header.
            if existing_fieldnames != voucher_fieldnames:
                with csv_filepath.open('w', newline='', encoding='utf-8') as fixed_file:
                    writer = csv.DictWriter(fixed_file, fieldnames=voucher_fieldnames)
                    writer.writeheader()
                    for row in existing_rows:
                        writer.writerow({
                            "VoucherTitle": row.get("VoucherTitle", ""),
                            "Status": row.get("Status", "Active"),
                            "Redeemed": row.get("Redeemed", 0),
                            "Total": row.get("Total", 0),
                            "ExpiryDate": row.get("ExpiryDate", ""),
                            "Address": row.get("Address", address),
                            "ImageUrl": row.get("ImageUrl", "/assets/default-logo.png"),
                            "Dismissed": row.get("Dismissed", "False")
                        })

        with csv_filepath.open(mode='a', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=voucher_fieldnames)
            if not file_already_existed:
                writer.writeheader()
            writer.writerow({
                "VoucherTitle": title,
                "Status": "Active",
                "Redeemed": 0,
                "Total": supply,
                "ExpiryDate": expiration,
                "Address": address,
                "ImageUrl": image_url or "/assets/default-logo.png",
                "Dismissed": "False"
            })

        created_voucher = build_voucher_object({
            "VoucherTitle": title,
            "Status": "Active",
            "Redeemed": 0,
            "Total": supply,
            "ExpiryDate": expiration,
            "Address": address,
            "ImageUrl": image_url or "/assets/default-logo.png"
        }, merchant_name)
        vouchr_db.upsert_voucher(merchant_name, {
            "id": created_voucher["id"],
            "VoucherTitle": title,
            "Status": "Active",
            "Redeemed": 0,
            "Total": supply,
            "ExpiryDate": expiration,
            "Address": address,
            "ImageUrl": image_url or "/assets/default-logo.png"
        }, log_activity=True)

        create_notification({
            "id": f"merchant_{created_voucher['id']}_{int(datetime.now().timestamp())}",
            "type": "merchant",
            "icon": "🎟",
            "title": "New voucher available",
            "message": f"{merchant_name} added {title}.",
            "voucher_id": created_voucher["id"],
            "merchant_id": created_voucher["merchant_id"]
        })

        return redirect(url_for('merchant_main_menu'))

    return render_template('create_voucher.html')

def get_merchant_address(merchant_name):
    """Helper to find the address from merchants.csv"""
    if Merchant_File.exists():
        with Merchant_File.open("r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row.get("name") == merchant_name:
                    return row.get("address", "No address provided")
    return "No address provided"

@app.route("/api/generate-ai", methods=["POST"])
def generate_ai():
    if not session.get("merchant_name"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    idea = data.get("idea", "")

    if not idea:
        return jsonify({"error": "No idea provided"}), 400

    try:
        api_key = get_gemini_api_key()
        if not api_key:
            return jsonify({"error": "GEMINI_API_KEY is missing"}), 503

        genai.configure(api_key=api_key)
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        if not available_models:
            return jsonify({"error": "Your API key has no access to generate text."}), 500
            
        chosen_model_name = available_models[0]
        for name in available_models:
            if 'flash' in name:
                chosen_model_name = name
                break
            elif 'pro' in name:
                chosen_model_name = name

        print(f"\n--- SUCCESS: Connected to Google AI using model: {chosen_model_name} ---\n")
        
        dynamic_model = genai.GenerativeModel(chosen_model_name)

        prompt = f"""
        I am a restaurant/food merchant creating a discount voucher based on this idea: '{idea}'. 
        
        Return EXACTLY in this format. DO NOT use markdown, asterisks, or bold tags:
        Title: [Catchy Food Title, max 5 words]
        Terms: [1 short sentence of Terms & Conditions]
        ImagePrompt: [A highly detailed, 15-word visual description of ONLY the exact food item. DO NOT mention vouchers, discounts, numbers, or text.]
        """

        response = dynamic_model.generate_content(prompt)
        text = response.text
        
        text = text.replace("**", "").replace("*", "")
        
        title_match = re.search(r"Title:\s*(.*)", text, re.IGNORECASE)
        terms_match = re.search(r"Terms:\s*(.*)", text, re.IGNORECASE)
        image_match = re.search(r"ImagePrompt:\s*(.*)", text, re.IGNORECASE | re.DOTALL)
        
        if not title_match or not terms_match or not image_match:
            return jsonify({"error": "AI returned unexpected formatting. Try again."}), 500

        return jsonify({
            "title": title_match.group(1).strip(),
            "terms": terms_match.group(1).strip(),
            "image_prompt": image_match.group(1).strip()
        })
        
    except Exception as e:
        error_msg = str(e)
        if "API_KEY_INVALID" in error_msg or "PermissionDenied" in error_msg:
            return jsonify({"error": "Your Google API Key is invalid or expired!"}), 500
        return jsonify({"error": f"AI Error: {error_msg}"}), 500
    
@app.route("/merchant-profile", methods=["GET", "POST"])
def merchant_profile():
    merchant_name = session.get("merchant_name")
    if not merchant_name:
        return redirect("/auth.html")

    merchant_record = None
    merchants = read_merchants()
    for merchant in merchants:
        if str(merchant.get("name", "")).strip() == merchant_name:
            merchant_record = merchant
            break

    if merchant_record is None:
        return redirect("/auth.html")

    if request.method == "POST":
        form_action = request.form.get("form_action", "password").strip()

        # ---------------------------
        # Update password
        # ---------------------------
        if form_action == "password":
            new_password = request.form.get("new_password", "").strip()

            if new_password:
                temp_file = tempfile.NamedTemporaryFile(mode="w", delete=False, newline="", encoding="utf-8")
                password_updated = False

                try:
                    with open(Merchant_File, "r", encoding="utf-8-sig", newline="") as file, temp_file:
                        reader = csv.DictReader(file)
                        fieldnames = reader.fieldnames or CSV_FIELDS
                        writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                        writer.writeheader()

                        for row in reader:
                            if str(row.get("name", "")).strip() == merchant_name:
                                row["password"] = new_password
                                password_updated = True
                            writer.writerow(row)

                    shutil.move(temp_file.name, Merchant_File)

                    if password_updated:
                        return redirect("/merchant-profile?success=1")
                    return redirect("/merchant-profile?error=1")

                except Exception as error:
                    print(f"Password update error: {error}")
                    try:
                        os.unlink(temp_file.name)
                    except Exception:
                        pass
                    return redirect("/merchant-profile?error=1")

        # ---------------------------
        # Update merchant profile
        # ---------------------------
        if form_action == "profile":
            new_name = request.form.get("merchant_name", "").strip()
            new_email = request.form.get("merchant_email", "").strip().lower()
            new_address = request.form.get("merchant_address", "").strip()

            if not new_name or not new_email or not new_address:
                return redirect("/merchant-profile?profile_error=missing")

            if not is_valid_email(new_email):
                return redirect("/merchant-profile?profile_error=email")

            temp_file = tempfile.NamedTemporaryFile(mode="w", delete=False, newline="", encoding="utf-8")
            old_name = merchant_name
            old_email = str(merchant_record.get("email", "")).strip().lower()
            profile_updated = False

            try:
                with open(Merchant_File, "r", encoding="utf-8-sig", newline="") as file, temp_file:
                    reader = csv.DictReader(file)
                    fieldnames = reader.fieldnames or CSV_FIELDS
                    writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                    writer.writeheader()

                    for row in reader:
                        row_name = str(row.get("name", "")).strip()
                        row_email = str(row.get("email", "")).strip().lower()

                        # Prevent duplicate email on another merchant account.
                        if row_name != old_name and row_email == new_email:
                            try:
                                os.unlink(temp_file.name)
                            except Exception:
                                pass
                            return redirect("/merchant-profile?profile_error=duplicate_email")

                        if row_name == old_name:
                            row["name"] = new_name
                            row["email"] = new_email
                            row["address"] = new_address
                            profile_updated = True

                        writer.writerow(row)

                shutil.move(temp_file.name, Merchant_File)

                # Keep merchant session aligned with the new name.
                if profile_updated:
                    session["merchant_name"] = new_name

                    # Rename the merchant voucher CSV if it exists, so created vouchers stay linked.
                    old_voucher_csv = get_merchant_csv_path(old_name)
                    new_voucher_csv = get_merchant_csv_path(new_name)
                    if old_name != new_name and old_voucher_csv.exists() and not new_voucher_csv.exists():
                        old_voucher_csv.rename(new_voucher_csv)

                    # Save/replace merchant picture using the same naming style used during signup.
                    uploaded_file = request.files.get("merchant_image")
                    if uploaded_file and uploaded_file.filename:
                        safe_merchant_name = new_name.replace(" ", "_")
                        image_path = ASSETS_DIR / f"{safe_merchant_name}.jpg"
                        uploaded_file.save(image_path)

                        # Remove old image when name changed, if it is different.
                        old_image_path = ASSETS_DIR / f"{old_name.replace(' ', '_')}.jpg"
                        if old_image_path != image_path and old_image_path.exists():
                            try:
                                old_image_path.unlink()
                            except Exception:
                                pass

                    return redirect("/merchant-profile?profile_success=1")

                return redirect("/merchant-profile?profile_error=1")

            except Exception as error:
                print(f"Merchant profile update error: {error}")
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass
                return redirect("/merchant-profile?profile_error=1")

    return render_template(
        "merchant_profile.html",
        merchant_name=merchant_record.get("name", merchant_name),
        merchant_email=merchant_record.get("email", ""),
        merchant_address=merchant_record.get("address", "")
    )

@app.route("/signout", methods=["GET", "POST"])
def signout():
    session.clear()
    return redirect("/auth.html")

if __name__ == "__main__":
    ensure_notifications_csv()
    ensure_budget_settings_csv()
    ensure_budget_csv()
    ensure_base_csv_exists()
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
