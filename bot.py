import os, json, threading
from pathlib import Path
from flask import Flask, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["8864026991:AAEM_QgbvbfrKcPVDRGEVy3j6khjggkEO-c"]
ADMIN_ID = int(os.environ["8001997389"])
DATA_FILE = Path("data.json")
LOCK = threading.Lock()

DEFAULT = {
 "users": {}, "balance": {},
 "proxy": {"name":"200 MB Proxy","mb":200,"price":10,"stock":[]},
 "vpn": {"name":"30 Days VPN","days":30,"price":50,"stock":[]},
 "orders": {}, "next_order_id":1
}
def save(d):
    with LOCK: DATA_FILE.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def load():
    try: d=json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception: d=json.loads(json.dumps(DEFAULT))
    for k,v in DEFAULT.items(): d.setdefault(k,json.loads(json.dumps(v)))
    save(d); return d
DATA=load()
def bal(uid): return float(DATA["balance"].get(str(uid),0))

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    DATA["users"][str(u.id)]={"id":u.id,"username":u.username or "","name":u.first_name or ""}
    DATA["balance"].setdefault(str(u.id),0); save(DATA)
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("🛍️ Open Store",web_app=WebAppInfo(WEBAPP_URL))]])
    await update.message.reply_text("👋 Welcome to TrustVault Store\n\n🛍️ Open the Mini App:",reply_markup=kb)

async def admin(update,context):
    if update.effective_user.id!=ADMIN_ID:return
    await update.message.reply_text(
        f"👨‍💻 Admin\n\nProxy stock: {len(DATA['proxy']['stock'])}\n"
        f"VPN stock: {len(DATA['vpn']['stock'])}\nUsers: {len(DATA['users'])}\nOrders: {len(DATA['orders'])}"
    )

app_web=Flask(__name__)
@app_web.get("/")
def home():
    return open("index.html",encoding="utf-8").read()
@app_web.get("/health")
def health(): return jsonify({"ok":True})
@app_web.get("/api/catalog")
def catalog():
    return jsonify({"proxy":DATA["proxy"],"vpn":DATA["vpn"],
                    "proxy_stock":len(DATA["proxy"]["stock"]),
                    "vpn_stock":len(DATA["vpn"]["stock"])})
@app_web.post("/api/profile")
def profile():
    b=request.get_json(force=True); uid=str(b.get("user_id",""))
    if not uid.isdigit(): return jsonify({"error":"invalid user"}),400
    orders=[o for o in DATA["orders"].values() if str(o["user_id"])==uid]
    return jsonify({"user_id":int(uid),"balance":bal(uid),"orders":orders[-20:]})
@app_web.post("/api/buy")
def buy():
    b=request.get_json(force=True); uid=str(b.get("user_id","")); product=b.get("product")
    if not uid.isdigit() or product not in ("proxy","vpn"): return jsonify({"error":"invalid request"}),400
    item=DATA[product]; price=float(item["price"])
    if not item["stock"]: return jsonify({"error":"Stock শেষ"}),409
    if bal(uid)<price: return jsonify({"error":"Balance পর্যাপ্ত নয়"}),402
    delivered=item["stock"].pop(0); DATA["balance"][uid]=round(bal(uid)-price,2)
    oid=DATA["next_order_id"]; DATA["next_order_id"]+=1
    DATA["orders"][str(oid)]={"id":oid,"user_id":int(uid),"product":product,"amount":price,"item":delivered,"status":"completed"}
    save(DATA)
    return jsonify({"ok":True,"order_id":oid,"item":delivered,"balance":bal(uid)})

async def bot_runner():
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("admin",admin))
    await app.initialize(); await app.start(); await app.updater.start_polling()
    import asyncio; await asyncio.Event().wait()

if __name__=="__main__":
    import asyncio
    asyncio.run(bot_runner())
