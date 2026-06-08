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

Technology used:
Python, HTML, CSV, CSS, JS, flask

How system is built:
This system follows a system architecture where frontend display with HTML/CSS/JS while the backend runs with python flask. Both apps use vouchr.db. The database layer syncs existing CSV users, merchants, vouchers, support tickets, announcements, and admin records for the demo.

Support note:
Customer support happens inside the Vouchr website through /support and the Master Admin Support page. Discord is not used.

AI Review note:
Merchants can create active vouchers freely. The local rule-based checker flags suspicious vouchers for admin review. Medium-risk vouchers stay active; high-risk vouchers can be hidden until reviewed.

Do not use Live Server for the Flask app because Live Server cannot write to the project data files.

AI Tools Used:
Chatgpt, Gemini Ai, Grok
