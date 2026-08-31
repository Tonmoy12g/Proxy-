import os
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ============================================================
# CONFIG
# Set these as Render Environment Variables:
# BOT_TOKEN = your Telegram bot token
# ADMIN_ID  = your Telegram numeric user ID
# ============================================================

BOT_TOKEN ="8805001071:AAFe5ORvRD5QAqH3eU4sCAbT9GjlfmBm8QM"
ADMIN_ID = "8001997389"
BKASH_NUMBER = "01902461583"

DATA_FILE = Path("data.json")
logging.basicConfig(level=logging.INFO)


# ============================================================
# DATA STORAGE — no MySQL required
# ============================================================

DEFAULT_DATA = {
    "balance": {},
    "users": {},
    "proxy": {
        "name": "200 MB Proxy",
        "mb": 200,
        "price": 10,
        "stock": []
    },
    "vpn": {
        "name": "30 Days VPN",
        "days": 30,
        "price": 50,
        "stock": []
    },
    "deposit_requests": {},
    "orders": {},
    "next_deposit_id": 1,
    "next_order_id": 1
}


def load_data():
    if not DATA_FILE.exists():
        save_data(DEFAULT_DATA)
        return json.loads(json.dumps(DEFAULT_DATA))

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        # Keep newly added keys if an older data file is used.
        changed = False
        for key, value in DEFAULT_DATA.items():
            if key not in data:
                data[key] = json.loads(json.dumps(value))
                changed = True
        if changed:
            save_data(data)
        return data
    except Exception:
        return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    tmp.replace(DATA_FILE)


DATA = load_data()


# ============================================================
# HELPERS
# ============================================================

def is_admin(user_id):
    return int(user_id) == ADMIN_ID


def balance(user_id):
    return float(DATA["balance"].get(str(user_id), 0))


def money(value):
    return f"৳{float(value):.2f}"


def user_menu():
    return ReplyKeyboardMarkup(
        [
            ["🟢 Buy Proxy", "🟢 Buy VPN"],
            ["🟢 Add Money", "🟣 Profile"],
            ["🟢 Help"]
        ],
        resize_keyboard=True
    )


def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Pending Deposits", callback_data="admin_deposits"),
            InlineKeyboardButton("📦 Stock", callback_data="admin_stock")
        ],
        [
            InlineKeyboardButton("⚙️ Proxy Settings", callback_data="proxy_settings"),
            InlineKeyboardButton("⚙️ VPN Settings", callback_data="vpn_settings")
        ],
        [
            InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")
        ]
    ])


def clean(text):
    # Avoid HTML parse issues while still allowing code tags where used manually.
    import html
    return html.escape(str(text))


async def safe_send(context, chat_id, text, **kwargs):
    try:
        return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except Exception:
        logging.exception("Telegram send failed")
        return None


# ============================================================
# /start
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    DATA["users"][str(user.id)] = {
        "id": user.id,
        "username": user.username or "",
        "name": user.first_name or "",
        "last_seen": datetime.now().isoformat(timespec="seconds")
    }
    DATA["balance"].setdefault(str(user.id), 0)
    save_data(DATA)

    text = (
        "👋 Welcome to Proxy Shop!\n\n"
        "🛍 নিচের Menu থেকে একটি option নির্বাচন করুন।"
    )
    await update.message.reply_text(text, reply_markup=user_menu())

    if is_admin(user.id):
        await update.message.reply_text(
            "👨‍💻 Admin Panel",
            reply_markup=admin_menu()
        )


# ============================================================
# USER MENU
# ============================================================

async def show_proxy(update, context):
    p = DATA["proxy"]
    stock = len(p["stock"])
    text = (
        "🌐 Proxy Shop\n\n"
        f"📦 {p['name']}\n"
        f"📊 Size: {p['mb']} MB\n"
        f"💰 Price: {money(p['price'])}\n"
        f"📦 Available: {stock}\n\n"
        f"💳 Balance: {money(balance(update.effective_user.id))}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Buy Now", callback_data="buy_proxy")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)


async def show_vpn(update, context):
    v = DATA["vpn"]
    stock = len(v["stock"])
    text = (
        "🌐 VPN Shop\n\n"
        f"📦 {v['name']}\n"
        f"⏳ Duration: {v['days']} Days\n"
        f"💰 Price: {money(v['price'])}\n"
        f"📦 Available: {stock}\n\n"
        f"💳 Balance: {money(balance(update.effective_user.id))}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Buy Now", callback_data="buy_vpn")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)


async def add_money_start(update, context):
    context.user_data["awaiting_deposit_amount"] = True
    await update.message.reply_text(
        "💰 Add Money\n\n"
        "আপনি কত টাকা Add করতে চান তা লিখুন।\n"
        "উদাহরণ: 100"
    )


async def profile(update, context):
    uid = update.effective_user.id
    await update.message.reply_text(
        "🟣 Profile\n\n"
        f"👤 Name: {update.effective_user.first_name or 'User'}\n"
        f"🆔 ID: {uid}\n"
        f"💳 Balance: {money(balance(uid))}"
    )


async def help_user(update, context):
    await update.message.reply_text(
        "🟢 Help\n\n"
        "• Buy Proxy / Buy VPN থেকে পণ্য নির্বাচন করুন।\n"
        "• আগে Add Money করে balance নিতে হবে।\n"
        "• Payment request-এর জন্য সঠিক TxID দিন।\n"
        "• Admin verify করার পর balance যোগ হবে।\n\n"
        f"🟣 bKash: {BKASH_NUMBER}"
    )


# ============================================================
# DEPOSIT FLOW
# ============================================================

async def handle_deposit_amount(update, context):
    if not context.user_data.get("awaiting_deposit_amount"):
        return False

    try:
        amount = float(update.message.text.strip())
        if amount <= 0 or amount > 1000000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ সঠিক Amount দিন। উদাহরণ: 100")
        return True

    context.user_data.pop("awaiting_deposit_amount", None)
    uid = update.effective_user.id
    did = DATA["next_deposit_id"]
    DATA["next_deposit_id"] += 1

    DATA["deposit_requests"][str(did)] = {
        "id": did,
        "user_id": uid,
        "amount": amount,
        "txid": "",
        "status": "awaiting_txid",
        "created_at": datetime.now().isoformat(timespec="seconds")
    }
    save_data(DATA)

    context.user_data["awaiting_txid_deposit"] = did

    await update.message.reply_text(
        "💰 Add Money\n\n"
        f"💵 Amount: {money(amount)}\n"
        f"🟣 bKash Number: {BKASH_NUMBER}\n\n"
        "Payment করার পর Transaction ID (TxID) পাঠান।"
    )
    return True


async def handle_txid(update, context):
    did = context.user_data.get("awaiting_txid_deposit")
    if not did:
        return False

    txid = update.message.text.strip()

    # Basic format/length check; actual payment verification is done by admin.
    if not (6 <= len(txid) <= 64) or any(ch.isspace() for ch in txid):
        await update.message.reply_text("❌ সঠিক Transaction ID দিন।")
        return True

    req = DATA["deposit_requests"].get(str(did))
    if not req or req["status"] != "awaiting_txid":
        context.user_data.pop("awaiting_txid_deposit", None)
        return False

    # Prevent reuse of the same TxID.
    for old in DATA["deposit_requests"].values():
        if old.get("txid", "").lower() == txid.lower():
            await update.message.reply_text(
                "❌ এই Transaction ID আগে ব্যবহার করা হয়েছে। অন্য TxID দিন।"
            )
            return True

    req["txid"] = txid
    req["status"] = "pending"
    save_data(DATA)
    context.user_data.pop("awaiting_txid_deposit", None)

    await update.message.reply_text(
        "⏳ Payment Verification Pending\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 Amount: {money(req['amount'])}\n"
        f"🔑 TxID: {req['txid']}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✅ আপনার payment request সফলভাবে জমা হয়েছে।\n\n"
        "💳 Payment সঠিকভাবে verify হলে আপনার account balance-এ "
        "যোগ করে দেওয়া হবে।\n\n"
        "⚠️ Verification সম্পন্ন হওয়ার আগে আপনার balance-এ "
        "কোনো টাকা যোগ হবে না।\n\n"
        "🙏 অনুগ্রহ করে কিছুক্ষণ অপেক্ষা করুন।"
    )

    if ADMIN_ID:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Accept", callback_data=f"accept_dep_{did}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_dep_{did}")
        ]])
        await safe_send(
            context,
            ADMIN_ID,
            "🔔 New Payment Request\n\n"
            f"🧾 Deposit #{did}\n"
            f"👤 User ID: {req['user_id']}\n"
            f"💰 Amount: {money(req['amount'])}\n"
            f"🔑 TxID: {req['txid']}",
            reply_markup=kb
        )
    return True


# ============================================================
# PURCHASE
# ============================================================

async def buy_product(query, context, product):
    uid = query.from_user.id
    item = DATA[product]

    if not item["stock"]:
        await query.message.reply_text("❌ বর্তমানে Stock শেষ।")
        return

    price = float(item["price"])
    bal = balance(uid)

    if bal < price:
        await query.message.reply_text(
            "❌ আপনার Balance পর্যাপ্ত নয়।\n\n"
            f"💳 Current Balance: {money(bal)}\n"
            f"💰 Required: {money(price)}\n\n"
            "আগে 🟢 Add Money ব্যবহার করুন।"
        )
        return

    # Reserve/deliver immediately from stock after successful balance check.
    product_item = item["stock"].pop(0)
    DATA["balance"][str(uid)] = round(bal - price, 2)

    oid = DATA["next_order_id"]
    DATA["next_order_id"] += 1
    DATA["orders"][str(oid)] = {
        "id": oid,
        "user_id": uid,
        "product": product,
        "amount": price,
        "item": product_item,
        "status": "completed",
        "created_at": datetime.now().isoformat(timespec="seconds")
    }
    save_data(DATA)

    if product == "proxy":
        label = "🔐 Proxy"
    else:
        label = "🔐 VPN"

    await query.message.reply_text(
        "✅ Purchase Successful!\n\n"
        f"🧾 Order #{oid}\n"
        f"📦 {item['name']}\n"
        f"💰 Paid: {money(price)}\n"
        f"💳 Remaining Balance: {money(DATA['balance'][str(uid)])}\n\n"
        f"{label}:\n{product_item}"
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================

async def admin(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin access নেই।")
        return
    await update.message.reply_text("👨‍💻 Admin Panel", reply_markup=admin_menu())


async def admin_help(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "👨‍💻 Admin Commands\n\n"
        "📦 Stock:\n"
        "/addproxy host:port:user:pass\n"
        "/addproxybulk — এরপর প্রতি লাইনে একটি proxy\n"
        "/addvpn VPN_DATA\n"
        "/addvpnbulk — এরপর প্রতি লাইনে একটি VPN item\n\n"
        "⚙️ Proxy:\n"
        "/setproxyname 200 MB Proxy\n"
        "/setproxymb 200\n"
        "/setproxyprice 10\n\n"
        "⚙️ VPN:\n"
        "/setvpnname 30 Days VPN\n"
        "/setvpndays 30\n"
        "/setvpnprice 50\n\n"
        "📊 /stats\n"
        "📦 /stock\n"
        "🧾 /deposits\n"
        "👨‍💻 /admin"
    )


def parse_command_arg(text):
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def admin_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text.strip()

    if text.startswith("/addproxy "):
        value = parse_command_arg(text)
        if value:
            DATA["proxy"]["stock"].append(value)
            save_data(DATA)
            await update.message.reply_text(
                f"✅ Proxy added.\n📦 Stock: {len(DATA['proxy']['stock'])}"
            )
        return

    if text == "/addproxybulk":
        context.user_data["bulk_mode"] = "proxy"
        await update.message.reply_text(
            "➕ প্রতি লাইনে একটি Proxy পাঠান।\n"
            "শেষ হলে /done লিখুন।"
        )
        return

    if text.startswith("/addvpn "):
        value = parse_command_arg(text)
        if value:
            DATA["vpn"]["stock"].append(value)
            save_data(DATA)
            await update.message.reply_text(
                f"✅ VPN added.\n📦 Stock: {len(DATA['vpn']['stock'])}"
            )
        return

    if text == "/addvpnbulk":
        context.user_data["bulk_mode"] = "vpn"
        await update.message.reply_text(
            "➕ প্রতি লাইনে একটি VPN item পাঠান।\n"
            "শেষ হলে /done লিখুন।"
        )
        return

    commands = {
        "/setproxyname": ("proxy", "name", str),
        "/setproxymb": ("proxy", "mb", int),
        "/setproxyprice": ("proxy", "price", float),
        "/setvpnname": ("vpn", "name", str),
        "/setvpndays": ("vpn", "days", int),
        "/setvpnprice": ("vpn", "price", float),
    }

    for cmd, (section, key, caster) in commands.items():
        if text == cmd or text.startswith(cmd + " "):
            raw = parse_command_arg(text)
            try:
                value = caster(raw)
                if isinstance(value, (int, float)) and value <= 0:
                    raise ValueError
                DATA[section][key] = value
                save_data(DATA)
                await update.message.reply_text(
                    f"✅ Updated.\n{key}: {value}"
                )
            except Exception:
                await update.message.reply_text("❌ সঠিক value দিন।")
            return

    if text == "/done":
        context.user_data.pop("bulk_mode", None)
        await update.message.reply_text("✅ Bulk stock mode বন্ধ হয়েছে।")
        return

    if text == "/stock":
        await update.message.reply_text(
            "📦 Stock\n\n"
            f"🌐 Proxy: {len(DATA['proxy']['stock'])}\n"
            f"🌐 VPN: {len(DATA['vpn']['stock'])}"
        )
        return

    if text == "/deposits":
        pending = [
            r for r in DATA["deposit_requests"].values()
            if r["status"] == "pending"
        ]
        if not pending:
            await update.message.reply_text("📭 Pending payment নেই।")
            return

        for r in pending[:30]:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Accept", callback_data=f"accept_dep_{r['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_dep_{r['id']}")
            ]])
            await update.message.reply_text(
                f"🧾 Deposit #{r['id']}\n"
                f"👤 User: {r['user_id']}\n"
                f"💰 Amount: {money(r['amount'])}\n"
                f"🔑 TxID: {r['txid']}",
                reply_markup=kb
            )
        return

    if text == "/stats":
        total_users = len(DATA["users"])
        total_orders = len(DATA["orders"])
        total_balance = sum(float(x) for x in DATA["balance"].values())
        await update.message.reply_text(
            "📊 Statistics\n\n"
            f"👥 Users: {total_users}\n"
            f"🧾 Orders: {total_orders}\n"
            f"💳 User balances: {money(total_balance)}\n"
            f"📦 Proxy stock: {len(DATA['proxy']['stock'])}\n"
            f"📦 VPN stock: {len(DATA['vpn']['stock'])}"
        )
        return


async def bulk_stock_message(update, context):
    if not is_admin(update.effective_user.id):
        return False

    mode = context.user_data.get("bulk_mode")
    if not mode:
        return False

    if update.message.text.strip() == "/done":
        context.user_data.pop("bulk_mode", None)
        await update.message.reply_text("✅ Bulk stock mode বন্ধ হয়েছে।")
        return True

    values = [x.strip() for x in update.message.text.splitlines() if x.strip()]
    if not values:
        return True

    DATA[mode]["stock"].extend(values)
    save_data(DATA)
    await update.message.reply_text(
        f"✅ {len(values)} item added.\n"
        f"📦 Current {mode} stock: {len(DATA[mode]['stock'])}"
    )
    return True


# ============================================================
# CALLBACKS
# ============================================================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data == "buy_proxy":
        await buy_product(query, context, "proxy")
        return

    if data == "buy_vpn":
        await buy_product(query, context, "vpn")
        return

    if not is_admin(uid):
        await query.message.reply_text("❌ Admin access নেই।")
        return

    if data == "admin_deposits":
        # Reuse command-like display.
        pending = [
            r for r in DATA["deposit_requests"].values()
            if r["status"] == "pending"
        ]
        if not pending:
            await query.message.reply_text("📭 Pending payment নেই।")
            return
        for r in pending[:30]:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Accept", callback_data=f"accept_dep_{r['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_dep_{r['id']}")
            ]])
            await query.message.reply_text(
                f"🧾 Deposit #{r['id']}\n"
                f"👤 User: {r['user_id']}\n"
                f"💰 Amount: {money(r['amount'])}\n"
                f"🔑 TxID: {r['txid']}",
                reply_markup=kb
            )
        return

    if data == "admin_stock":
        await query.message.reply_text(
            "📦 Stock\n\n"
            f"🌐 Proxy: {len(DATA['proxy']['stock'])}\n"
            f"🌐 VPN: {len(DATA['vpn']['stock'])}"
        )
        return

    if data == "proxy_settings":
        p = DATA["proxy"]
        await query.message.reply_text(
            "⚙️ Proxy Settings\n\n"
            f"Name: {p['name']}\n"
            f"MB: {p['mb']}\n"
            f"Price: {money(p['price'])}\n\n"
            "/setproxyname ...\n"
            "/setproxymb 200\n"
            "/setproxyprice 10"
        )
        return

    if data == "vpn_settings":
        v = DATA["vpn"]
        await query.message.reply_text(
            "⚙️ VPN Settings\n\n"
            f"Name: {v['name']}\n"
            f"Days: {v['days']}\n"
            f"Price: {money(v['price'])}\n\n"
            "/setvpnname ...\n"
            "/setvpndays 30\n"
            "/setvpnprice 50"
        )
        return

    if data == "admin_stats":
        await query.message.reply_text(
            "📊 Statistics\n\n"
            f"👥 Users: {len(DATA['users'])}\n"
            f"🧾 Orders: {len(DATA['orders'])}\n"
            f"📦 Proxy: {len(DATA['proxy']['stock'])}\n"
            f"📦 VPN: {len(DATA['vpn']['stock'])}"
        )
        return

    if data.startswith("accept_dep_"):
        did = data.removeprefix("accept_dep_")
        req = DATA["deposit_requests"].get(did)
        if not req or req["status"] != "pending":
            await query.message.reply_text("⚠️ Request already processed/not found.")
            return

        uid2 = str(req["user_id"])
        DATA["balance"][uid2] = round(
            float(DATA["balance"].get(uid2, 0)) + float(req["amount"]), 2
        )
        req["status"] = "accepted"
        req["accepted_at"] = datetime.now().isoformat(timespec="seconds")
        save_data(DATA)

        await query.message.reply_text(
            f"✅ Deposit #{did} accepted.\n"
            f"💳 Added: {money(req['amount'])}"
        )
        await safe_send(
            context,
            req["user_id"],
            "✅ Payment Verified!\n\n"
            f"💰 Added: {money(req['amount'])}\n"
            f"💳 Current Balance: {money(DATA['balance'][uid2])}"
        )
        return

    if data.startswith("reject_dep_"):
        did = data.removeprefix("reject_dep_")
        req = DATA["deposit_requests"].get(did)
        if not req or req["status"] != "pending":
            await query.message.reply_text("⚠️ Request already processed/not found.")
            return

        req["status"] = "rejected"
        req["rejected_at"] = datetime.now().isoformat(timespec="seconds")
        save_data(DATA)

        await query.message.reply_text(f"❌ Deposit #{did} rejected.")
        await safe_send(
            context,
            req["user_id"],
            "❌ Payment Verification Failed\n\n"
            f"💰 Amount: {money(req['amount'])}\n"
            f"🔑 TxID: {req['txid']}\n\n"
            "Payment verify করা যায়নি, তাই balance add করা হয়নি।"
        )
        return


# ============================================================
# GENERAL TEXT ROUTER
# ============================================================

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    # Admin bulk stock gets priority.
    if await bulk_stock_message(update, context):
        return

    # Deposit amount / TxID flows.
    if await handle_deposit_amount(update, context):
        return
    if await handle_txid(update, context):
        return

    text = update.message.text.strip()

    if text == "🟢 Buy Proxy":
        await show_proxy(update, context)
    elif text == "🟢 Buy VPN":
        await show_vpn(update, context)
    elif text == "🟢 Add Money":
        await add_money_start(update, context)
    elif text == "🟣 Profile":
        await profile(update, context)
    elif text == "🟢 Help":
        await help_user(update, context)


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):
    logging.exception("Unhandled bot error", exc_info=context.error)


# ============================================================
# MAIN
# ============================================================

def main():
    if BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE" or not BOT_TOKEN:
        raise RuntimeError(
            "Set BOT_TOKEN in Render Environment Variables."
        )
    if ADMIN_ID == 0:
        raise RuntimeError(
            "Set ADMIN_ID in Render Environment Variables."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("helpadmin", admin_help))

    # Admin command handler must run before generic text handler.
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.User(user_id=ADMIN_ID),
            admin_command
        )
    )

    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)

    logging.info("Bot started.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
