import csv
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CSV_DIR = BASE_DIR / "CSV"
USER_CSV_DIR = CSV_DIR / "user"
MERCHANT_CSV_DIR = CSV_DIR / "merchant"

USERS_CSV = USER_CSV_DIR / "users.csv"
MERCHANTS_CSV = MERCHANT_CSV_DIR / "merchants.csv"
NOTIFICATIONS_CSV = USER_CSV_DIR / "notifications.csv"
FEEDBACK_CSV = USER_CSV_DIR / "feedback.csv"
BUDGET_CSV = USER_CSV_DIR / "budget.csv"
BUDGET_SETTINGS_CSV = USER_CSV_DIR / "budget_settings.csv"

DB_PATH = BASE_DIR / "vouchr.db"


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def slugify(value):
    import re

    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "item"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query_all(sql, params=()):
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def query_one(sql, params=()):
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql, params=()):
    with connect() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def ensure_column(conn, table, column, definition):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_schema_updates(conn):
    ensure_column(conn, "vouchers", "risk_status", "TEXT NOT NULL DEFAULT 'normal'")
    ensure_column(conn, "vouchers", "risk_level", "TEXT NOT NULL DEFAULT 'none'")
    ensure_column(conn, "vouchers", "risk_reason", "TEXT")
    ensure_column(conn, "vouchers", "risk_confidence", "REAL DEFAULT 0")
    ensure_column(conn, "support_tickets", "merchant_id", "INTEGER")
    ensure_column(conn, "announcements", "updated_at", "TEXT")
    conn.execute(
        """
        UPDATE announcements
        SET updated_at = COALESCE(NULLIF(updated_at, ''), created_at, ?)
        WHERE updated_at IS NULL OR updated_at = ''
        """,
        (now_text(),),
    )
    conn.execute(
        """
        UPDATE announcements
        SET scheduled_at = replace(scheduled_at, 'T', ' ')
        WHERE scheduled_at LIKE '%T%'
        """
    )


def init_db(sync_csv=True):
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                csv_id TEXT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT,
                role TEXT NOT NULL DEFAULT 'customer',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS merchants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                csv_id TEXT,
                business_name TEXT NOT NULL,
                category TEXT DEFAULT 'Food',
                contact_email TEXT,
                contact_phone TEXT,
                address TEXT,
                partner_since TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS vouchers (
                id TEXT PRIMARY KEY,
                merchant_id INTEGER,
                merchant_name TEXT,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT DEFAULT 'Restaurants',
                discount_type TEXT DEFAULT 'deal',
                discount_value TEXT,
                start_date TEXT,
                expiry_date TEXT,
                image_url TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                risk_status TEXT NOT NULL DEFAULT 'normal',
                risk_level TEXT NOT NULL DEFAULT 'none',
                risk_reason TEXT,
                risk_confidence REAL DEFAULT 0,
                total_supply INTEGER DEFAULT 0,
                redeemed_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(merchant_id) REFERENCES merchants(id)
            );

            CREATE TABLE IF NOT EXISTS saved_vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                voucher_id TEXT,
                saved_at TEXT NOT NULL,
                UNIQUE(user_id, voucher_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(voucher_id) REFERENCES vouchers(id)
            );

            CREATE TABLE IF NOT EXISTS voucher_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                voucher_id TEXT,
                merchant_id INTEGER,
                qr_code TEXT,
                redemption_code TEXT,
                redeemed_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'generated',
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(voucher_id) REFERENCES vouchers(id),
                FOREIGN KEY(merchant_id) REFERENCES merchants(id)
            );

            CREATE TABLE IF NOT EXISTS voucher_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                voucher_id TEXT,
                viewed_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(voucher_id) REFERENCES vouchers(id)
            );

            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                subject TEXT NOT NULL,
                issue_type TEXT NOT NULL DEFAULT 'other',
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'new',
                merchant_id INTEGER,
                assigned_admin_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(merchant_id) REFERENCES merchants(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS ticket_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                sender_id INTEGER,
                sender_role TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(ticket_id) REFERENCES support_tickets(id)
            );

            CREATE TABLE IF NOT EXISTS live_support_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                assigned_admin_id INTEGER,
                status TEXT NOT NULL DEFAULT 'waiting',
                subject TEXT NOT NULL DEFAULT 'Live Support',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ended_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(assigned_admin_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS live_support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                sender_id INTEGER,
                sender_role TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                read_at TEXT,
                FOREIGN KEY(session_id) REFERENCES live_support_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS agent_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'online',
                last_seen_at TEXT NOT NULL,
                FOREIGN KEY(admin_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                audience TEXT NOT NULL DEFAULT 'all_users',
                status TEXT NOT NULL DEFAULT 'draft',
                scheduled_at TEXT,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY(created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS announcement_reads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                announcement_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                read_at TEXT NOT NULL,
                UNIQUE(announcement_id, user_id),
                FOREIGN KEY(announcement_id) REFERENCES announcements(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS merchant_activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER,
                actor_user_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                source_type TEXT,
                source_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(merchant_id) REFERENCES merchants(id),
                FOREIGN KEY(actor_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS ai_voucher_flags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_id TEXT UNIQUE NOT NULL,
                merchant_id INTEGER,
                risk_level TEXT NOT NULL,
                reason TEXT NOT NULL,
                confidence_score REAL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending_review',
                reviewed_by INTEGER,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(voucher_id) REFERENCES vouchers(id),
                FOREIGN KEY(merchant_id) REFERENCES merchants(id),
                FOREIGN KEY(reviewed_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                details TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(admin_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE NOT NULL,
                setting_value TEXT NOT NULL,
                updated_by INTEGER,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(updated_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS system_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_name TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                FOREIGN KEY(created_by) REFERENCES users(id)
            );
            """
        )
        ensure_schema_updates(conn)
        conn.execute(
            """
            UPDATE vouchers
            SET category = CASE lower(COALESCE(category, ''))
                WHEN 'merchant deal' THEN 'Restaurants'
                WHEN 'food & dining' THEN 'Restaurants'
                WHEN 'food' THEN 'Restaurants'
                WHEN 'retail' THEN 'Café'
                WHEN 'health & beauty' THEN 'Desserts'
                WHEN 'travel' THEN 'Beverages'
                WHEN 'entertainment' THEN 'Sushi'
                WHEN 'others' THEN 'Pizza'
                ELSE category
            END
            WHERE lower(COALESCE(category, '')) IN (
                'merchant deal', 'food & dining', 'food', 'retail',
                'health & beauty', 'travel', 'entertainment', 'others'
            )
            """
        )
        conn.commit()

    seed_admin()
    seed_demo_activity()
    if sync_csv:
        sync_from_csv()


def seed_admin():
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO users (name, email, password, role, status, created_at)
            VALUES (?, ?, ?, 'admin', 'active', ?)
            ON CONFLICT(email) DO UPDATE SET
                name = excluded.name,
                password = excluded.password,
                role = 'admin',
                status = 'active'
            """,
            ("Master Admin", "admin@vouchr.com", "admin123", now_text()),
        )
        conn.commit()


def read_csv(path):
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def ensure_csv_folders():
    """Create the final CSV folder layout used by the user and merchant apps."""
    CSV_DIR.mkdir(exist_ok=True)
    USER_CSV_DIR.mkdir(exist_ok=True)
    MERCHANT_CSV_DIR.mkdir(exist_ok=True)


def normalize_csv_filename(value):
    import re

    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def merchant_csv_candidates(merchant_name):
    merchant_name = str(merchant_name or "").strip()
    if not merchant_name:
        return []
    safe_exact = merchant_name.replace("/", "_").replace("\\", "_")
    return [
        MERCHANT_CSV_DIR / f"{safe_exact}.csv",
        MERCHANT_CSV_DIR / f"{safe_exact.replace(' ', '_')}.csv",
        MERCHANT_CSV_DIR / f"{slugify(safe_exact)}.csv",
    ]


def get_merchant_csv_path(merchant_name):
    """Return the merchant voucher CSV path inside CSV/merchant/.

    The app should save new merchant voucher files using the readable exact
    business name, e.g. CSV/merchant/Ayam Gepuk Albert.csv. For reading, this
    also supports older underscore/slug filenames so existing vouchers do not
    disappear after the folder restructure.
    """
    ensure_csv_folders()
    merchant_name = str(merchant_name or "").strip()
    if not merchant_name:
        return MERCHANT_CSV_DIR / "merchant.csv"

    for candidate in merchant_csv_candidates(merchant_name):
        if candidate.exists():
            return candidate

    wanted = normalize_csv_filename(merchant_name)
    for csv_file in MERCHANT_CSV_DIR.glob("*.csv"):
        if csv_file.name.lower() == "merchants.csv":
            continue
        if normalize_csv_filename(csv_file.stem) == wanted:
            return csv_file

    # New files should be created using the exact business name with spaces.
    return MERCHANT_CSV_DIR / f"{merchant_name.replace('/', '_').replace('\\', '_')}.csv"


def migrate_legacy_csv_files():
    """Move/merge old flat CSV files into CSV/user and CSV/merchant.

    This keeps old project data usable while making the new folder placement the
    single source of truth afterwards.
    """
    ensure_csv_folders()

    def move_if_needed(old_path, new_path):
        if old_path.exists() and not new_path.exists():
            new_path.parent.mkdir(exist_ok=True)
            shutil.move(str(old_path), str(new_path))

    move_if_needed(CSV_DIR / "users.csv", USERS_CSV)
    move_if_needed(CSV_DIR / "user.csv", USERS_CSV)
    move_if_needed(CSV_DIR / "merchants.csv", MERCHANTS_CSV)
    move_if_needed(CSV_DIR / "notifications.csv", NOTIFICATIONS_CSV)
    move_if_needed(CSV_DIR / "feedback.csv", FEEDBACK_CSV)
    move_if_needed(CSV_DIR / "budget.csv", BUDGET_CSV)
    move_if_needed(CSV_DIR / "budget_settings.csv", BUDGET_SETTINGS_CSV)

    # Move old per-merchant voucher CSVs from CSV/{merchant}.csv to CSV/merchant/{merchant}.csv.
    reserved = {
        "users.csv", "user.csv", "merchants.csv", "notifications.csv",
        "feedback.csv", "budget.csv", "budget_settings.csv",
    }
    for old_csv in CSV_DIR.glob("*.csv"):
        if old_csv.name.lower() in reserved:
            continue
        target = MERCHANT_CSV_DIR / old_csv.name
        if not target.exists():
            shutil.move(str(old_csv), str(target))


def upsert_user(name, email, password="", role="customer", csv_id=None, created_at=None, status="active"):
    email = str(email or "").strip().lower()
    name = str(name or email or "User").strip()
    if not email:
        email = f"{slugify(name)}@demo.local"
    created_at = created_at or now_text()
    db_role = "customer" if role == "user" else role

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO users (csv_id, name, email, password, role, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                csv_id = COALESCE(excluded.csv_id, users.csv_id),
                name = excluded.name,
                password = COALESCE(NULLIF(excluded.password, ''), users.password),
                role = excluded.role,
                status = excluded.status
            """,
            (csv_id, name, email, password or "", db_role, status, created_at),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        return row["id"]


def touch_login(email):
    execute("UPDATE users SET last_login_at = ? WHERE lower(email) = lower(?)", (now_text(), email))


def upsert_merchant(business_name, email="", password="", address="", csv_id=None, created_at=None, status="active", category="Food"):
    login_email = email or f"{slugify(business_name)}@merchant.local"
    existing_user = query_one("SELECT id, role FROM users WHERE lower(email) = lower(?)", (login_email,))
    if existing_user and existing_user.get("role") not in {"merchant", "admin"}:
        login_email = f"{slugify(business_name)}@merchant.local"

    user_id = upsert_user(business_name, login_email, password, "merchant", csv_id, created_at, status)
    partner_since = created_at or now_text()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM merchants WHERE lower(business_name) = lower(?)",
            (business_name,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE merchants
                SET user_id = ?, csv_id = ?, contact_email = ?, address = ?, status = ?, category = ?
                WHERE id = ?
                """,
                (user_id, csv_id, email, address, status, category, existing["id"]),
            )
            merchant_id = existing["id"]
        else:
            cur = conn.execute(
                """
                INSERT INTO merchants (user_id, csv_id, business_name, category, contact_email, address, partner_since, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, csv_id, business_name, category, email, address, partner_since, status, created_at or now_text()),
            )
            merchant_id = cur.lastrowid
        conn.commit()
        return merchant_id


def extract_offer(title):
    import re

    title = str(title or "Special Deal")
    percent = re.search(r"\d+\s*%\s*(?:off)?", title, re.I)
    if percent:
        return percent.group(0).upper()
    rm = re.search(r"RM\s*\d+(?:\.\d{1,2})?", title, re.I)
    if rm:
        return rm.group(0).upper()
    return "Special Deal"


def normalize_status(status, expiry_date=None):
    text = str(status or "active").strip().lower()
    if text in {"inactive", "rejected", "pending", "hidden", "removed"}:
        return text
    if expiry_date:
        try:
            if datetime.strptime(str(expiry_date)[:10], "%Y-%m-%d").date() < datetime.now().date():
                return "expired"
        except ValueError:
            pass
    return "active"


def assess_voucher_risk(voucher):
    import re

    title = str(voucher.get("title") or voucher.get("VoucherTitle") or "")
    description = str(voucher.get("description") or "")
    discount = str(voucher.get("discount_value") or voucher.get("Discount") or "")
    expiry = str(voucher.get("expiry_date") or voucher.get("ExpiryDate") or "")
    text = f"{title} {description} {discount}".lower()
    reasons = []
    score = 0
    level = "none"

    percentages = [int(match) for match in re.findall(r"(\d{1,3})\s*%", text)]
    if any(percent >= 90 for percent in percentages):
        reasons.append("Unrealistic discount")
        score += 55
        level = "high"
    elif any(percent >= 75 for percent in percentages):
        reasons.append("Very high discount")
        score += 30
        level = "medium"

    if re.search(r"\brm\s*0\b|\b0\s*rm\b|\bfree\b.*\bunlimited\b|\bunlimited\b.*\bfree\b", text):
        reasons.append("Free or RM0 unlimited offer")
        score += 45
        level = "high" if score >= 55 else "medium"

    banned_patterns = [
        ("claim now or lose money", "Fake urgency wording"),
        ("guaranteed profit", "Scam-like wording"),
        ("bank login", "Restricted financial wording"),
        ("password", "Sensitive information wording"),
        ("whatsapp", "External contact wording"),
        ("http://", "Suspicious external link"),
        ("https://", "Suspicious external link"),
        ("bit.ly", "Shortened external link"),
    ]
    for pattern, reason in banned_patterns:
        if pattern in text:
            reasons.append(reason)
            score += 24
            if score >= 55:
                level = "high"
            elif level == "none":
                level = "medium"

    if "minimum spend" in text and "free" in text:
        amounts = [int(amount) for amount in re.findall(r"rm\s*(\d+)", text)]
        if any(amount >= 100 for amount in amounts):
            reasons.append("Free wording with high minimum spend")
            score += 28
            if level == "none":
                level = "medium"

    if expiry:
        try:
            if datetime.strptime(expiry[:10], "%Y-%m-%d").date() < datetime.now().date():
                reasons.append("Expiry date already passed")
                score += 22
                if level == "none":
                    level = "medium"
        except ValueError:
            pass

    if not reasons:
        return {
            "is_flagged": False,
            "risk_level": "none",
            "reason": "",
            "confidence_score": 0,
        }

    if score >= 55:
        level = "high"
    elif score >= 25 and level == "none":
        level = "medium"
    elif level == "none":
        level = "low"

    return {
        "is_flagged": True,
        "risk_level": level,
        "reason": "; ".join(dict.fromkeys(reasons)),
        "confidence_score": min(98, max(50, score)),
    }


def apply_voucher_risk(conn, voucher_id, merchant_id, risk, current_status="active"):
    now = now_text()
    if risk["is_flagged"]:
        existing_flag = conn.execute(
            "SELECT status FROM ai_voucher_flags WHERE voucher_id = ?",
            (voucher_id,),
        ).fetchone()
        existing_status = existing_flag["status"] if existing_flag else ""
        if existing_status in {"hidden", "removed"}:
            next_status = existing_status
        elif risk["risk_level"] == "high" and existing_status not in {"allowed", "reviewed"} and current_status not in {"removed", "expired"}:
            next_status = "hidden"
        else:
            next_status = current_status
        conn.execute(
            """
            UPDATE vouchers
            SET risk_status = 'flagged',
                risk_level = ?,
                risk_reason = ?,
                risk_confidence = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                risk["risk_level"],
                risk["reason"],
                risk["confidence_score"],
                next_status,
                now,
                voucher_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_voucher_flags (
                voucher_id, merchant_id, risk_level, reason, confidence_score,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending_review', ?, ?)
            ON CONFLICT(voucher_id) DO UPDATE SET
                merchant_id = excluded.merchant_id,
                risk_level = excluded.risk_level,
                reason = excluded.reason,
                confidence_score = excluded.confidence_score,
                status = CASE
                    WHEN ai_voucher_flags.status IN ('allowed', 'removed', 'hidden', 'reviewed') THEN ai_voucher_flags.status
                    ELSE 'pending_review'
                END,
                updated_at = excluded.updated_at
            """,
            (
                voucher_id,
                merchant_id,
                risk["risk_level"],
                risk["reason"],
                risk["confidence_score"],
                now,
                now,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE vouchers
            SET risk_status = 'normal',
                risk_level = 'none',
                risk_reason = '',
                risk_confidence = 0
            WHERE id = ? AND status != 'removed'
            """,
            (voucher_id,),
        )


def log_merchant_activity(merchant_id, actor_user_id, action, details="", source_type="", source_id="", created_at=None):
    if not merchant_id:
        return None
    return execute(
        """
        INSERT INTO merchant_activity_logs (
            merchant_id, actor_user_id, action, details, source_type, source_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (merchant_id, actor_user_id, action, details, source_type, str(source_id or ""), created_at or now_text()),
    )


def flag_voucher_for_review(voucher_id, merchant_id, risk_level, reason, confidence_score=75, auto_hide=False):
    now = now_text()
    status = "hidden" if auto_hide else None
    with connect() as conn:
        if status:
            conn.execute(
                """
                UPDATE vouchers
                SET status = ?, risk_status = 'flagged', risk_level = ?, risk_reason = ?,
                    risk_confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, risk_level, reason, confidence_score, now, voucher_id),
            )
        else:
            conn.execute(
                """
                UPDATE vouchers
                SET risk_status = 'flagged', risk_level = ?, risk_reason = ?,
                    risk_confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (risk_level, reason, confidence_score, now, voucher_id),
            )
        conn.execute(
            """
            INSERT INTO ai_voucher_flags (
                voucher_id, merchant_id, risk_level, reason, confidence_score,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending_review', ?, ?)
            ON CONFLICT(voucher_id) DO UPDATE SET
                merchant_id = excluded.merchant_id,
                risk_level = excluded.risk_level,
                reason = excluded.reason,
                confidence_score = excluded.confidence_score,
                status = CASE
                    WHEN ai_voucher_flags.status IN ('allowed', 'removed', 'hidden', 'reviewed') THEN ai_voucher_flags.status
                    ELSE 'pending_review'
                END,
                updated_at = excluded.updated_at
            """,
            (voucher_id, merchant_id, risk_level, reason, confidence_score, now, now),
        )
        conn.execute(
            """
            INSERT INTO merchant_activity_logs (
                merchant_id, actor_user_id, action, details, source_type, source_id, created_at
            )
            VALUES (?, NULL, 'Flagged Voucher', ?, 'ai_review', ?, ?)
            """,
            (merchant_id, reason, voucher_id, now),
        )
        conn.commit()


def upsert_voucher(merchant_name, row, force_status=None, log_activity=False):
    merchant = query_one("SELECT id FROM merchants WHERE lower(business_name) = lower(?)", (merchant_name,))
    merchant_id = merchant["id"] if merchant else upsert_merchant(merchant_name)
    merchant = query_one("SELECT * FROM merchants WHERE id = ?", (merchant_id,))
    title = str(row.get("VoucherTitle") or row.get("title") or "Special Offer").strip()
    expiry = str(row.get("ExpiryDate") or row.get("expiry_date") or "").strip()
    voucher_id = row.get("id") or f"{slugify(merchant_name)}-{slugify(title)}"
    status = force_status or normalize_status(row.get("Status"), expiry)
    total = int(float(row.get("Total") or row.get("total_supply") or 0))
    redeemed = int(float(row.get("Redeemed") or row.get("redeemed_count") or 0))
    image_url = row.get("ImageUrl") or row.get("image_url") or "/assets/default-logo.png"
    address = row.get("Address") or row.get("location") or "Selected outlets"
    created_at = row.get("created_at") or now_text()

    with connect() as conn:
        existing = conn.execute("SELECT id, status FROM vouchers WHERE id = ?", (voucher_id,)).fetchone()
        conn.execute(
            """
            INSERT INTO vouchers (
                id, merchant_id, merchant_name, title, description, category, discount_type,
                discount_value, start_date, expiry_date, image_url, status, total_supply,
                redeemed_count, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                merchant_id = excluded.merchant_id,
                merchant_name = excluded.merchant_name,
                title = excluded.title,
                description = excluded.description,
                category = excluded.category,
                discount_value = excluded.discount_value,
                expiry_date = excluded.expiry_date,
                image_url = excluded.image_url,
                status = excluded.status,
                total_supply = excluded.total_supply,
                redeemed_count = excluded.redeemed_count,
                updated_at = excluded.updated_at
            """,
            (
                voucher_id,
                merchant_id,
                merchant_name,
                title,
                f"Redeem this exclusive voucher from {merchant_name}: {title}.",
                row.get("category") or "Restaurants",
                row.get("discount_type") or "deal",
                row.get("discount_value") or extract_offer(title),
                row.get("start_date") or created_at[:10],
                expiry,
                image_url,
                status,
                total,
                redeemed,
                created_at,
                now_text(),
            ),
        )
        risk = assess_voucher_risk({
            "title": title,
            "description": row.get("description") or f"Redeem this exclusive voucher from {merchant_name}: {title}.",
            "discount_value": row.get("discount_value") or extract_offer(title),
            "expiry_date": expiry,
        })
        duplicate_count = conn.execute(
            "SELECT COUNT(*) AS c FROM vouchers WHERE merchant_id = ? AND lower(title) = lower(?)",
            (merchant_id, title),
        ).fetchone()["c"]
        day_ago = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        recent_count = conn.execute(
            "SELECT COUNT(*) AS c FROM vouchers WHERE merchant_id = ? AND created_at >= ?",
            (merchant_id, day_ago),
        ).fetchone()["c"]
        extra_reasons = []
        if duplicate_count > 1:
            extra_reasons.append("Duplicate voucher spam")
        if recent_count > 8:
            extra_reasons.append("Too many vouchers created in a short time")
        if extra_reasons:
            combined_reason = "; ".join([risk["reason"], *extra_reasons]).strip("; ")
            risk = {
                "is_flagged": True,
                "risk_level": "medium" if risk["risk_level"] in {"none", "low"} else risk["risk_level"],
                "reason": combined_reason,
                "confidence_score": max(risk["confidence_score"], 70),
            }
        current_status = status if status in {"active", "expired", "hidden", "removed"} else "active"
        apply_voucher_risk(conn, voucher_id, merchant_id, risk, current_status)
        if log_activity:
            action = "Flagged Voucher" if risk["is_flagged"] else ("Updated Voucher" if existing else "Created Voucher")
            details = f"{risk['reason']}: {title}" if risk["is_flagged"] else title
            conn.execute(
                """
                INSERT INTO merchant_activity_logs (
                    merchant_id, actor_user_id, action, details, source_type, source_id, created_at
                )
                VALUES (?, ?, ?, ?, 'voucher', ?, ?)
                """,
                (
                    merchant_id,
                    merchant.get("user_id") if merchant else None,
                    action,
                    details,
                    voucher_id,
                    now_text(),
                ),
            )
        conn.commit()
    return voucher_id


def sync_from_csv():
    # Final CSV structure:
    # CSV/user/users.csv, notifications.csv, feedback.csv, budget.csv, budget_settings.csv
    # CSV/merchant/merchants.csv and CSV/merchant/{merchant_name}.csv
    migrate_legacy_csv_files()

    for row in read_csv(USERS_CSV):
        upsert_user(
            row.get("name"),
            row.get("email"),
            row.get("password"),
            row.get("role") or "customer",
            row.get("id"),
            row.get("created_at"),
        )

    for row in read_csv(MERCHANTS_CSV):
        upsert_merchant(
            row.get("name") or row.get("business_name") or "Merchant",
            row.get("email"),
            row.get("password"),
            row.get("address"),
            row.get("id"),
            row.get("created_at"),
            row.get("status") or "active",
            row.get("category") or "Food",
        )

    merchants = query_all("SELECT business_name FROM merchants")
    for merchant in merchants:
        csv_path = get_merchant_csv_path(merchant["business_name"])
        for row in read_csv(csv_path):
            if str(row.get("Dismissed") or "").strip().lower() == "true":
                continue
            if row.get("VoucherTitle") or row.get("title"):
                upsert_voucher(merchant["business_name"], row)

    # Convert user feedback rows into support tickets for admin visibility.
    for row in read_csv(FEEDBACK_CSV):
        message = row.get("message") or ""
        if not message:
            continue
        user_id = ensure_user(row.get("user_name") or "User")
        existing = query_one(
            "SELECT id FROM support_tickets WHERE subject = ? AND user_id = ?",
            ("Imported feedback", user_id),
        )
        if not existing:
            ticket_id = create_support_ticket(
                user_id,
                "Imported feedback",
                row.get("category") or "other",
                message,
                "low",
                row.get("created_at") or now_text(),
            )
            add_audit(None, "import_feedback", "support_ticket", ticket_id, message[:120])


def ensure_user(name_or_email, email=None):
    email = email or (name_or_email if "@" in str(name_or_email) else f"{slugify(name_or_email)}@demo.local")
    if "@" not in str(name_or_email or ""):
        by_name = query_one("SELECT id FROM users WHERE lower(name) = lower(?) AND role = 'customer'", (str(name_or_email or "").strip(),))
        if by_name:
            return by_name["id"]
    user = query_one("SELECT id FROM users WHERE lower(email) = lower(?)", (email,))
    if user:
        return user["id"]
    return upsert_user(str(name_or_email or "User"), email, "", "customer")


def get_user_by_email_or_name(email=None, name=None):
    if email:
        user = query_one("SELECT * FROM users WHERE lower(email) = lower(?)", (email,))
        if user:
            return user
    if name:
        user = query_one("SELECT * FROM users WHERE lower(name) = lower(?)", (name,))
        if user:
            return user
    return None


def create_support_ticket(user_id, subject, issue_type, message, priority="medium", created_at=None, merchant_id=None):
    created_at = created_at or now_text()
    if merchant_id is None:
        user = query_one("SELECT id, role FROM users WHERE id = ?", (user_id,))
        if user and user.get("role") == "merchant":
            merchant = query_one("SELECT id FROM merchants WHERE user_id = ?", (user_id,))
            merchant_id = merchant["id"] if merchant else None
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO support_tickets (user_id, merchant_id, subject, issue_type, priority, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'new', ?, ?)
            """,
            (user_id, merchant_id, subject, issue_type, priority, created_at, created_at),
        )
        ticket_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO ticket_messages (ticket_id, sender_id, sender_role, message, created_at)
            VALUES (?, ?, 'customer', ?, ?)
            """,
            (ticket_id, user_id, message, created_at),
        )
        if merchant_id:
            conn.execute(
                """
                INSERT INTO merchant_activity_logs (
                    merchant_id, actor_user_id, action, details, source_type, source_id, created_at
                )
                VALUES (?, ?, 'Submitted Ticket', ?, 'ticket', ?, ?)
                """,
                (merchant_id, user_id, subject, ticket_id, created_at),
            )
        conn.commit()
        return ticket_id


def add_ticket_message(ticket_id, sender_id, sender_role, message):
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO ticket_messages (ticket_id, sender_id, sender_role, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticket_id, sender_id, sender_role, message, now_text()),
        )
        next_status = "replied" if sender_role == "admin" else "in_progress"
        conn.execute(
            "UPDATE support_tickets SET status = ?, updated_at = ? WHERE id = ?",
            (next_status, now_text(), ticket_id),
        )
        ticket = conn.execute("SELECT merchant_id, subject FROM support_tickets WHERE id = ?", (ticket_id,)).fetchone()
        if ticket and ticket["merchant_id"] and sender_role == "merchant":
            conn.execute(
                """
                INSERT INTO merchant_activity_logs (
                    merchant_id, actor_user_id, action, details, source_type, source_id, created_at
                )
                VALUES (?, ?, 'Replied to Ticket', ?, 'ticket', ?, ?)
                """,
                (ticket["merchant_id"], sender_id, ticket["subject"], ticket_id, now_text()),
            )
        conn.commit()


def list_support_tickets(user_id=None, issue_type=None, status=None):
    sql = """
        SELECT t.*, u.name AS user_name, u.email AS user_email,
               m.business_name AS merchant_name,
               a.name AS assigned_admin_name
        FROM support_tickets t
        LEFT JOIN users u ON u.id = t.user_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        LEFT JOIN users a ON a.id = t.assigned_admin_id
        WHERE 1=1
    """
    params = []
    if user_id:
        sql += " AND t.user_id = ?"
        params.append(user_id)
    if issue_type and issue_type != "all":
        sql += " AND t.issue_type = ?"
        params.append(issue_type)
    if status and status != "all":
        sql += " AND t.status = ?"
        params.append(status)
    sql += " ORDER BY t.updated_at DESC"
    return query_all(sql, params)


def get_ticket(ticket_id):
    ticket = query_one(
        """
        SELECT t.*, u.name AS user_name, u.email AS user_email,
               m.business_name AS merchant_name,
               a.name AS assigned_admin_name
        FROM support_tickets t
        LEFT JOIN users u ON u.id = t.user_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        LEFT JOIN users a ON a.id = t.assigned_admin_id
        WHERE t.id = ?
        """,
        (ticket_id,),
    )
    messages = query_all(
        """
        SELECT m.*, u.name AS sender_name
        FROM ticket_messages m
        LEFT JOIN users u ON u.id = m.sender_id
        WHERE m.ticket_id = ?
        ORDER BY m.created_at ASC
        """,
        (ticket_id,),
    )
    return ticket, messages


def update_ticket(ticket_id, status=None, assigned_admin_id=None):
    fields = []
    params = []
    if status:
        fields.append("status = ?")
        params.append(status)
    if assigned_admin_id:
        fields.append("assigned_admin_id = ?")
        params.append(assigned_admin_id)
    if not fields:
        return
    fields.append("updated_at = ?")
    params.append(now_text())
    params.append(ticket_id)
    execute(f"UPDATE support_tickets SET {', '.join(fields)} WHERE id = ?", params)


def set_agent_status(admin_id, status="online"):
    if not admin_id:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_status (admin_id, status, last_seen_at)
            VALUES (?, ?, ?)
            ON CONFLICT(admin_id) DO UPDATE SET
                status = excluded.status,
                last_seen_at = excluded.last_seen_at
            """,
            (admin_id, status, now_text()),
        )
        conn.commit()


def live_support_agent_available():
    cutoff = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    row = query_one(
        """
        SELECT COUNT(*) AS count
        FROM agent_status
        WHERE status IN ('online', 'busy')
          AND last_seen_at >= ?
        """,
        (cutoff,),
    )
    return int((row or {}).get("count") or 0) > 0


def get_live_support_session(session_id):
    return query_one(
        """
        SELECT s.*, u.name AS user_name, u.email AS user_email, a.name AS admin_name
        FROM live_support_sessions s
        LEFT JOIN users u ON u.id = s.user_id
        LEFT JOIN users a ON a.id = s.assigned_admin_id
        WHERE s.id = ?
        """,
        (session_id,),
    )


def get_active_live_support_session(user_id):
    if not user_id:
        return None
    return query_one(
        """
        SELECT s.*, u.name AS user_name, u.email AS user_email, a.name AS admin_name
        FROM live_support_sessions s
        LEFT JOIN users u ON u.id = s.user_id
        LEFT JOIN users a ON a.id = s.assigned_admin_id
        WHERE s.user_id = ?
          AND s.status IN ('waiting', 'active')
        ORDER BY s.updated_at DESC
        LIMIT 1
        """,
        (user_id,),
    )


def add_live_support_message(session_id, sender_id, sender_role, message):
    message = str(message or "").strip()
    if not session_id or not message:
        return None
    created_at = now_text()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO live_support_messages (session_id, sender_id, sender_role, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, sender_id, sender_role, message, created_at),
        )
        conn.execute(
            "UPDATE live_support_sessions SET updated_at = ? WHERE id = ?",
            (created_at, session_id),
        )
        conn.commit()
        return cur.lastrowid


def start_live_support_session(user_id, subject="Live Support"):
    existing = get_active_live_support_session(user_id)
    if existing:
        return existing
    created_at = now_text()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO live_support_sessions (user_id, status, subject, created_at, updated_at)
            VALUES (?, 'waiting', ?, ?, ?)
            """,
            (user_id, subject or "Live Support", created_at, created_at),
        )
        session_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO live_support_messages (session_id, sender_id, sender_role, message, created_at)
            VALUES (?, NULL, 'system', 'Live support request started.', ?)
            """,
            (session_id, created_at),
        )
        conn.commit()
    return get_live_support_session(session_id)


def get_live_support_messages(session_id):
    return query_all(
        """
        SELECT m.*, u.name AS sender_name
        FROM live_support_messages m
        LEFT JOIN users u ON u.id = m.sender_id
        WHERE m.session_id = ?
        ORDER BY m.created_at ASC
        """,
        (session_id,),
    )


def list_live_support_sessions(status=None, limit=80):
    sql = """
        SELECT
            s.*,
            u.name AS user_name,
            u.email AS user_email,
            a.name AS admin_name,
            (
                SELECT message
                FROM live_support_messages lm
                WHERE lm.session_id = s.id
                ORDER BY lm.created_at DESC
                LIMIT 1
            ) AS last_message,
            (
                SELECT created_at
                FROM live_support_messages lm
                WHERE lm.session_id = s.id
                ORDER BY lm.created_at DESC
                LIMIT 1
            ) AS last_message_at
        FROM live_support_sessions s
        LEFT JOIN users u ON u.id = s.user_id
        LEFT JOIN users a ON a.id = s.assigned_admin_id
        WHERE 1=1
    """
    params = []
    if status and status != "all":
        if isinstance(status, (list, tuple, set)):
            placeholders = ",".join("?" for _ in status)
            sql += f" AND s.status IN ({placeholders})"
            params.extend(list(status))
        else:
            sql += " AND s.status = ?"
            params.append(status)
    sql += " ORDER BY CASE s.status WHEN 'waiting' THEN 0 WHEN 'active' THEN 1 WHEN 'resolved' THEN 2 ELSE 3 END, s.updated_at DESC LIMIT ?"
    params.append(limit)
    return query_all(sql, params)


def accept_live_support_session(session_id, admin_id, admin_name="Admin User"):
    current = get_live_support_session(session_id)
    if current and current.get("status") == "active" and current.get("assigned_admin_id"):
        return current
    now = now_text()
    with connect() as conn:
        conn.execute(
            """
            UPDATE live_support_sessions
            SET assigned_admin_id = ?, status = 'active', updated_at = ?
            WHERE id = ? AND status IN ('waiting', 'active')
            """,
            (admin_id, now, session_id),
        )
        conn.execute(
            """
            INSERT INTO live_support_messages (session_id, sender_id, sender_role, message, created_at)
            VALUES (?, ?, 'system', ?, ?)
            """,
            (session_id, admin_id, f"{admin_name or 'Admin User'} joined the chat.", now),
        )
        conn.commit()
    add_audit(admin_id, "accept_live_chat", "live_support_session", session_id, "Accepted live support chat")
    return get_live_support_session(session_id)


def end_live_support_session(session_id, status="resolved", actor_id=None, message=None):
    final_status = status if status in {"resolved", "ended"} else "resolved"
    now = now_text()
    system_message = message or (
        "This chat has been marked as resolved."
        if final_status == "resolved"
        else "The customer ended this live support chat."
    )
    with connect() as conn:
        conn.execute(
            """
            UPDATE live_support_sessions
            SET status = ?, updated_at = ?, ended_at = ?
            WHERE id = ?
            """,
            (final_status, now, now, session_id),
        )
        conn.execute(
            """
            INSERT INTO live_support_messages (session_id, sender_id, sender_role, message, created_at)
            VALUES (?, ?, 'system', ?, ?)
            """,
            (session_id, actor_id, system_message, now),
        )
        conn.commit()
    if actor_id:
        add_audit(actor_id, f"{final_status}_live_chat", "live_support_session", session_id, system_message)
    return get_live_support_session(session_id)


def convert_live_support_to_ticket(session_id, admin_id=None):
    session_row = get_live_support_session(session_id)
    if not session_row or not session_row.get("user_id"):
        return None
    messages = get_live_support_messages(session_id)
    transcript = "\n".join(
        f"[{message.get('created_at')}] {message.get('sender_role')}: {message.get('message')}"
        for message in messages
    )
    ticket_id = create_support_ticket(
        session_row["user_id"],
        f"Live Support: {session_row.get('subject') or 'Customer chat'}",
        "other",
        transcript or "Live support chat converted to ticket.",
        "medium",
    )
    update_ticket(ticket_id, status="in_progress", assigned_admin_id=admin_id)
    add_audit(admin_id, "convert_live_chat_ticket", "support_ticket", ticket_id, f"Live chat {session_id}")
    return ticket_id


def add_audit(admin_id, action, target_type="", target_id="", details=""):
    execute(
        """
        INSERT INTO admin_audit_logs (admin_id, action, target_type, target_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (admin_id, action, target_type, str(target_id or ""), details, now_text()),
    )


DEFAULT_ADMIN_SETTINGS = {
    "notification_email_alerts": "true",
    "notification_suspicious_voucher_alerts": "true",
    "notification_ticket_notifications": "true",
    "notification_announcement_notifications": "true",
    "notification_system_warnings": "false",
    "maintenance_mode": "false",
    "backup_frequency": "Daily",
    "backup_retention": "30 days",
}


def admin_settings_dict():
    rows = query_all("SELECT setting_key, setting_value FROM admin_settings")
    data = dict(DEFAULT_ADMIN_SETTINGS)
    data.update({row["setting_key"]: row["setting_value"] for row in rows})
    return data


def set_admin_setting(key, value, admin_id=None):
    key = str(key or "").strip()
    if not key:
        return False
    value = str(value)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO admin_settings (setting_key, setting_value, updated_by, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (key, value, admin_id, now_text()),
        )
        conn.commit()
    add_audit(admin_id, "change_settings", "admin_settings", key, f"{key} = {value}")
    return True


def save_admin_settings(settings, admin_id=None):
    for key, value in (settings or {}).items():
        set_admin_setting(key, value, admin_id)
    return admin_settings_dict()


def recent_admin_audits(limit=30):
    rows = query_all(
        """
        SELECT l.*, u.name AS admin_name
        FROM admin_audit_logs l
        LEFT JOIN users u ON u.id = l.admin_id
        ORDER BY l.created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    if rows:
        return rows
    return [
        {
            "admin_name": "Master Admin",
            "action": "admin_login",
            "target_type": "admin",
            "target_id": "demo",
            "details": "Master admin login",
            "created_at": now_text(),
        },
        {
            "admin_name": "Master Admin",
            "action": "create_announcement",
            "target_type": "announcement",
            "target_id": "demo",
            "details": "Published customer announcement",
            "created_at": now_text(),
        },
        {
            "admin_name": "Master Admin",
            "action": "update_voucher",
            "target_type": "voucher",
            "target_id": "demo",
            "details": "Updated voucher status",
            "created_at": now_text(),
        },
    ]


def latest_system_backup():
    return query_one("SELECT * FROM system_backups ORDER BY created_at DESC LIMIT 1")


def list_system_backups(limit=10):
    return query_all("SELECT * FROM system_backups ORDER BY created_at DESC LIMIT ?", (limit,))


def run_manual_backup(admin_id=None):
    backup_dir = BASE_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"vouchr_backup_{stamp}.db"
    backup_path = backup_dir / backup_name
    shutil.copy2(DB_PATH, backup_path)
    created_at = now_text()
    backup_id = execute(
        """
        INSERT INTO system_backups (backup_name, backup_path, created_by, created_at, status)
        VALUES (?, ?, ?, ?, 'completed')
        """,
        (backup_name, str(backup_path), admin_id, created_at),
    )
    add_audit(admin_id, "run_backup", "system_backup", backup_id, backup_name)
    return query_one("SELECT * FROM system_backups WHERE id = ?", (backup_id,))


def seed_demo_activity():
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO announcements (id, title, message, audience, status, created_at, updated_at)
            VALUES (1, 'Welcome to Vouchr', 'New food vouchers are available this week.', 'all_users', 'published', ?, ?)
            """,
            (now_text(), now_text()),
        )
        conn.commit()


def dashboard_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    return {
        "total_users": query_one("SELECT COUNT(*) AS c FROM users WHERE role = 'customer'")["c"],
        "active_users_today": query_one("SELECT COUNT(*) AS c FROM users WHERE role = 'customer' AND substr(COALESCE(last_login_at, created_at), 1, 10) = ?", (today,))["c"],
        "total_merchants": query_one("SELECT COUNT(*) AS c FROM merchants")["c"],
        "active_vouchers": query_one("SELECT COUNT(*) AS c FROM vouchers WHERE status = 'active'")["c"],
        "pending_vouchers": query_one("SELECT COUNT(*) AS c FROM vouchers WHERE status = 'pending'")["c"],
        "expired_vouchers": query_one("SELECT COUNT(*) AS c FROM vouchers WHERE status = 'expired'")["c"],
        "today_redemptions": query_one(
            """
            SELECT COUNT(*) AS c
            FROM voucher_redemptions
            WHERE substr(redeemed_at, 1, 10) = ? AND lower(status) = 'redeemed'
            """,
            (today,),
        )["c"],
        "total_redemptions": query_one(
            "SELECT COUNT(*) AS c FROM voucher_redemptions WHERE lower(status) = 'redeemed'"
        )["c"],
        "new_users_week": query_one("SELECT COUNT(*) AS c FROM users WHERE role = 'customer' AND substr(created_at, 1, 10) >= ?", (week_ago,))["c"],
        "new_merchants_month": query_one("SELECT COUNT(*) AS c FROM merchants WHERE substr(created_at, 1, 10) >= ?", (month_ago,))["c"],
    }


def admin_users():
    return query_all(
        """
        SELECT
            u.*,
            COUNT(DISTINCT sv.id) AS saves,
            COUNT(DISTINCT vr.id) AS redemptions
        FROM users u
        LEFT JOIN saved_vouchers sv ON sv.user_id = u.id
        LEFT JOIN voucher_redemptions vr ON vr.user_id = u.id
        WHERE u.role = 'customer'
        GROUP BY u.id
        ORDER BY u.created_at DESC
        """
    )


def admin_merchants():
    return query_all(
        """
        SELECT
            m.*,
            COUNT(v.id) AS active_vouchers,
            COALESCE(SUM(v.redeemed_count), 0) AS redemptions
        FROM merchants m
        LEFT JOIN vouchers v ON v.merchant_id = m.id AND v.status = 'active'
        GROUP BY m.id
        ORDER BY redemptions DESC, m.created_at DESC
        """
    )


def admin_vouchers():
    return query_all(
        """
        SELECT
            v.*,
            m.business_name,
            COUNT(sv.id) AS saves
        FROM vouchers v
        LEFT JOIN merchants m ON m.id = v.merchant_id
        LEFT JOIN saved_vouchers sv ON sv.voucher_id = v.id
        GROUP BY v.id
        ORDER BY v.updated_at DESC
        """
    )


def set_voucher_status(voucher_id, status, admin_id=None):
    execute("UPDATE vouchers SET status = ?, updated_at = ? WHERE id = ?", (status, now_text(), voucher_id))
    add_audit(admin_id, f"voucher_{status}", "voucher", voucher_id, f"Voucher marked {status}")


def list_merchant_activity(limit=8):
    rows = query_all(
        """
        SELECT l.*, m.business_name, u.name AS actor_name
        FROM merchant_activity_logs l
        LEFT JOIN merchants m ON m.id = l.merchant_id
        LEFT JOIN users u ON u.id = l.actor_user_id
        ORDER BY l.created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    if rows:
        return rows
    return query_all(
        """
        SELECT v.merchant_id, v.id AS source_id, v.title AS details,
               CASE WHEN v.risk_status = 'flagged' THEN 'Flagged Voucher' ELSE 'Created Voucher' END AS action,
               'voucher' AS source_type,
               v.updated_at AS created_at,
               COALESCE(m.business_name, v.merchant_name, 'Merchant') AS business_name,
               COALESCE(m.business_name, v.merchant_name, 'Merchant Owner') AS actor_name
        FROM vouchers v
        LEFT JOIN merchants m ON m.id = v.merchant_id
        ORDER BY v.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def list_ai_flags(status=None, limit=20):
    sql = """
        SELECT f.*, v.title AS voucher_title, v.description, v.discount_value, v.status AS voucher_status,
               v.expiry_date, m.business_name AS merchant_name
        FROM ai_voucher_flags f
        LEFT JOIN vouchers v ON v.id = f.voucher_id
        LEFT JOIN merchants m ON m.id = f.merchant_id
        WHERE 1=1
    """
    params = []
    if status:
        sql += " AND f.status = ?"
        params.append(status)
    sql += """
        ORDER BY
            CASE f.risk_level WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
            f.updated_at DESC
        LIMIT ?
    """
    params.append(limit)
    return query_all(sql, params)


def get_ai_flag(flag_id):
    return query_one(
        """
        SELECT f.*, v.title AS voucher_title, v.description, v.discount_value, v.status AS voucher_status,
               v.expiry_date, m.business_name AS merchant_name, m.contact_email
        FROM ai_voucher_flags f
        LEFT JOIN vouchers v ON v.id = f.voucher_id
        LEFT JOIN merchants m ON m.id = f.merchant_id
        WHERE f.id = ?
        """,
        (flag_id,),
    )


def review_ai_flag(flag_id, action, admin_id=None):
    flag = get_ai_flag(flag_id)
    if not flag:
        return False

    action_map = {
        "allow": ("allowed", "active", "Voucher allowed by admin"),
        "hide": ("hidden", "hidden", "Voucher hidden by admin"),
        "remove": ("removed", "removed", "Voucher removed by admin"),
        "warn": ("reviewed", flag.get("voucher_status") or "active", "Merchant warned by admin"),
        "reviewed": ("reviewed", flag.get("voucher_status") or "active", "Flag marked reviewed"),
    }
    if action not in action_map:
        return False

    flag_status, voucher_status, details = action_map[action]
    now = now_text()
    with connect() as conn:
        conn.execute(
            """
            UPDATE ai_voucher_flags
            SET status = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (flag_status, admin_id, now, now, flag_id),
        )
        conn.execute(
            """
            UPDATE vouchers
            SET status = ?,
                risk_status = CASE WHEN ? = 'allowed' THEN 'reviewed' ELSE risk_status END,
                updated_at = ?
            WHERE id = ?
            """,
            (voucher_status, flag_status, now, flag["voucher_id"]),
        )
        conn.execute(
            """
            INSERT INTO merchant_activity_logs (
                merchant_id, actor_user_id, action, details, source_type, source_id, created_at
            )
            VALUES (?, ?, ?, ?, 'ai_review', ?, ?)
            """,
            (
                flag.get("merchant_id"),
                admin_id,
                {
                    "allow": "Voucher Restored by Admin",
                    "hide": "Voucher Hidden by Admin",
                    "remove": "Voucher Hidden by Admin",
                    "warn": "Profile Updated",
                    "reviewed": "Updated Voucher",
                }[action],
                f"{details}: {flag.get('voucher_title')}",
                flag_id,
                now,
            ),
        )
        conn.commit()
    add_audit(admin_id, f"ai_review_{action}", "ai_voucher_flag", flag_id, details)
    return True


def normalize_announcement_datetime(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return raw


def announcement_audiences_for_user(user_id=None, role="unknown"):
    normalized_role = str(role or "unknown").strip().lower()
    user = None
    if user_id:
        user = query_one("SELECT id, role, created_at FROM users WHERE id = ?", (user_id,))
        if user and normalized_role in {"", "unknown", "user"}:
            normalized_role = user.get("role") or normalized_role

    audiences = ["all_users"]
    if normalized_role in {"customer", "customers", "user"}:
        audiences.append("customers")
    elif normalized_role in {"merchant", "merchants"}:
        audiences.append("merchants")

    if user:
        created_at = str(user.get("created_at") or "")[:10]
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if created_at and created_at >= week_ago:
            audiences.append("new_users")

        activity = query_one(
            """
            SELECT
                (SELECT COUNT(*) FROM saved_vouchers WHERE user_id = ?) +
                (SELECT COUNT(*) FROM voucher_redemptions WHERE user_id = ?) AS count
            """,
            (user_id, user_id),
        )
        if int((activity or {}).get("count") or 0) >= 5:
            audiences.append("high_activity_users")

    return list(dict.fromkeys(audiences))


def list_admin_announcements(limit=50):
    return query_all(
        """
        SELECT a.*, u.name AS created_by_name
        FROM announcements a
        LEFT JOIN users u ON u.id = a.created_by
        ORDER BY a.created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def create_announcement(title, message, audience, status, admin_id=None, scheduled_at=None):
    created_at = now_text()
    scheduled_at = normalize_announcement_datetime(scheduled_at)
    announcement_id = execute(
        """
        INSERT INTO announcements (title, message, audience, status, scheduled_at, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (title, message, audience, status, scheduled_at, admin_id, created_at, created_at),
    )
    add_audit(admin_id, "create_announcement", "announcement", announcement_id, title)
    return announcement_id


def active_announcements_for_user(user_id=None, role="unknown", limit=10):
    audiences = announcement_audiences_for_user(user_id, role)
    placeholders = ",".join("?" for _ in audiences)
    params = [now_text(), *audiences]
    read_filter = ""
    if user_id:
        read_filter = "AND a.id NOT IN (SELECT announcement_id FROM announcement_reads WHERE user_id = ?)"
        params.append(user_id)
    params.append(limit)

    return query_all(
        f"""
        SELECT a.*
        FROM announcements a
        WHERE (
                a.status = 'published'
                OR (
                    a.status = 'scheduled'
                    AND COALESCE(a.scheduled_at, '') != ''
                    AND a.scheduled_at <= ?
                )
            )
          AND a.audience IN ({placeholders})
          {read_filter}
        ORDER BY a.created_at DESC
        LIMIT ?
        """,
        params,
    )


def mark_announcement_read(announcement_id, user_id):
    if not announcement_id or not user_id:
        return False
    execute(
        """
        INSERT OR IGNORE INTO announcement_reads (announcement_id, user_id, read_at)
        VALUES (?, ?, ?)
        """,
        (announcement_id, user_id, now_text()),
    )
    return True


def mark_all_active_announcements_read(user_id, role="unknown"):
    if not user_id:
        return 0
    announcements = active_announcements_for_user(user_id, role, limit=100)
    for announcement in announcements:
        mark_announcement_read(announcement.get("id"), user_id)
    return len(announcements)


def published_announcements(audience="all_users"):
    role_map = {
        "customers": "customer",
        "customer": "customer",
        "merchants": "merchant",
        "merchant": "merchant",
        "all_users": "unknown",
    }
    return active_announcements_for_user(None, role_map.get(str(audience or ""), "unknown"), limit=5)
