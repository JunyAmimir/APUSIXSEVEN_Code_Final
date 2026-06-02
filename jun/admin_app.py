from datetime import datetime, timedelta
import csv
import io

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

import vouchr_db


admin_app = Flask(__name__, template_folder="templates", static_folder="assets")
admin_app.secret_key = "vouchr_master_admin_key"
admin_app.permanent_session_lifetime = timedelta(days=7)

FOOD_CATEGORIES = ["Fast Food", "Restaurants", "Café", "Desserts", "Beverages", "Sushi", "Pizza"]

DEMO_FOOD_CATEGORY_REDEMPTIONS = [
    {"category": "Fast Food", "redemptions": 2045},
    {"category": "Restaurants", "redemptions": 1237},
    {"category": "Café", "redemptions": 842},
    {"category": "Desserts", "redemptions": 623},
    {"category": "Beverages", "redemptions": 416},
    {"category": "Sushi", "redemptions": 258},
    {"category": "Pizza", "redemptions": 190},
]


@admin_app.before_request
def prepare_database():
    vouchr_db.init_db(sync_csv=True)


def current_admin():
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    return vouchr_db.query_one("SELECT * FROM users WHERE id = ? AND role = 'admin'", (admin_id,))


def require_admin():
    admin = current_admin()
    if not admin:
        return None
    vouchr_db.set_agent_status(admin["id"], "online")
    return admin


def compact_date(value):
    try:
        parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        return parsed.strftime("%b %d")
    except (TypeError, ValueError):
        return str(value or "")[:6] or "Today"


def relative_time(value):
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(value or "Just now")
    delta = datetime.now() - parsed
    minutes = max(1, int(delta.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def date_range_label(days=6):
    end = datetime.now()
    start = end - timedelta(days=days)
    if start.year == end.year:
        return f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
    return f"{start.strftime('%b %d, %Y')} - {end.strftime('%b %d, %Y')}"


def normalize_food_category(category="", title="", merchant=""):
    text = f"{category} {title} {merchant}".lower()
    text = text.replace("é", "e")

    if any(word in text for word in ["sushi", "sashimi", "maki"]):
        return "Sushi"
    if any(word in text for word in ["pizza", "pizzeria"]):
        return "Pizza"
    if any(word in text for word in ["cafe", "coffee", "starbucks", "latte", "espresso"]):
        return "Café"
    if any(word in text for word in ["dessert", "cake", "sweet", "ice cream", "waffle", "pastry"]):
        return "Desserts"
    if any(word in text for word in ["drink", "juice", "smoothie", "tea", "beverage", "boost"]):
        return "Beverages"
    if any(word in text for word in ["fast", "burger", "mcdonald", "kfc", "combo", "fries"]):
        return "Fast Food"
    if any(word in text for word in ["restaurant", "pasta", "meal", "lunch", "dinner", "palmyra", "ayam", "gepunk", "gepok"]):
        return "Restaurants"

    legacy_map = {
        "food & dining": "Restaurants",
        "retail": "Café",
        "health & beauty": "Desserts",
        "travel": "Beverages",
        "entertainment": "Sushi",
        "others": "Pizza",
        "merchant deal": "Restaurants",
        "food": "Restaurants",
    }
    return legacy_map.get(str(category or "").strip().lower(), "Restaurants")


def food_category_performance(use_demo_fallback=False):
    totals = {category: 0 for category in FOOD_CATEGORIES}
    rows = vouchr_db.query_all(
        """
        SELECT category, title, merchant_name, COALESCE(redeemed_count, 0) AS redemptions
        FROM vouchers
        """
    )
    for row in rows:
        category = normalize_food_category(
            row.get("category"),
            row.get("title"),
            row.get("merchant_name"),
        )
        totals[category] += int(row.get("redemptions") or 0)

    if use_demo_fallback or not rows or sum(totals.values()) == 0:
        return [dict(item) for item in DEMO_FOOD_CATEGORY_REDEMPTIONS]

    return [
        {"category": category, "redemptions": totals[category]}
        for category in FOOD_CATEGORIES
    ]


def demo_user_growth(total_users):
    end = datetime.now()
    points = []
    start_value = max(1200, int(total_users * 0.64))
    end_value = max(total_users, 128540)
    for index in range(30):
        current = end - timedelta(days=29 - index)
        progress = index / 29
        wave = [0, 900, 2100, 1300, 2800, 1600][index % 6]
        value = int(start_value + ((end_value - start_value) * progress) + wave)
        points.append({"date": current.strftime("%b %d"), "users": value})
    points[-1]["users"] = end_value
    return points


def database_user_growth(total_users):
    rows = vouchr_db.query_all(
        """
        SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
        FROM users
        WHERE role = 'customer'
        GROUP BY day
        ORDER BY day ASC
        """
    )
    running = 0
    points = []
    for row in rows[-30:]:
        running += int(row.get("count") or 0)
        points.append({"date": compact_date(row.get("day")), "users": running})
    if len(points) < 6:
        return demo_user_growth(total_users)
    return points


def dashboard_summary_payload():
    stats = vouchr_db.dashboard_stats()
    merchants = vouchr_db.admin_merchants()
    vouchers = vouchr_db.admin_vouchers()
    tickets = vouchr_db.list_support_tickets()
    waiting_live_chats = vouchr_db.list_live_support_sessions(status="waiting", limit=100)
    ai_flags = vouchr_db.list_ai_flags(status="pending_review", limit=6)

    demo_mode = stats["total_users"] < 25 or stats["active_vouchers"] < 8
    kpis = {
        "total_users": max(stats["total_users"], 128540) if demo_mode else stats["total_users"],
        "active_users_today": max(stats["active_users_today"], 24782) if demo_mode else stats["active_users_today"],
        "partnered_merchants": max(stats["total_merchants"], 1276) if demo_mode else stats["total_merchants"],
        "active_vouchers": max(stats["active_vouchers"], 8932) if demo_mode else stats["active_vouchers"],
        "todays_redemptions": max(stats["today_redemptions"], 3421) if demo_mode else stats["today_redemptions"],
    }
    kpi_deltas = {
        "total_users": "12.4%",
        "active_users_today": "8.7%",
        "partnered_merchants": "6.3%",
        "active_vouchers": "5.1%",
        "todays_redemptions": "9.8%",
    }

    redemptions_by_category = food_category_performance(use_demo_fallback=demo_mode)

    if demo_mode:
        voucher_status = [
            {"status": "Active", "count": 5312},
            {"status": "Redeemed", "count": 2141},
            {"status": "Expired", "count": 1102},
            {"status": "Scheduled", "count": 377},
        ]
    else:
        voucher_status = [
            {"status": "Active", "count": stats["active_vouchers"]},
            {"status": "Redeemed", "count": stats["total_redemptions"]},
            {"status": "Expired", "count": stats["expired_vouchers"]},
            {"status": "Scheduled", "count": vouchr_db.query_one("SELECT COUNT(*) AS c FROM vouchers WHERE status = 'scheduled'")["c"]},
        ]

    activity = []
    for row in vouchr_db.list_merchant_activity(limit=8):
        activity.append({
            "partner": row.get("business_name") or "Merchant",
            "action": row.get("action") or "Updated Voucher",
            "details": row.get("details") or "Merchant activity",
            "by": "AI Risk System" if row.get("action") == "Flagged Voucher" else (row.get("actor_name") or "Merchant Owner"),
            "time": relative_time(row.get("created_at")),
        })
    if demo_mode and len(activity) < 5:
        activity.extend([
            {"partner": "The Good Burger", "action": "Created Voucher", "details": "30% OFF Burger Combo", "by": "Merchant Owner", "time": "5m ago"},
            {"partner": "Pastamani", "action": "Submitted Ticket", "details": "Voucher image not updating", "by": "Pastamani Admin", "time": "12m ago"},
            {"partner": "Boost Juice", "action": "Updated Voucher", "details": "Changed expiry date to 30 June", "by": "Merchant Staff", "time": "25m ago"},
            {"partner": "Sushi King", "action": "Flagged Voucher", "details": "Suspicious discount: 95% OFF", "by": "AI Risk System", "time": "1h ago"},
            {"partner": "Palmyra", "action": "Replied to Ticket", "details": "QR redemption issue", "by": "Store Manager", "time": "2h ago"},
        ])
    activity = activity[:5]

    flagged = [
        {
            "id": flag["id"],
            "merchant": flag.get("merchant_name") or "Merchant",
            "voucher": flag.get("voucher_title") or "Voucher",
            "reason": flag.get("reason") or "Needs review",
            "risk_level": str(flag.get("risk_level") or "low").title(),
            "confidence_score": flag.get("confidence_score") or 0,
            "review_url": url_for("ai_review_detail", flag_id=flag["id"]),
        }
        for flag in ai_flags
    ]
    if demo_mode and not flagged:
        flagged = [
            {"id": "demo-1", "merchant": "Sushi King", "voucher": "95% OFF Sushi Buffet", "reason": "Unrealistic discount", "risk_level": "High", "confidence_score": 94, "review_url": url_for("ai_review")},
            {"id": "demo-2", "merchant": "Café Luna", "voucher": "Free Drink Unlimited", "reason": "Misleading wording", "risk_level": "Medium", "confidence_score": 78, "review_url": url_for("ai_review")},
            {"id": "demo-3", "merchant": "Burger House", "voucher": "RM0 Meal Deal", "reason": "Possible abuse", "risk_level": "High", "confidence_score": 91, "review_url": url_for("ai_review")},
        ]

    top_category = max(redemptions_by_category, key=lambda row: row["redemptions"]) if redemptions_by_category else None
    high_flags = [flag for flag in flagged if str(flag.get("risk_level")).lower() == "high"]
    if high_flags:
        insight = f"{len(high_flags)} high-risk vouchers need review. Check AI Review before they affect customer trust."
    elif top_category and top_category["redemptions"] > 0:
        insight = (
            f"{top_category['category']} vouchers are leading redemptions this week. "
            "Consider encouraging more merchants to launch food combo deals."
        )
    elif kpis["active_vouchers"] < 10:
        insight = "Active vouchers are low. Invite partners to publish more campaigns this week."
    else:
        insight = "Platform activity looks stable. Keep monitoring partner campaigns and support tickets."

    return {
        "date_range": date_range_label(),
        "kpis": kpis,
        "kpi_deltas": kpi_deltas,
        "user_growth": database_user_growth(kpis["total_users"]),
        "redemptions_by_category": redemptions_by_category,
        "voucher_status": voucher_status,
        "recent_merchant_activity": activity,
        "recent_activity": activity,
        "ai_flagged_vouchers": flagged,
        "insight": insight,
        "ai_review_count": len(ai_flags),
        "support_ticket_count": len([ticket for ticket in tickets if ticket.get("status") in {"new", "open", "in_progress"}]) + len(waiting_live_chats),
        "live_chat_waiting_count": len(waiting_live_chats),
        "notification_count": max(len(ai_flags) + len([ticket for ticket in tickets if ticket.get("status") in {"new", "open", "in_progress"}]) + len(waiting_live_chats), 8 if demo_mode else 0),
        "system_status": {
            "web_application": "Operational",
            "api_services": "Operational",
            "database": "Operational",
            "qr_redemption": "Operational",
            "uptime": "99.98%",
        },
        "demo_mode": demo_mode,
        "real_counts": stats,
    }


@admin_app.route("/login", methods=["GET", "POST"])
@admin_app.route("/admin/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        admin = vouchr_db.query_one(
            "SELECT * FROM users WHERE lower(email) = lower(?) AND role = 'admin'",
            (email,),
        )
        if admin and admin.get("password") == password:
            session.permanent = bool(request.form.get("remember"))
            session["admin_id"] = admin["id"]
            vouchr_db.touch_login(admin["email"])
            vouchr_db.add_audit(admin["id"], "admin_login", "admin", admin["id"], "Master admin login")
            return redirect(url_for("dashboard"))
        error = "Invalid admin login."
    return render_template("admin_login.html", error=error)


@admin_app.route("/logout")
@admin_app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def page_context(active):
    admin = require_admin()
    if not admin:
        return None

    summary = dashboard_summary_payload()
    stats = vouchr_db.dashboard_stats()
    vouchers = vouchr_db.admin_vouchers()
    users = vouchr_db.admin_users()
    merchants = vouchr_db.admin_merchants()
    tickets = vouchr_db.list_support_tickets()
    live_sessions = vouchr_db.list_live_support_sessions()
    ai_flags = vouchr_db.list_ai_flags(status="pending_review", limit=50)
    selected_ticket = None
    ticket_messages = []
    selected_live_session = None
    live_messages = []
    support_tab = request.args.get("tab", "tickets")
    if active == "support":
        if request.path.endswith("/live") or request.args.get("live_session_id"):
            support_tab = "live"
        selected_id = request.args.get("ticket_id") or (tickets[0]["id"] if tickets else None)
        if selected_id and support_tab != "live":
            selected_ticket, ticket_messages = vouchr_db.get_ticket(selected_id)
        selected_live_id = request.args.get("live_session_id") or (live_sessions[0]["id"] if live_sessions else None)
        if selected_live_id and support_tab == "live":
            selected_live_session = vouchr_db.get_live_support_session(selected_live_id)
            live_messages = vouchr_db.get_live_support_messages(selected_live_id)
    announcements = vouchr_db.list_admin_announcements()
    audits = vouchr_db.recent_admin_audits(limit=30)
    admin_settings = vouchr_db.admin_settings_dict()
    backups = vouchr_db.list_system_backups(limit=5)
    latest_backup = backups[0] if backups else None

    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    user_growth = vouchr_db.query_all(
        """
        SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
        FROM users
        WHERE role = 'customer'
        GROUP BY day
        ORDER BY day DESC
        LIMIT 7
        """
    )
    category_performance = food_category_performance()
    voucher_status = vouchr_db.query_all(
        """
        SELECT status, COUNT(*) AS count
        FROM vouchers
        GROUP BY status
        ORDER BY count DESC
        """
    )

    recent_activity = vouchr_db.list_merchant_activity(limit=6)

    long_term_partners = [
        merchant for merchant in merchants
        if str(merchant.get("partner_since") or merchant.get("created_at") or "")[:10] < month_ago
    ]
    high_performing = [merchant for merchant in merchants if int(merchant.get("redemptions") or 0) >= 10]
    new_partners = [
        merchant for merchant in merchants
        if str(merchant.get("created_at") or "")[:10] >= month_ago
    ]

    if ai_flags:
        insight = f"{len(ai_flags)} voucher risk item needs AI Review."
    elif stats["active_vouchers"] == 0:
        insight = "There are no active vouchers. Ask merchants to publish fresh offers."
    elif stats["new_users_week"] > 0:
        insight = f"{stats['new_users_week']} new users joined this week. Good time to publish announcements."
    else:
        insight = "Platform health looks stable. Keep monitoring support tickets and merchant activity."

    return {
        "active": active,
        "admin": admin,
        "stats": stats,
        "users": users,
        "merchants": merchants,
        "vouchers": vouchers,
        "tickets": tickets,
        "live_sessions": live_sessions,
        "ai_flags": ai_flags,
        "selected_ticket": selected_ticket,
        "ticket_messages": ticket_messages,
        "selected_live_session": selected_live_session,
        "live_messages": live_messages,
        "support_tab": support_tab,
        "live_chat_waiting_count": summary.get("live_chat_waiting_count", 0),
        "announcements": announcements,
        "audits": audits,
        "admin_settings": admin_settings,
        "system_backups": backups,
        "latest_backup": latest_backup,
        "user_growth": list(reversed(user_growth)),
        "category_performance": category_performance,
        "voucher_status": voucher_status,
        "recent_activity": recent_activity,
        "insight": insight,
        "long_term_partners": long_term_partners,
        "high_performing": high_performing,
        "new_partners": new_partners,
        "week_ago": week_ago,
        "today": datetime.now().strftime("%d %b %Y"),
        "date_range": summary["date_range"],
        "notification_count": summary["notification_count"],
        "ai_review_count": summary["ai_review_count"],
        "support_ticket_count": summary["support_ticket_count"],
        "system_status": summary["system_status"],
        "dashboard_summary": summary,
    }


def render_admin(active):
    ctx = page_context(active)
    if ctx is None:
        return redirect(url_for("login"))
    return render_template("admin_dashboard.html", **ctx)


@admin_app.route("/")
@admin_app.route("/dashboard")
@admin_app.route("/admin/dashboard")
def dashboard():
    return render_admin("dashboard")


@admin_app.route("/api/admin/dashboard-summary")
def dashboard_summary_api():
    if not require_admin():
        return jsonify({"error": "Admin login required"}), 401
    return jsonify(dashboard_summary_payload())


@admin_app.route("/ai-review")
def ai_review():
    return render_admin("ai_review")


@admin_app.route("/ai-review/<int:flag_id>")
def ai_review_detail(flag_id):
    admin = require_admin()
    if not admin:
        return redirect(url_for("login"))
    flag = vouchr_db.get_ai_flag(flag_id)
    if not flag:
        return redirect(url_for("ai_review"))
    return render_template(
        "admin_ai_review.html",
        admin=admin,
        flag=flag,
        active="ai_review",
        date_range=date_range_label(),
        notification_count=dashboard_summary_payload()["notification_count"],
        ai_review_count=len(vouchr_db.list_ai_flags(status="pending_review", limit=100)),
        support_ticket_count=len([ticket for ticket in vouchr_db.list_support_tickets() if ticket.get("status") in {"new", "open", "in_progress"}]) + len(vouchr_db.list_live_support_sessions(status="waiting", limit=100)),
    )


@admin_app.route("/ai-review/<int:flag_id>/<action>", methods=["POST"])
def ai_review_action(flag_id, action):
    admin = require_admin()
    if not admin:
        return redirect(url_for("login"))
    if action in {"allow", "hide", "remove", "warn", "reviewed"}:
        vouchr_db.review_ai_flag(flag_id, action, admin["id"])
    return redirect(url_for("ai_review_detail", flag_id=flag_id))


@admin_app.route("/users")
def users():
    return render_admin("users")


@admin_app.route("/partners")
def partners():
    return render_admin("partners")


@admin_app.route("/vouchers", methods=["GET", "POST"])
def vouchers():
    admin = require_admin()
    if not admin:
        return redirect(url_for("login"))
    if request.method == "POST":
        voucher_id = request.form.get("voucher_id")
        action = request.form.get("action")
        if voucher_id and action in {"active", "hidden", "removed"}:
            vouchr_db.set_voucher_status(voucher_id, action, admin["id"])
        return redirect(url_for("vouchers"))
    return render_admin("vouchers")


@admin_app.route("/support", methods=["GET", "POST"])
def support():
    admin = require_admin()
    if not admin:
        return redirect(url_for("login"))

    if request.method == "POST":
        ticket_id = request.form.get("ticket_id")
        action = request.form.get("action", "reply")
        if action == "resolve":
            vouchr_db.update_ticket(ticket_id, status="resolved", assigned_admin_id=admin["id"])
            vouchr_db.add_audit(admin["id"], "resolve_ticket", "support_ticket", ticket_id, "Ticket resolved")
        else:
            message = request.form.get("message", "").strip()
            if message:
                vouchr_db.update_ticket(ticket_id, status="in_progress", assigned_admin_id=admin["id"])
                vouchr_db.add_ticket_message(ticket_id, admin["id"], "admin", message)
                vouchr_db.add_audit(admin["id"], "reply_ticket", "support_ticket", ticket_id, message[:120])
        return redirect(url_for("support", ticket_id=ticket_id))

    return render_admin("support")


@admin_app.route("/support/live")
def support_live():
    return render_admin("support")


def admin_live_session_or_404(session_id):
    support_session = vouchr_db.get_live_support_session(session_id)
    if not support_session:
        return None
    return support_session


@admin_app.route("/api/admin/live-support/sessions")
def api_admin_live_support_sessions():
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    return jsonify({
        "success": True,
        "sessions": vouchr_db.list_live_support_sessions(),
        "waiting_count": len(vouchr_db.list_live_support_sessions(status="waiting", limit=100))
    })


@admin_app.route("/api/admin/live-support/<int:session_id>/messages")
def api_admin_live_support_messages(session_id):
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    support_session = admin_live_session_or_404(session_id)
    if not support_session:
        return jsonify({"success": False, "error": "Live chat not found"}), 404
    return jsonify({
        "success": True,
        "session": support_session,
        "messages": vouchr_db.get_live_support_messages(session_id)
    })


@admin_app.route("/api/admin/live-support/<int:session_id>/accept", methods=["POST"])
def api_admin_live_support_accept(session_id):
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    support_session = admin_live_session_or_404(session_id)
    if not support_session:
        return jsonify({"success": False, "error": "Live chat not found"}), 404
    updated = vouchr_db.accept_live_support_session(session_id, admin["id"], admin.get("name") or "Admin User")
    return jsonify({
        "success": True,
        "session": updated,
        "messages": vouchr_db.get_live_support_messages(session_id)
    })


@admin_app.route("/api/admin/live-support/<int:session_id>/send", methods=["POST"])
def api_admin_live_support_send(session_id):
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    support_session = admin_live_session_or_404(session_id)
    if not support_session:
        return jsonify({"success": False, "error": "Live chat not found"}), 404
    if support_session.get("status") in {"resolved", "ended"}:
        return jsonify({"success": False, "error": "This chat has ended"}), 400
    if support_session.get("status") == "waiting":
        vouchr_db.accept_live_support_session(session_id, admin["id"], admin.get("name") or "Admin User")
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400
    vouchr_db.add_live_support_message(session_id, admin["id"], "admin", message)
    return jsonify({
        "success": True,
        "session": vouchr_db.get_live_support_session(session_id),
        "messages": vouchr_db.get_live_support_messages(session_id)
    })


@admin_app.route("/api/admin/live-support/<int:session_id>/resolve", methods=["POST"])
def api_admin_live_support_resolve(session_id):
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    support_session = admin_live_session_or_404(session_id)
    if not support_session:
        return jsonify({"success": False, "error": "Live chat not found"}), 404
    updated = vouchr_db.end_live_support_session(session_id, status="resolved", actor_id=admin["id"])
    return jsonify({
        "success": True,
        "session": updated,
        "messages": vouchr_db.get_live_support_messages(session_id)
    })


@admin_app.route("/api/admin/live-support/<int:session_id>/convert-ticket", methods=["POST"])
def api_admin_live_support_convert_ticket(session_id):
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    if not admin_live_session_or_404(session_id):
        return jsonify({"success": False, "error": "Live chat not found"}), 404
    ticket_id = vouchr_db.convert_live_support_to_ticket(session_id, admin["id"])
    if not ticket_id:
        return jsonify({"success": False, "error": "Could not convert chat"}), 400
    return jsonify({
        "success": True,
        "ticket_id": ticket_id,
        "ticket_url": url_for("support", ticket_id=ticket_id)
    })


@admin_app.route("/reports")
def reports():
    return render_admin("reports")


@admin_app.route("/reports/export.csv")
def export_reports_csv():
    admin = require_admin()
    if not admin:
        return redirect(url_for("login"))
    rows = vouchr_db.admin_vouchers()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Voucher", "Merchant", "Category", "Status", "Saves", "Redemptions", "Expiry"])
    for row in rows:
        writer.writerow([
            row.get("title"),
            row.get("merchant_name"),
            row.get("category"),
            row.get("status"),
            row.get("saves"),
            row.get("redeemed_count"),
            row.get("expiry_date"),
        ])
    vouchr_db.add_audit(admin["id"], "export_reports_csv", "report", "voucher_report", "Exported voucher report")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=vouchr_report.csv"},
    )


@admin_app.route("/announcements", methods=["GET"])
def announcements():
    admin = require_admin()
    if not admin:
        return redirect(url_for("login"))
    return render_admin("announcements")


@admin_app.route("/announcements/create", methods=["POST"])
def create_admin_announcement():
    admin = require_admin()
    if not admin:
        return redirect(url_for("login"))

    title = request.form.get("title", "").strip()
    message = request.form.get("message", "").strip()
    audience = request.form.get("audience", "all_users").strip() or "all_users"
    status = request.form.get("status", "draft").strip() or "draft"
    scheduled_at = request.form.get("scheduled_at") or None

    if title and message:
        vouchr_db.create_announcement(title, message, audience, status, admin["id"], scheduled_at)

    return redirect(url_for("announcements"))


@admin_app.route("/api/admin/announcements")
def api_admin_announcements():
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401

    return jsonify({
        "success": True,
        "announcements": vouchr_db.list_admin_announcements(),
    })


@admin_app.route("/settings")
def settings():
    return render_admin("settings")


@admin_app.route("/api/admin/settings")
def api_admin_settings():
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    return jsonify({
        "success": True,
        "settings": vouchr_db.admin_settings_dict(),
        "audits": vouchr_db.recent_admin_audits(limit=10),
        "backups": vouchr_db.list_system_backups(limit=5),
    })


@admin_app.route("/api/admin/settings/notifications", methods=["POST"])
def api_admin_settings_notifications():
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    data = request.get_json(silent=True) or {}
    allowed = {
        "notification_email_alerts",
        "notification_suspicious_voucher_alerts",
        "notification_ticket_notifications",
        "notification_announcement_notifications",
        "notification_system_warnings",
    }
    updates = {
        key: "true" if data.get(key) in {True, "true", "on", "1", 1} else "false"
        for key in allowed
        if key in data
    }
    settings_data = vouchr_db.save_admin_settings(updates, admin["id"]) if updates else vouchr_db.admin_settings_dict()
    return jsonify({
        "success": True,
        "message": "Notification preferences saved",
        "settings": settings_data,
    })


@admin_app.route("/api/admin/settings/maintenance", methods=["POST"])
def api_admin_settings_maintenance():
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    data = request.get_json(silent=True) or {}
    enabled = data.get("maintenance_mode") in {True, "true", "on", "1", 1}
    vouchr_db.set_admin_setting("maintenance_mode", "true" if enabled else "false", admin["id"])
    if data.get("backup_frequency"):
        vouchr_db.set_admin_setting("backup_frequency", data.get("backup_frequency"), admin["id"])
    if data.get("backup_retention"):
        vouchr_db.set_admin_setting("backup_retention", data.get("backup_retention"), admin["id"])
    return jsonify({
        "success": True,
        "message": "Maintenance mode saved for demo",
        "maintenance_mode": enabled,
    })


@admin_app.route("/api/admin/settings/backup", methods=["POST"])
def api_admin_settings_backup():
    admin = require_admin()
    if not admin:
        return jsonify({"success": False, "error": "Admin login required"}), 401
    try:
        backup = vouchr_db.run_manual_backup(admin["id"])
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), 500
    return jsonify({
        "success": True,
        "message": "Manual backup created",
        "backup": backup,
    })


if __name__ == "__main__":
    admin_app.run(host="127.0.0.1", port=5001, debug=True)
