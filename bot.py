import os
import sqlite3
from datetime import datetime, timedelta, timezone

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

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PREMIUM_PRICE = int(os.getenv("PREMIUM_PRICE", "100"))
PREMIUM_DAYS = int(os.getenv("PREMIUM_DAYS", "30"))

DB_FILE = "signals.db"


# =========================
# DATABASE
# =========================

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

    cur.execute("""
        UPDATE users SET username = ? WHERE user_id = ?
    """, (username, user_id))

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
    """, (datetime.now(timezone.utc).isoformat(), user_id))

    conn.commit()
    conn.close()


def set_premium(user_id):
    conn = db()
    cur = conn.cursor()

    current = cur.execute("""
        SELECT premium_until FROM users WHERE user_id = ?
    """, (user_id,)).fetchone()

    now = datetime.now(timezone.utc)

    if current and current[0]:
        try:
            old_date = datetime.fromisoformat(current[0])

            if old_date > now:
                start = old_date
            else:
                start = now
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


def is_premium(user_id):
    user = get_user(user_id)

    if not user or not user[0]:
        return False

    try:
        expiry = datetime.fromisoformat(user[0])
        return expiry > datetime.now(timezone.utc)
    except Exception:
        return False


def get_signal():
    conn = db()
    cur = conn.cursor()

    result = cur.execute("""
        SELECT value FROM settings
        WHERE name = 'latest_signal'
    """).fetchone()

    conn.close()

    if result:
        return result[0]

    return (
        "📊 <b>Today's Signal</b>\n\n"
        "⚠️ No signal has been published yet.\n\n"
        "The admin can publish a signal with:\n"
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


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    register_user(
        user.id,
        user.username or user.first_name
    )

    keyboard = [
        [InlineKeyboardButton("🆓 Get Free Signal", callback_data="free_signal")],
        [InlineKeyboardButton("💎 Premium Signals", callback_data="premium")],
        [InlineKeyboardButton("📊 Latest Signal", callback_data="latest")],
    ]

    await update.message.reply_text(
        f"👋 <b>Welcome to RobertFX AI Signals</b>\n\n"
        f"Forex & BTC market signals delivered directly to Telegram.\n\n"
        f"🆓 Free users receive 1 signal per day.\n"
        f"💎 Premium members receive additional signals.\n\n"
        f"⚠️ Trading involves risk. Signals are not guaranteed profits.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# BUTTONS
# =========================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "free_signal":

        user = get_user(user_id)

        if is_premium(user_id):
            await query.message.reply_text(
                "💎 You are already a Premium member.\n\n"
                "You have access to Premium signals."
            )
            return

        last_signal = user[1] if user else None

        if last_signal:

            try:
                last_time = datetime.fromisoformat(last_signal)
                difference = datetime.now(timezone.utc) - last_time

                if difference < timedelta(hours=24):
                    remaining = timedelta(hours=24) - difference

                    hours = int(remaining.total_seconds() // 3600)
                    minutes = int(
                        (remaining.total_seconds() % 3600) // 60
                    )

                    await query.message.reply_text(
                        f"⏳ You've already received today's free signal.\n\n"
                        f"Next free signal in approximately "
                        f"{hours}h {minutes}m.\n\n"
                        f"💎 Want more signals?\n"
                        f"Use /premium"
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
                f"💎 <b>Premium Active</b>\n\n"
                f"Your Premium access expires:\n"
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
                f"💎 <b>Premium Signals</b>\n\n"
                f"Get access to additional Forex & BTC signals.\n\n"
                f"📅 Duration: {PREMIUM_DAYS} days\n"
                f"💰 Price: {PREMIUM_PRICE} Telegram Stars\n\n"
                f"Tap below to subscribe.",
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


# =========================
# PAYMENT
# =========================

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.pre_checkout_query

    await query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):

    payment = update.message.successful_payment
    user_id = update.effective_user.id

    expiry = set_premium(user_id)

    await update.message.reply_text(
        f"✅ <b>Payment successful!</b>\n\n"
        f"💎 Premium activated.\n\n"
        f"Your Premium access expires:\n"
        f"{expiry.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"🚀 You now have access to Premium signals.",
        parse_mode="HTML"
    )


# =========================
# PREMIUM COMMAND
# =========================

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if is_premium(user_id):

        user = get_user(user_id)
        expiry = datetime.fromisoformat(user[0])

        await update.message.reply_text(
            f"💎 Premium is active.\n\n"
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
        f"💎 <b>RobertFX Premium</b>\n\n"
        f"📅 {PREMIUM_DAYS} days\n"
        f"💰 {PREMIUM_PRICE} Telegram Stars\n\n"
        f"Premium members receive additional signals.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# ADMIN COMMAND
# =========================

async def set_signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

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


# =========================
# ADMIN BROADCAST
# =========================

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/broadcast Your message"
        )
        return

    message = " ".join(context.args)

    conn = db()
    cur = conn.cursor()

    users = cur.execute(
        "SELECT user_id FROM users"
    ).fetchall()

    conn.close()

    sent = 0

    for user in users:

        try:

            await context.bot.send_message(
                chat_id=user[0],
                text=message,
                parse_mode="HTML"
            )

            sent += 1

        except Exception:
            pass

    await update.message.reply_text(
        f"✅ Broadcast sent to {sent} users."
    )


# =========================
# MAIN
# =========================

def main():

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is missing.")

    setup_database()

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
        CommandHandler("broadcast", broadcast)
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
