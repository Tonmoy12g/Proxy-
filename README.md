# TrustVault Store Mini App

GitHub-এ সব ফাইল upload করুন।

Render Web Service:
- Build: `pip install -r requirements.txt`
- Start: `gunicorn -w 1 -b 0.0.0.0:$PORT bot:app_web`

Environment Variables:
- `BOT_TOKEN` = BotFather token
- `ADMIN_ID` = numeric Telegram ID
- `WEBAPP_URL` = Render HTTPS URL

**Important:** এই starter Gmail username/password stock বা automatic Gmail credential delivery রাখে না। এটি Proxy/VPN store-এর Mini App shell ও inventory/purchase flow দেখায়। Production-এ persistent database ব্যবহার করুন; Render local filesystem স্থায়ী database হিসেবে নির্ভরযোগ্য নয়।
