Vouchr Customer, Merchant, and Master Admin Demo

Main customer/merchant app:
1. Install dependencies:
   pip install -r requirements.txt

2. Run the existing app:
   python app.py

3. Open:
   http://127.0.0.1:5000

Master Admin website:
1. Open a second VS Code terminal in this same Project-main folder.

2. Run:
   python admin_app.py

3. Open:
   http://127.0.0.1:5001

Demo admin login:
Email: admin@vouchr.com
Password: admin123

Admin login page:
http://127.0.0.1:5001/login

Admin dashboard:
http://127.0.0.1:5001/dashboard

Shared database:
Both apps use vouchr.db. The database layer syncs existing CSV users, merchants, vouchers, support tickets, announcements, and admin records for the demo.

What still works:
- Existing customer login/signup flow.
- Existing merchant login/signup flow.
- Existing voucher browsing, creation, QR display, and profile pages.
- Existing CSV files are not removed.

New admin features:
- Dashboard overview.
- Dashboard data API at /api/admin/dashboard-summary.
- Chart dashboard with KPI cards, user growth, food category redemptions, voucher status, recent merchant activity, AI flagged vouchers, AI-style rule insight, and system status.
- Users page.
- Merchants page.
- Voucher monitoring without a normal approval queue.
- AI Review page for suspicious vouchers.
- In-website support ticket centre.
- Reports and CSV export.
- Announcements page.
- Settings and audit logs.

Support note:
Customer support happens inside the Vouchr website through /support and the Master Admin Support page. Discord is not used.

AI Review note:
Merchants can create active vouchers freely. The local rule-based checker flags suspicious vouchers for admin review. Medium-risk vouchers stay active; high-risk vouchers can be hidden until reviewed.

Do not use Live Server for the Flask app because Live Server cannot write to the project data files.
