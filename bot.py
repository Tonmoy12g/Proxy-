"""
TrustVault Store - Telegram Shop Bot
=====================================
Sells digital stock items (Proxy / VPN / Gmail Accounts) with a manual
bKash deposit system, stock-based instant delivery, and a full inline
admin panel.

Requirements: python-telegram-bot==22.5 (v20+ async API)

Configuration is done via environment variables (recommended) or by
editing the CONFIG section below directly:

    BOT_TOKEN   - your Telegram bot token from @BotFather
    ADMIN_IDS   - comma-separated Telegram user IDs allowed to use /admin

Run:
    pip install -r requirements.txt
    export BOT_TOKEN="8805001071:AAFe5ORvRD5QAqH3eU4sCAbT9GjlfmBm8QM"
    export ADMIN_IDS="8001997389"
    python bot.py

All persistent state (users, stock, prices, settings, orders, deposits)
lives in data.json next to this file and is loaded/saved automatically,
so nothing is lost on restart.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --------------------------------------------------------------------------- #
# CONFIG
# --------------------------------------------------------------------------- #

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
}

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

DEFAULT_STORE_NAME = "TrustVault Store"

PRODUCTS = {
    "proxy": "Proxy",
    "vpn": "VPN",
    "gmail": "Gmail Account",
}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# DATA LAYER (simple JSON file persistence)
# --------------------------------------------------------------------------- #

DEFAULT_DATA: Dict[str, Any] = {
    "users": {},        # user_id(str) -> {balance, banned, username, first_name, joined, orders: [order_id,...]}
    "stock": {k: [] for k in PRODUCTS},       # product -> list of stock strings
    "prices": {k: 0 for k in PRODUCTS},       # product -> price (in BDT)
    "settings": {
        "bkash_number": "Not set",
        "support_username": "Not set",
        "help_text": "",                 # custom extra help text, optional
        "withdrawal_info": "Not set",    # admin's own reference note, never shown to users
        "store_name": DEFAULT_STORE_NAME,
        "welcome_message": "",           # custom welcome text, optional (overrides default)
        "vpn_duration_days": 0,          # 0 = not set / unlimited
    },
    "orders": [],        # list of order dicts
    "deposits": {},       # deposit_id -> {user_id, amount, txid, status, time}
    "next_order_id": 1,
}


def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return json.loads(json.dumps(DEFAULT_DATA))
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Ensure any missing keys added in later versions exist
    for key, default_val in DEFAULT_DATA.items():
        if key not in data:
            data[key] = json.loads(json.dumps(default_val))
    for k, v in DEFAULT_DATA["settings"].items():
        data["settings"].setdefault(k, v)
    for p in PRODUCTS:
        data["stock"].setdefault(p, [])
        data["prices"].setdefault(p, 0)
    return data


def save_data(data: Dict[str, Any]) -> None:
    tmp_file = DATA_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_file, DATA_FILE)


DATA: Dict[str, Any] = load_data()


def persist() -> None:
    save_data(DATA)


def store_name() -> str:
    return DATA["settings"].get("store_name") or DEFAULT_STORE_NAME


def get_user(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> Dict[str, Any]:
    uid = str(user_id)
    if uid not in DATA["users"]:
        DATA["users"][uid] = {
            "balance": 0,
            "banned": False,
            "username": username or "",
            "first_name": first_name or "",
            "joined": int(time.time()),
            "orders": [],
        }
        persist()
    else:
        changed = False
        if username and DATA["users"][uid].get("username") != username:
            DATA["users"][uid]["username"] = username
            changed = True
        if first_name and DATA["users"][uid].get("first_name") != first_name:
            DATA["users"][uid]["first_name"] = first_name
            changed = True
        if changed:
            persist()
    return DATA["users"][uid]


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def fmt_money(amount: float) -> str:
    return f"৳{amount:,.2f}"


# --------------------------------------------------------------------------- #
# REPLY KEYBOARD (user-facing main menu)
# --------------------------------------------------------------------------- #

BTN_BUY_PROXY = "🟢 Buy Proxy"
BTN_BUY_VPN = "🟢 Buy VPN"
BTN_BUY_GMAIL = "🟢 Buy Gmail Account"
BTN_ADD_MONEY = "🟢 Add Money"
BTN_PROFILE = "🟣 Profile"
BTN_HELP = "🟢 Help"

MAIN_MENU_BUTTONS = [
    [BTN_BUY_PROXY, BTN_BUY_VPN, BTN_BUY_GMAIL],
    [BTN_ADD_MONEY, BTN_PROFILE],
    [BTN_HELP],
]


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(b) for b in row] for row in MAIN_MENU_BUTTONS],
        resize_keyboard=True,
    )


# --------------------------------------------------------------------------- #
# PENDING-INPUT STATE MACHINE
# --------------------------------------------------------------------------- #
# For simple one-shot text prompts (admin flows, deposit flow) we track what
# we're waiting for in context.user_data["awaiting"] rather than a full
# ConversationHandler per action - this keeps the many admin flows compact.

def set_awaiting(context: ContextTypes.DEFAULT_TYPE, action: str, **extra: Any) -> None:
    context.user_data["awaiting"] = {"action": action, **extra}


def clear_awaiting(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting", None)


# --------------------------------------------------------------------------- #
# USER COMMANDS
# --------------------------------------------------------------------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_user(user.id, user.username, user.first_name)
    clear_awaiting(context)
    custom_welcome = DATA["settings"].get("welcome_message")
    if custom_welcome:
        text = custom_welcome
    else:
        text = (
            f"👋 Welcome to *{store_name()}*!\n\n"
            "We sell Proxy, VPN and Gmail Accounts with instant delivery.\n\n"
            "Use the menu below to get started."
        )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = DATA["settings"]
    extra = settings.get("help_text") or ""
    text = (
        f"*{store_name()} - Help*\n\n"
        "• *Buy Proxy / Buy VPN / Buy Gmail Account* - purchase stock instantly "
        "(balance is deducted automatically).\n"
        "• *Add Money* - top up your balance via bKash.\n"
        "• *Profile* - view your balance and order history.\n\n"
        f"Support: {settings.get('support_username', 'Not set')}"
    )
    if extra:
        text += f"\n\n{extra}"
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    u = get_user(user.id, user.username, user.first_name)
    orders = u.get("orders", [])
    text = (
        f"👤 *Your Profile*\n\n"
        f"User ID: `{user.id}`\n"
        f"Balance: {fmt_money(u['balance'])}\n"
        f"Total Orders: {len(orders)}\n"
        f"Status: {'🚫 Banned' if u.get('banned') else '✅ Active'}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def add_money(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = DATA["settings"]
    text = (
        "💰 *Add Money via bKash*\n\n"
        f"Send payment to bKash number: `{settings.get('bkash_number', 'Not set')}` (Send Money)\n\n"
        "Then reply with your deposit in this exact format:\n"
        "`AMOUNT TXID`\n\n"
        "Example: `500 8N7A2K9XYZ`"
    )
    set_awaiting(context, "deposit_submit")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE, product_key: str) -> None:
    user = update.effective_user
    u = get_user(user.id, user.username, user.first_name)

    if u.get("banned"):
        await update.message.reply_text("🚫 Your account is banned. Contact support.")
        return

    price = DATA["prices"].get(product_key, 0)
    stock_list: List[str] = DATA["stock"].get(product_key, [])
    product_label = PRODUCTS[product_key]

    if price <= 0:
        await update.message.reply_text(f"⚠️ {product_label} is not available for purchase right now.")
        return

    if not stock_list:
        await update.message.reply_text(f"❌ Sorry, *{product_label}* is currently out of stock.", parse_mode=ParseMode.MARKDOWN)
        return

    if u["balance"] < price:
        await update.message.reply_text(
            f"❌ Insufficient balance.\n\n"
            f"{product_label} price: {fmt_money(price)}\n"
            f"Your balance: {fmt_money(u['balance'])}\n\n"
            "Use *Add Money* to top up.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Deduct balance and pop stock item atomically (single-process assumption)
    item = stock_list.pop(0)
    u["balance"] -= price

    order_id = DATA["next_order_id"]
    DATA["next_order_id"] += 1
    order = {
        "id": order_id,
        "user_id": user.id,
        "username": user.username or "",
        "product": product_key,
        "product_label": product_label,
        "price": price,
        "time": int(time.time()),
    }
    DATA["orders"].append(order)
    u["orders"].append(order_id)
    persist()

    extra_line = ""
    if product_key == "vpn":
        days = DATA["settings"].get("vpn_duration_days", 0)
        if days:
            extra_line = f"Validity: {days} day(s)\n"

    await update.message.reply_text(
        f"✅ *Purchase Successful!*\n\n"
        f"Product: {product_label}\n"
        f"Price: {fmt_money(price)}\n"
        f"{extra_line}"
        f"Remaining Balance: {fmt_money(u['balance'])}\n\n"
        f"Your item:\n`{item}`",
        parse_mode=ParseMode.MARKDOWN,
    )


# --------------------------------------------------------------------------- #
# TEXT ROUTER (reply-keyboard buttons + pending text inputs)
# --------------------------------------------------------------------------- #

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    user = update.effective_user
    get_user(user.id, user.username, user.first_name)

    awaiting = context.user_data.get("awaiting")
    if awaiting:
        await handle_awaiting_input(update, context, awaiting, text)
        return

    if text == BTN_BUY_PROXY:
        await buy_product(update, context, "proxy")
    elif text == BTN_BUY_VPN:
        await buy_product(update, context, "vpn")
    elif text == BTN_BUY_GMAIL:
        await buy_product(update, context, "gmail")
    elif text == BTN_ADD_MONEY:
        await add_money(update, context)
    elif text == BTN_PROFILE:
        await profile(update, context)
    elif text == BTN_HELP:
        await help_command(update, context)
    else:
        await update.message.reply_text(
            "Please use the menu buttons below.", reply_markup=main_menu_keyboard()
        )


async def handle_awaiting_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: Dict[str, Any], text: str
) -> None:
    action = awaiting.get("action")
    user = update.effective_user

    # ---------------- User-side: deposit submission ---------------- #
    if action == "deposit_submit":
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Invalid format. Please send as: `AMOUNT TXID`", parse_mode=ParseMode.MARKDOWN
            )
            return
        amount_str, txid = parts[0], " ".join(parts[1:])
        try:
            amount = float(amount_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please try again with: `AMOUNT TXID`", parse_mode=ParseMode.MARKDOWN)
            return

        deposit_id = uuid.uuid4().hex[:10]
        DATA["deposits"][deposit_id] = {
            "user_id": user.id,
            "username": user.username or "",
            "amount": amount,
            "txid": txid,
            "status": "pending",
            "time": int(time.time()),
        }
        persist()
        clear_awaiting(context)

        await update.message.reply_text(
            "✅ Your deposit request has been submitted and is pending admin approval.\n"
            f"Amount: {fmt_money(amount)}\nTxID: `{txid}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        admin_text = (
            "🆕 *New Deposit Request*\n\n"
            f"User: {user.first_name} (`{user.id}`)\n"
            f"Username: @{user.username if user.username else 'N/A'}\n"
            f"Amount: {fmt_money(amount)}\n"
            f"TxID: `{txid}`"
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Accept", callback_data=f"dep_accept:{deposit_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"dep_reject:{deposit_id}"),
                ]
            ]
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, admin_text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
            except Exception:
                logger.exception("Failed to notify admin %s", admin_id)
        return

    # ---------------- Admin-side flows ---------------- #
    if not is_admin(user.id):
        clear_awaiting(context)
        return

    if action == "admin_add_balance":
        await admin_apply_balance_change(update, context, text, add=True)
    elif action == "admin_deduct_balance":
        await admin_apply_balance_change(update, context, text, add=False)
    elif action == "admin_add_stock":
        await admin_apply_add_stock(update, context, text, awaiting["product"])
    elif action == "admin_clear_stock_confirm":
        await admin_apply_clear_stock(update, context, text, awaiting["product"])
    elif action == "admin_set_price":
        await admin_apply_set_price(update, context, text, awaiting["product"])
    elif action == "admin_set_bkash":
        DATA["settings"]["bkash_number"] = text.strip()
        persist()
        clear_awaiting(context)
        await update.message.reply_text(f"✅ bKash number updated to: `{text.strip()}`", parse_mode=ParseMode.MARKDOWN)
    elif action == "admin_set_support":
        DATA["settings"]["support_username"] = text.strip()
        persist()
        clear_awaiting(context)
        await update.message.reply_text(f"✅ Support username updated to: {text.strip()}")
    elif action == "admin_set_help_text":
        DATA["settings"]["help_text"] = text.strip()
        persist()
        clear_awaiting(context)
        await update.message.reply_text("✅ Custom help text updated.")
    elif action == "admin_set_withdrawal_info":
        DATA["settings"]["withdrawal_info"] = text.strip()
        persist()
        clear_awaiting(context)
        await update.message.reply_text("✅ Withdrawal info updated (admin-only note).")
    elif action == "admin_set_store_name":
        DATA["settings"]["store_name"] = text.strip()
        persist()
        clear_awaiting(context)
        await update.message.reply_text(f"✅ Store name updated to: {text.strip()}")
    elif action == "admin_set_welcome_message":
        DATA["settings"]["welcome_message"] = text.strip()
        persist()
        clear_awaiting(context)
        await update.message.reply_text("✅ Welcome message updated.")
    elif action == "admin_set_vpn_duration":
        try:
            days = int(text.strip())
            if days < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Please send a whole number of days (0 = unlimited/not set).")
            return
        DATA["settings"]["vpn_duration_days"] = days
        persist()
        clear_awaiting(context)
        await update.message.reply_text(f"✅ VPN duration set to {days} day(s).")
    elif action == "admin_ban_user":
        await admin_apply_ban(update, context, text, ban=True)
    elif action == "admin_unban_user":
        await admin_apply_ban(update, context, text, ban=False)
    elif action == "admin_broadcast":
        await admin_apply_broadcast(update, context, text)
    else:
        clear_awaiting(context)


# --------------------------------------------------------------------------- #
# ADMIN: balance management
# --------------------------------------------------------------------------- #

async def admin_apply_balance_change(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, add: bool) -> None:
    parts = text.split()
    if len(parts) != 2:
        await update.message.reply_text("❌ Format: `USER_ID AMOUNT`", parse_mode=ParseMode.MARKDOWN)
        return
    uid_str, amount_str = parts
    try:
        target_uid = int(uid_str)
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Format: `USER_ID AMOUNT`", parse_mode=ParseMode.MARKDOWN)
        return

    u = DATA["users"].get(str(target_uid))
    if u is None:
        await update.message.reply_text("❌ User not found (they must /start the bot first).")
        return

    if add:
        u["balance"] += amount
        verb = "added to"
    else:
        u["balance"] -= amount
        verb = "deducted from"
    persist()
    clear_awaiting(context)

    await update.message.reply_text(
        f"✅ {fmt_money(amount)} {verb} user `{target_uid}`.\nNew balance: {fmt_money(u['balance'])}",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        await context.bot.send_message(
            target_uid,
            f"💳 Your balance has been updated by an admin.\nNew balance: {fmt_money(u['balance'])}",
        )
    except Exception:
        logger.exception("Could not DM user %s about balance change", target_uid)


# --------------------------------------------------------------------------- #
# ADMIN: stock management (Add / Count / Delete)
# --------------------------------------------------------------------------- #

STOCK_FORMAT_HINTS = {
    "proxy": "Example:\n`ip:port:user:pass`",
    "vpn": "Example:\n`config_or_credentials_here`",
    "gmail": "Example (one per line):\n`emailaddress@gmail.com:password`",
}


async def admin_apply_add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, product: str) -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        await update.message.reply_text("❌ No valid lines found. Please send one stock item per line.")
        return
    DATA["stock"][product].extend(lines)
    persist()
    clear_awaiting(context)
    await update.message.reply_text(
        f"✅ Added {len(lines)} item(s) to *{PRODUCTS[product]}* stock.\n"
        f"Current stock count: {len(DATA['stock'][product])}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_apply_clear_stock(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, product: str) -> None:
    clear_awaiting(context)
    if text.strip().upper() != "CONFIRM":
        await update.message.reply_text("Cancelled. Stock was not cleared.")
        return
    DATA["stock"][product] = []
    persist()
    await update.message.reply_text(f"✅ Stock cleared for *{PRODUCTS[product]}*.", parse_mode=ParseMode.MARKDOWN)


async def admin_apply_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, product: str) -> None:
    try:
        price = float(text.strip())
        if price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Please send a number.")
        return
    DATA["prices"][product] = price
    persist()
    clear_awaiting(context)
    await update.message.reply_text(f"✅ Price for *{PRODUCTS[product]}* set to {fmt_money(price)}.", parse_mode=ParseMode.MARKDOWN)


# --------------------------------------------------------------------------- #
# ADMIN: user control
# --------------------------------------------------------------------------- #

async def admin_apply_ban(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, ban: bool) -> None:
    try:
        target_uid = int(text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please send a valid numeric User ID.")
        return
    u = DATA["users"].get(str(target_uid))
    if u is None:
        await update.message.reply_text("❌ User not found.")
        return
    u["banned"] = ban
    persist()
    clear_awaiting(context)
    await update.message.reply_text(f"✅ User `{target_uid}` has been {'banned' if ban else 'unbanned'}.", parse_mode=ParseMode.MARKDOWN)


# --------------------------------------------------------------------------- #
# ADMIN: broadcast
# --------------------------------------------------------------------------- #

async def admin_apply_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    clear_awaiting(context)
    sent, failed = 0, 0
    for uid_str in list(DATA["users"].keys()):
        try:
            await context.bot.send_message(int(uid_str), f"📢 *Announcement*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ Broadcast complete. Sent: {sent}, Failed: {failed}")


# --------------------------------------------------------------------------- #
# ADMIN PANEL - main inline menu (matches the requested layout)
# --------------------------------------------------------------------------- #

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    clear_awaiting(context)
    await update.message.reply_text(
        "👨‍💻 *Admin Panel*", parse_mode=ParseMode.MARKDOWN, reply_markup=admin_main_keyboard()
    )


def admin_main_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📊 Dashboard / Statistics", callback_data="adm:dashboard")],
        [InlineKeyboardButton("💰 User Balance Manage", callback_data="adm:balance")],
        [InlineKeyboardButton("📦 Proxy Stock", callback_data="adm:proxy_stock")],
        [InlineKeyboardButton("🌐 VPN Stock", callback_data="adm:vpn_stock")],
        [InlineKeyboardButton("📧 Gmail Product", callback_data="adm:gmail_product")],
        [InlineKeyboardButton("💵 Product Price Settings", callback_data="adm:price_settings")],
        [InlineKeyboardButton("📅 VPN Duration Settings", callback_data="adm:vpn_duration")],
        [InlineKeyboardButton("📈 Sales History", callback_data="adm:sales_history")],
        [InlineKeyboardButton("🧾 Order History", callback_data="adm:order_history:0")],
        [InlineKeyboardButton("👥 User List", callback_data="adm:user_list:0")],
        [InlineKeyboardButton("🚫 Ban / Unban User", callback_data="adm:ban_unban")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm:broadcast")],
        [InlineKeyboardButton("📊 Stock Count", callback_data="adm:stock_count")],
        [InlineKeyboardButton("🗑️ Delete Stock", callback_data="adm:delete_stock")],
        [InlineKeyboardButton("💳 Payment Settings", callback_data="adm:payment_settings")],
        [InlineKeyboardButton("💸 Withdrawal Settings", callback_data="adm:withdrawal_settings")],
        [InlineKeyboardButton("🆘 Help Settings", callback_data="adm:help_settings")],
        [InlineKeyboardButton("⚙️ Bot Settings", callback_data="adm:bot_settings")],
    ]
    return InlineKeyboardMarkup(rows)


def back_button(target: str = "adm:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=target)]])


async def admin_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user

    if query.data.startswith("dep_accept:") or query.data.startswith("dep_reject:"):
        if not is_admin(user.id):
            await query.answer("Not authorized.", show_alert=True)
            return
        await handle_deposit_decision(update, context)
        return

    if not is_admin(user.id):
        await query.answer("⛔ Not authorized.", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == "adm:main":
        await query.edit_message_text("👨‍💻 *Admin Panel*", parse_mode=ParseMode.MARKDOWN, reply_markup=admin_main_keyboard())
    elif data == "adm:dashboard":
        await show_dashboard(update, context)
    elif data == "adm:balance":
        await show_balance_menu(update, context)
    elif data == "adm:proxy_stock":
        await show_product_stock_menu(update, context, "proxy")
    elif data == "adm:vpn_stock":
        await show_product_stock_menu(update, context, "vpn")
    elif data == "adm:gmail_product":
        await show_product_stock_menu(update, context, "gmail")
    elif data == "adm:price_settings":
        await show_price_settings_menu(update, context)
    elif data == "adm:vpn_duration":
        await show_vpn_duration_menu(update, context)
    elif data == "adm:sales_history":
        await show_sales_history(update, context)
    elif data.startswith("adm:order_history:"):
        page = int(data.split(":")[2])
        await show_order_history(update, context, page=page)
    elif data.startswith("adm:user_list:"):
        page = int(data.split(":")[2])
        await show_user_list(update, context, page=page)
    elif data == "adm:ban_unban":
        await show_ban_unban_menu(update, context)
    elif data == "adm:broadcast":
        set_awaiting(context, "admin_broadcast")
        await query.edit_message_text(
            "📢 Send the message you want to broadcast to *all* users.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button(),
        )
    elif data == "adm:stock_count":
        await show_stock_count(update, context)
    elif data == "adm:delete_stock":
        await show_delete_stock_menu(update, context)
    elif data == "adm:payment_settings":
        await show_payment_settings_menu(update, context)
    elif data == "adm:withdrawal_settings":
        await show_withdrawal_settings_menu(update, context)
    elif data == "adm:help_settings":
        await show_help_settings_menu(update, context)
    elif data == "adm:bot_settings":
        await show_bot_settings_menu(update, context)
    elif data.startswith("bal:"):
        await handle_balance_action(update, context, data)
    elif data.startswith("pstock:"):
        await handle_product_stock_action(update, context, data)
    elif data.startswith("price:"):
        await handle_price_action(update, context, data)
    elif data.startswith("delstock:"):
        await handle_delete_stock_action(update, context, data)
    elif data.startswith("ban:"):
        await handle_ban_unban_action(update, context, data)
    elif data.startswith("pay:"):
        await handle_payment_settings_action(update, context, data)
    elif data.startswith("wd:"):
        await handle_withdrawal_settings_action(update, context, data)
    elif data.startswith("hlp:"):
        await handle_help_settings_action(update, context, data)
    elif data.startswith("bset:"):
        await handle_bot_settings_action(update, context, data)


# ---- Dashboard / Statistics ---- #

async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    total_users = len(DATA["users"])
    total_orders = len(DATA["orders"])
    total_revenue = sum(o["price"] for o in DATA["orders"])
    pending_deposits = sum(1 for d in DATA["deposits"].values() if d["status"] == "pending")
    banned = sum(1 for u in DATA["users"].values() if u.get("banned"))

    stock_summary = "\n".join(
        f"  • {PRODUCTS[p]}: {len(DATA['stock'][p])} in stock" for p in PRODUCTS
    )

    text = (
        "📊 *Dashboard / Statistics*\n\n"
        f"Total Users: {total_users}\n"
        f"Banned Users: {banned}\n"
        f"Total Orders: {total_orders}\n"
        f"Total Revenue: {fmt_money(total_revenue)}\n"
        f"Pending Deposits: {pending_deposits}\n\n"
        f"*Stock:*\n{stock_summary}"
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_button())


# ---- User Balance Manage ---- #

def balance_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Add Balance", callback_data="bal:add")],
            [InlineKeyboardButton("➖ Deduct Balance", callback_data="bal:deduct")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:main")],
        ]
    )


async def show_balance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.edit_message_text(
        "💰 *User Balance Manage*\n\nChoose an action:", parse_mode=ParseMode.MARKDOWN, reply_markup=balance_menu_keyboard()
    )


async def handle_balance_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    if data == "bal:add":
        set_awaiting(context, "admin_add_balance")
        await query.edit_message_text(
            "➕ Send: `USER_ID AMOUNT` to add balance.\nExample: `123456789 500`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("adm:balance"),
        )
    elif data == "bal:deduct":
        set_awaiting(context, "admin_deduct_balance")
        await query.edit_message_text(
            "➖ Send: `USER_ID AMOUNT` to deduct balance.\nExample: `123456789 200`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("adm:balance"),
        )


# ---- Proxy Stock / VPN Stock / Gmail Product (per-product add-stock menus) ---- #

def product_stock_menu_keyboard(product: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"➕ Add {PRODUCTS[product]} Stock", callback_data=f"pstock:add:{product}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:main")],
        ]
    )


async def show_product_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, product: str) -> None:
    label = PRODUCTS[product]
    count = len(DATA["stock"][product])
    price = DATA["prices"][product]
    icon = {"proxy": "📦", "vpn": "🌐", "gmail": "📧"}[product]
    text = (
        f"{icon} *{label} {'Stock' if product != 'gmail' else 'Product'}*\n\n"
        f"Current stock: {count}\n"
        f"Current price: {fmt_money(price)}"
    )
    await update.callback_query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=product_stock_menu_keyboard(product)
    )


async def handle_product_stock_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    _, action, product = data.split(":")
    label = PRODUCTS[product]

    if action == "add":
        set_awaiting(context, "admin_add_stock", product=product)
        hint = STOCK_FORMAT_HINTS.get(product, "")
        await query.edit_message_text(
            f"➕ Send stock lines for *{label}* (one item per line).\n\n{hint}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button(f"adm:{'proxy_stock' if product == 'proxy' else ('vpn_stock' if product == 'vpn' else 'gmail_product')}"),
        )


# ---- Product Price Settings ---- #

def price_settings_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"💵 Set {PRODUCTS[p]} Price", callback_data=f"price:{p}")] for p in PRODUCTS]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:main")])
    return InlineKeyboardMarkup(rows)


async def show_price_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_lines = "\n".join(f"  • {PRODUCTS[p]}: {fmt_money(DATA['prices'][p])}" for p in PRODUCTS)
    text = f"💵 *Product Price Settings*\n\n{price_lines}"
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=price_settings_menu_keyboard())


async def handle_price_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    product = data.split(":")[1]
    set_awaiting(context, "admin_set_price", product=product)
    await query.edit_message_text(
        f"💵 Send the new price for *{PRODUCTS[product]}* (number only).",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_button("adm:price_settings"),
    )


# ---- VPN Duration Settings ---- #

async def show_vpn_duration_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current = DATA["settings"].get("vpn_duration_days", 0)
    text = (
        "📅 *VPN Duration Settings*\n\n"
        f"Current validity: {current if current else 'Not set'} day(s)\n\n"
        "This is shown to users when they purchase a VPN."
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Set Duration (days)", callback_data="vpndur:set")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:main")],
        ]
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def handle_vpn_duration_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    if data == "vpndur:set":
        set_awaiting(context, "admin_set_vpn_duration")
        await query.edit_message_text(
            "📅 Send the VPN validity in whole days (e.g. `30`). Send `0` for unlimited/not set.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("adm:vpn_duration"),
        )


# ---- Sales History (aggregated) ---- #

async def show_sales_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    per_product: Dict[str, Dict[str, float]] = {p: {"count": 0, "revenue": 0.0} for p in PRODUCTS}
    for o in DATA["orders"]:
        p = o["product"]
        if p in per_product:
            per_product[p]["count"] += 1
            per_product[p]["revenue"] += o["price"]

    total_orders = len(DATA["orders"])
    total_revenue = sum(o["price"] for o in DATA["orders"])

    lines = [f"  • {PRODUCTS[p]}: {int(v['count'])} sold, {fmt_money(v['revenue'])} revenue" for p, v in per_product.items()]

    text = (
        "📈 *Sales History*\n\n"
        f"Total Orders: {total_orders}\n"
        f"Total Revenue: {fmt_money(total_revenue)}\n\n"
        "*By Product:*\n" + "\n".join(lines)
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_button())


# ---- Order History (chronological log) ---- #

ORDERS_PER_PAGE = 10


async def show_order_history(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    orders = list(reversed(DATA["orders"]))
    start = page * ORDERS_PER_PAGE
    chunk = orders[start:start + ORDERS_PER_PAGE]

    if not chunk:
        text = "🧾 *Order History*\n\nNo orders yet."
        rows = [[InlineKeyboardButton("⬅️ Back", callback_data="adm:main")]]
    else:
        lines = []
        for o in chunk:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(o["time"]))
            lines.append(
                f"#{o['id']} | {o['product_label']} | {fmt_money(o['price'])} | "
                f"user `{o['user_id']}` | {ts}"
            )
        text = f"🧾 *Order History* (page {page + 1})\n\n" + "\n".join(lines)
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm:order_history:{page - 1}"))
        if start + ORDERS_PER_PAGE < len(orders):
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"adm:order_history:{page + 1}"))
        rows = [nav_row] if nav_row else []
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:main")])

    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))


# ---- User List ---- #

USERS_PER_PAGE = 10


async def show_user_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    all_users = list(DATA["users"].items())
    start = page * USERS_PER_PAGE
    chunk = all_users[start:start + USERS_PER_PAGE]

    if not chunk:
        text = "👥 *User List*\n\nNo users found."
    else:
        lines = []
        for uid, u in chunk:
            status = "🚫" if u.get("banned") else "✅"
            uname = f"@{u['username']}" if u.get("username") else "N/A"
            lines.append(f"{status} `{uid}` {uname} - {fmt_money(u['balance'])}")
        text = f"👥 *User List* (page {page + 1})\n\n" + "\n".join(lines)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm:user_list:{page - 1}"))
    if start + USERS_PER_PAGE < len(all_users):
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"adm:user_list:{page + 1}"))
    rows = [nav_row] if nav_row else []
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:main")])
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))


# ---- Ban / Unban User ---- #

def ban_unban_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚫 Ban User", callback_data="ban:ban")],
            [InlineKeyboardButton("✅ Unban User", callback_data="ban:unban")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:main")],
        ]
    )


async def show_ban_unban_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.edit_message_text(
        "🚫 *Ban / Unban User*", parse_mode=ParseMode.MARKDOWN, reply_markup=ban_unban_menu_keyboard()
    )


async def handle_ban_unban_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    if data == "ban:ban":
        set_awaiting(context, "admin_ban_user")
        await query.edit_message_text("🚫 Send the User ID to ban.", reply_markup=back_button("adm:ban_unban"))
    elif data == "ban:unban":
        set_awaiting(context, "admin_unban_user")
        await query.edit_message_text("✅ Send the User ID to unban.", reply_markup=back_button("adm:ban_unban"))


# ---- Stock Count (all products) ---- #

async def show_stock_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = "\n".join(f"  • {PRODUCTS[p]}: {len(DATA['stock'][p])} in stock" for p in PRODUCTS)
    text = f"📊 *Stock Count*\n\n{lines}"
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_button())


# ---- Delete Stock (choose product, then confirm) ---- #

def delete_stock_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"🗑️ Delete {PRODUCTS[p]} Stock", callback_data=f"delstock:{p}")] for p in PRODUCTS]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:main")])
    return InlineKeyboardMarkup(rows)


async def show_delete_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.edit_message_text(
        "🗑️ *Delete Stock*\n\nChoose a product to clear its stock completely:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=delete_stock_menu_keyboard(),
    )


async def handle_delete_stock_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    product = data.split(":")[1]
    label = PRODUCTS[product]
    set_awaiting(context, "admin_clear_stock_confirm", product=product)
    await query.edit_message_text(
        f"⚠️ This will permanently clear all *{label}* stock "
        f"({len(DATA['stock'][product])} items).\n\nType `CONFIRM` to proceed, or anything else to cancel.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_button("adm:delete_stock"),
    )


# ---- Payment Settings (bKash deposit number) ---- #

async def show_payment_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current = DATA["settings"].get("bkash_number", "Not set")
    text = f"💳 *Payment Settings*\n\nCurrent bKash number: `{current}`"
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Set bKash Number", callback_data="pay:set_bkash")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:main")],
        ]
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def handle_payment_settings_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    if data == "pay:set_bkash":
        set_awaiting(context, "admin_set_bkash")
        await query.edit_message_text(
            "📱 Send the new bKash number (shown to users for deposits).",
            reply_markup=back_button("adm:payment_settings"),
        )


# ---- Withdrawal Settings (admin-only reference note) ---- #

async def show_withdrawal_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current = DATA["settings"].get("withdrawal_info", "Not set")
    text = (
        "💸 *Withdrawal Settings*\n\n"
        f"Current note: `{current}`\n\n"
        "This is for your own reference (e.g. where you withdraw collected revenue) "
        "and is never shown to users."
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Set Withdrawal Info", callback_data="wd:set")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:main")],
        ]
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def handle_withdrawal_settings_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    if data == "wd:set":
        set_awaiting(context, "admin_set_withdrawal_info")
        await query.edit_message_text(
            "💸 Send your withdrawal reference info (account/agent number, notes, etc).",
            reply_markup=back_button("adm:withdrawal_settings"),
        )


# ---- Help Settings (support username + custom help text) ---- #

async def show_help_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = DATA["settings"]
    text = (
        "🆘 *Help Settings*\n\n"
        f"Support username: {settings.get('support_username', 'Not set')}\n"
        f"Custom help text: {settings.get('help_text') or '(none)'}"
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Set Support Username", callback_data="hlp:set_support")],
            [InlineKeyboardButton("✏️ Set Custom Help Text", callback_data="hlp:set_text")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:main")],
        ]
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def handle_help_settings_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    if data == "hlp:set_support":
        set_awaiting(context, "admin_set_support")
        await query.edit_message_text(
            "🆘 Send the new support username (e.g. @YourSupport).",
            reply_markup=back_button("adm:help_settings"),
        )
    elif data == "hlp:set_text":
        set_awaiting(context, "admin_set_help_text")
        await query.edit_message_text(
            "📝 Send the custom text to append to the /help message.",
            reply_markup=back_button("adm:help_settings"),
        )


# ---- Bot Settings (store name + welcome message) ---- #

async def show_bot_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = DATA["settings"]
    text = (
        "⚙️ *Bot Settings*\n\n"
        f"Store name: {store_name()}\n"
        f"Custom welcome message: {settings.get('welcome_message') or '(default)'}"
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Set Store Name", callback_data="bset:set_name")],
            [InlineKeyboardButton("✏️ Set Welcome Message", callback_data="bset:set_welcome")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:main")],
        ]
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def handle_bot_settings_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    if data == "bset:set_name":
        set_awaiting(context, "admin_set_store_name")
        await query.edit_message_text("🏪 Send the new store name.", reply_markup=back_button("adm:bot_settings"))
    elif data == "bset:set_welcome":
        set_awaiting(context, "admin_set_welcome_message")
        await query.edit_message_text(
            "👋 Send the new /start welcome message text.", reply_markup=back_button("adm:bot_settings")
        )


# --------------------------------------------------------------------------- #
# Route the remaining prefixed callbacks that need dedicated dispatch
# (vpndur: is handled here since it wasn't wired in the main if/elif chain
#  above to keep that chain readable)
# --------------------------------------------------------------------------- #

async def admin_callback_router_extra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = update.callback_query.data
    if data.startswith("vpndur:"):
        await handle_vpn_duration_action(update, context, data)


# --------------------------------------------------------------------------- #
# DEPOSIT ACCEPT / REJECT
# --------------------------------------------------------------------------- #

async def handle_deposit_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    decision, deposit_id = query.data.split(":")
    deposit = DATA["deposits"].get(deposit_id)

    if deposit is None:
        await query.answer("Deposit not found.", show_alert=True)
        return
    if deposit["status"] != "pending":
        await query.answer("This deposit was already processed.", show_alert=True)
        return

    await query.answer()
    target_uid = deposit["user_id"]

    if decision == "dep_accept":
        deposit["status"] = "approved"
        u = DATA["users"].get(str(target_uid))
        if u is not None:
            u["balance"] += deposit["amount"]
        persist()
        await query.edit_message_text(
            query.message.text + "\n\n✅ *APPROVED*", parse_mode=ParseMode.MARKDOWN
        )
        try:
            await context.bot.send_message(
                target_uid,
                f"✅ Your deposit of {fmt_money(deposit['amount'])} has been approved!\n"
                f"New balance: {fmt_money(u['balance']) if u else 'N/A'}",
            )
        except Exception:
            logger.exception("Could not notify user %s of approval", target_uid)
    else:
        deposit["status"] = "rejected"
        persist()
        await query.edit_message_text(
            query.message.text + "\n\n❌ *REJECTED*", parse_mode=ParseMode.MARKDOWN
        )
        try:
            await context.bot.send_message(
                target_uid,
                f"❌ Your deposit of {fmt_money(deposit['amount'])} (TxID: {deposit['txid']}) was rejected.\n"
                f"Please contact support if you believe this is a mistake.",
            )
        except Exception:
            logger.exception("Could not notify user %s of rejection", target_uid)


# --------------------------------------------------------------------------- #
# ERROR HANDLER
# --------------------------------------------------------------------------- #

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #

async def unified_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Single entry point registered with the dispatcher; delegates to the
    main admin router and picks up the small set of extra prefixes."""
    data = update.callback_query.data
    if data.startswith("vpndur:"):
        user = update.effective_user
        if not is_admin(user.id):
            await update.callback_query.answer("⛔ Not authorized.", show_alert=True)
            return
        await update.callback_query.answer()
        await handle_vpn_duration_action(update, context, data)
        return
    await admin_callback_router(update, context)


def main() -> None:
    if BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit(
            "Please set the BOT_TOKEN environment variable (or edit bot.py) before running."
        )
    if not ADMIN_IDS:
        logger.warning("No ADMIN_IDS configured - the admin panel will be inaccessible.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(unified_callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)

    logger.info("%s bot starting...", store_name())
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
