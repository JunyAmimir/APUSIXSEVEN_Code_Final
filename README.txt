VOUCHR
Smart Food Voucher and Budget Platform
======================================

OVERVIEW
--------
Vouchr connects customers with food deals while giving merchants campaign
tools and administrators a complete platform monitoring dashboard.

The project contains two Flask applications sharing one SQLite database:

1. Customer and Merchant App
   Entry point: app.py
   URL: http://127.0.0.1:5000

2. Master Admin App
   Entry point: admin_app.py
   URL: http://127.0.0.1:5001


QUICK START
-----------
1. Install Python 3.

2. Install the required packages:

   pip install -r requirements.txt

3. Start the customer and merchant app:

   python app.py

4. Open a second terminal and start the admin app:

   python admin_app.py

5. Open the URLs listed above.

Do not use VS Code Live Server. Flask must run the project so that database,
CSV, upload, QR, support, and admin features work correctly.


DEMO ACCOUNTS
-------------
Customer
Email: eaton@gmail.com
Password: 12345

Merchant
Email: albert@gmail.com
Password: 12345

Master Admin
Email: admin@vouchr.com
Password: admin123


MAIN FEATURES
-------------
Customer
- Account registration and login
- Voucher discovery, category browsing, search, saving, and QR redemption
- Nearby restaurant map
- Monthly budget tracking and expense management
- AI deal assistant, money coach, and help centre
- Notifications, announcements, support tickets, and live support

Merchant
- Merchant registration and profile management
- Voucher creation, editing, deletion, expiry handling, and image generation
- Voucher performance statistics
- Customer save and redemption activity
- Announcements, support tickets, and live support

Master Admin
- Platform dashboard and KPI reporting
- Customer, merchant, and voucher monitoring
- Rule-based suspicious voucher review
- Support ticket and live-chat administration
- Reports and CSV export
- Announcement management
- Settings, audit logs, and database backups


PROJECT STRUCTURE
-----------------
app.py
    Customer and merchant Flask routes and business logic.

admin_app.py
    Master admin Flask routes and dashboard logic.

vouchr_db.py
    Shared SQLite schema, synchronization, reporting, support, and admin data.

templates/
    user/       Customer pages
    merchant/   Merchant pages
    admin/      Master admin pages

assets/
    components/ Reusable HTML interface components
    css/        Shared interface styling
    admin/      Admin CSS and JavaScript
    merchant/   Merchant images and dashboard icons
    voucher/    Voucher artwork
    store/      Store artwork and logos
    profile/    Profile icons
    nav_icon/   Navigation icons
    cat-icon/   Voucher category icons
    modal/      Voucher modal icons

CSV/
    user/       Customer accounts and demo feature data
    merchant/   Merchant accounts and merchant voucher data

vouchr.db
    Shared SQLite database used by both Flask applications.


AI CONFIGURATION
----------------
Optional AI keys can be placed in a local .env file:

GEMINI_API_KEY=your_key
OPENAI_API_KEY=your_key

Core demo flows remain available when an external AI provider is unavailable.


NOTES
-----
- Merchant vouchers are synchronized from CSV into SQLite for admin reporting.
- High-risk voucher wording can be hidden automatically for admin review.
- Database backups are created in a backups folder when requested by an admin.
- Customer support is built into Vouchr; no external chat service is required.
