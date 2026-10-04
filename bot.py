import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PREMIUM_PRICE = int(os.getenv("PREMIUM_PRICE", "100"))
PREMIUM_DAYS = int(os.getenv("PREMIUM_DAYS", "30"))

DB_FILE = "signals.db"

# -------------------------
# Small web server for Render
# -------------------------

app = Flask(__name__)


@app.route("/")
def home():
    return "RobertFX AI Signals Bot is running!"


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# -------------------------
# Database
# -------------------------

def db():
    return sqlite3.connect(DB_FILE)


def setup_database():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            premium_until TEXT,
            last_free_signal TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            name TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


def register_user(user_id, username):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, premium_until, last_free_signal)
        VALUES (?, ?, NULL, NULL)
    """, (user_id, username))

    cur.execute(
        "UPDATE users SET username = ? WHERE user_id = ?",
        (username, user_id)
    )

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT premium_until, last_free_signal
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    result = cur.fetchone()
    conn.close()

    return result


def set_free_signal_time(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET last_free_signal = ?
        WHERE user_id = ?
    """, (
        datetime.now(timezone.utc).isoformat(),
        user_id
    ))

    conn.commit()
    conn.close()


def is_premium(user_id):
    user = get_user(user_id)

    if not user or not user[0]:
        return False

    try:
        expiry = datetime.fromisoformat(user[0])
        return expiry > datetime.now(timezone.utc)
    except Exception:
        return False


def set_premium(user_id):
    conn = db()
    cur = conn.cursor()

    result = cur.execute("""
        SELECT premium_until
        FROM users
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    now = datetime.now(timezone.utc)

    if result and result[0]:
        try:
            old_expiry = datetime.fromisoformat(result[0])
            start = old_expiry if old_expiry > now else now
        except Exception:
            start = now
    else:
        start = now

    expiry = start + timedelta(days=PREMIUM_DAYS)

    cur.execute("""
        UPDATE users
        SET premium_until = ?
        WHERE user_id = ?
    """, (expiry.isoformat(), user_id))

    conn.commit()
    conn.close()

    return expiry


def get_signal():
    conn = db()
    cur = conn.cursor()

    result = cur.execute("""
        SELECT value
        FROM settings
        WHERE name = 'latest_signal'
    """).fetchone()

    conn.close()

    if result:
        return result[0]

    return (
        "⚠️ <b>No signal published yet.</b>\n\n"
        "The administrator can publish one using:\n"
        "<code>/setsignal YOUR SIGNAL</code>"
    )


def set_signal(signal):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO settings (name, value)
        VALUES ('latest_signal', ?)
    """, (signal,))

    conn.commit()
    conn.close()


# -------------------------
# Start
# -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    register_user(
        user.id,
        user.username or user.first_name
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🆓 Get Free Signal",
                callback_data="free_signal"
            )
        ],
        [
            InlineKeyboardButton(
                "💎 Premium Signals",
                callback_data="premium"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Latest Signal",
                callback_data="latest"
            )
        ]
    ]

    await update.message.reply_text(
        "👋 <b>Welcome to RobertFX AI Signals</b>\n\n"
        "Forex & BTC trading signals delivered directly to Telegram.\n\n"
        "🆓 Free users receive 1 signal per day.\n"
        "💎 Premium members receive additional signals.\n\n"
        "⚠️ Trading involves risk. Signals are not guaranteed profits.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# -------------------------
# Buttons
# -------------------------

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "free_signal":

        if is_premium(user_id):
            await query.message.reply_text(
                "💎 You are a Premium member.\n\n"
                "You have access to Premium signals."
            )
            return

        user = get_user(user_id)

        last_signal = user[1] if user else None

        if last_signal:
            try:
                last_time = datetime.fromisoformat(last_signal)
                elapsed = datetime.now(timezone.utc) - last_time

                if elapsed < timedelta(hours=24):

                    remaining = timedelta(hours=24) - elapsed

                    hours = int(
                        remaining.total_seconds() // 3600
                    )

                    minutes = int(
                        (remaining.total_seconds() % 3600) // 60
                    )

                    await query.message.reply_text(
                        f"⏳ You've already received today's free signal.\n\n"
                        f"Next free signal in approximately "
                        f"{hours}h {minutes}m.\n\n"
                        f"💎 Use /premium for more signals."
                    )

                    return

            except Exception:
                pass

        set_free_signal_time(user_id)

        await query.message.reply_text(
            "🆓 <b>FREE DAILY SIGNAL</b>\n\n"
            + get_signal(),
            parse_mode="HTML"
        )

    elif query.data == "latest":

        await query.message.reply_text(
            get_signal(),
            parse_mode="HTML"
        )

    elif query.data == "premium":

        if is_premium(user_id):

            user = get_user(user_id)
            expiry = datetime.fromisoformat(user[0])

            await query.message.reply_text(
                "💎 <b>Premium Active</b>\n\n"
                f"Expires:\n"
                f"{expiry.strftime('%Y-%m-%d %H:%M UTC')}",
                parse_mode="HTML"
            )

        else:

            keyboard = [
                [
                    InlineKeyboardButton(
                        f"💳 Subscribe — {PREMIUM_PRICE} Stars",
                        callback_data="buy_premium"
                    )
                ]
            ]

            await query.message.reply_text(
                "💎 <b>Premium Signals</b>\n\n"
                "Get additional Forex & BTC signals.\n\n"
                f"📅 Duration: {PREMIUM_DAYS} days\n"
                f"💰 Price: {PREMIUM_PRICE} Telegram Stars\n\n"
                "Tap below to subscribe.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif query.data == "buy_premium":

        prices = [
            LabeledPrice(
                f"Premium — {PREMIUM_DAYS} days",
                PREMIUM_PRICE
            )
        ]

        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title="RobertFX Premium",
            description=(
                f"Premium Forex & BTC signals for "
                f"{PREMIUM_DAYS} days."
            ),
            payload=f"premium_{user_id}",
            currency="XTR",
            prices=prices
        )


# -------------------------
# Payment
# -------------------------

async def precheckout(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    expiry = set_premium(user_id)

    await update.message.reply_text(
        "✅ <b>Payment successful!</b>\n\n"
        "💎 Premium activated.\n\n"
        f"Premium expires:\n"
        f"{expiry.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "🚀 You now have access to Premium signals.",
        parse_mode="HTML"
    )


# -------------------------
# Premium command
# -------------------------

async def premium(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if is_premium(user_id):

        user = get_user(user_id)
        expiry = datetime.fromisoformat(user[0])

        await update.message.reply_text(
            "💎 Premium is active.\n\n"
            f"Expires: {expiry.strftime('%Y-%m-%d %H:%M UTC')}"
        )

        return

    keyboard = [
        [
            InlineKeyboardButton(
                f"💳 Subscribe — {PREMIUM_PRICE} Stars",
                callback_data="buy_premium"
            )
        ]
    ]

    await update.message.reply_text(
        "💎 <b>RobertFX Premium</b>\n\n"
        f"📅 {PREMIUM_DAYS} days\n"
        f"💰 {PREMIUM_PRICE} Telegram Stars\n\n"
        "Premium members receive additional signals.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# -------------------------
# Admin
# -------------------------

async def set_signal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n\n"
            "/setsignal 🟢 BUY BTC/USDT\n"
            "Entry: 120000\n"
            "SL: 118500\n"
            "TP: 123000"
        )

        return

    signal = " ".join(context.args)

    set_signal(signal)

    await update.message.reply_text(
        "✅ Signal updated successfully."
    )


# -------------------------
# Main
# -------------------------

def main():

    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN environment variable is missing."
        )

    setup_database()

    # Start Render web server
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("premium", premium)
    )

    application.add_handler(
        CommandHandler("setsignal", set_signal_command)
    )

    application.add_handler(
        CallbackQueryHandler(buttons)
    )

    application.add_handler(
        PreCheckoutQueryHandler(precheckout)
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )

    print("RobertFX AI Signals Bot is running...")

    application.run_polling()


if __name__ == "__main__":
    main()
