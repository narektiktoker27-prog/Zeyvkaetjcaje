import json
import logging
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    DocumentHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

import database as db
from config import BOT_TOKEN, OWNER_ID
from payment import parse_payload, send_number_invoice

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

PAGE_SIZE = 8
PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID


async def send_auto_backup(bot, reason: str) -> None:
    """Send the latest database backup to the owner after a data-changing action."""
    temp_path = None
    try:
        data = db.export_backup()
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", prefix="auto_backup_", delete=False
        ) as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path = f.name
        await bot.send_document(
            chat_id=OWNER_ID,
            document=temp_path,
            caption=f"🔐 Auto backup — {reason}\nՏվյալների վերջին տարբերակը պահպանված է Telegram-ում։",
        )
    except Exception:
        logger.exception("Automatic backup failed after: %s", reason)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def main_keyboard(admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📱 Գնել համար", callback_data="buy:0"),
            InlineKeyboardButton("📦 Իմ համարները", callback_data="my_numbers"),
        ],
        [
            InlineKeyboardButton("🧾 Իմ պատվերները", callback_data="my_orders"),
            InlineKeyboardButton("ℹ️ Օգնություն", callback_data="help"),
        ],
    ]
    if admin:
        rows.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Բոլոր համարները", callback_data="all_numbers:0"),
            InlineKeyboardButton("➕ Ավելացնել համար", callback_data="add_number"),
        ],
        [
            InlineKeyboardButton("🗑️ Հեռացնել համար", callback_data="remove_number:0"),
            InlineKeyboardButton("📊 Վիճակագրություն", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("💰 Վաճառված", callback_data="sold_numbers:0"),
            InlineKeyboardButton("⭐ Stars Statistics", callback_data="stars_stats"),
        ],
        [
            InlineKeyboardButton("📥 Backup", callback_data="backup"),
            InlineKeyboardButton("📤 Restore", callback_data="restore_help"),
        ],
        [InlineKeyboardButton("🏠 Գլխավոր", callback_data="home")],
    ])


def back_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Գլխավոր", callback_data="home")]
    ])


def back_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Admin Panel", callback_data="admin")]
    ])


def pagination_row(prefix: str, page: int, total: int) -> list[InlineKeyboardButton]:
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}:{page-1}"))
    if (page + 1) * PAGE_SIZE < total:
        buttons.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}:{page+1}"))
    return buttons


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.first_name)
    context.user_data.pop("action", None)
    context.user_data.pop("restore_data", None)

    text = (
        "🏠 <b>Համարների խանութ</b>\n\n"
        "Ընտրիր գործողությունը։"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(is_admin(user.id)),
    )


async def show_home(query) -> None:
    await query.edit_message_text(
        "🏠 <b>Համարների խանութ</b>\n\nԸնտրիր գործողությունը։",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(is_admin(query.from_user.id)),
    )


async def show_buy(query, page: int = 0) -> None:
    total = db.count_available_numbers()
    rows = db.get_available_numbers(PAGE_SIZE, page * PAGE_SIZE)

    if not rows:
        await query.edit_message_text(
            "📱 <b>Գնել համար</b>\n\n"
            "Այս պահին հասանելի համար չկա։",
            parse_mode=ParseMode.HTML,
            reply_markup=back_home_keyboard(),
        )
        return

    keyboard = []
    text_parts = ["📱 <b>Հասանելի համարներ</b>\n"]

    for row in rows:
        text_parts.append(
            f"📱 <code>{row['phone_number']}</code>\n"
            f"⭐ {row['price_stars']} Stars\n"
            f"🟢 Հասանելի\n"
        )
        keyboard.append([
            InlineKeyboardButton(
                f"⭐ Գնել {row['price_stars']} Stars",
                callback_data=f"buy_number:{row['id']}",
            )
        ])

    nav = pagination_row("buy", page, total)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🏠 Գլխավոր", callback_data="home")])

    await query.edit_message_text(
        "\n".join(text_parts),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_number_confirmation(query, number_id: int) -> None:
    row = db.get_number(number_id)
    if not row or row["status"] != "available":
        await query.answer("❌ Այս համարը արդեն վաճառված է կամ հասանելի չէ։", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"⭐ Վճարել {row['price_stars']} Stars-ով",
            callback_data=f"pay:{number_id}",
        )],
        [InlineKeyboardButton("⬅️ Հետ", callback_data="buy:0")],
    ])

    await query.edit_message_text(
        f"📱 <b>{row['phone_number']}</b>\n"
        f"⭐ Գին՝ <b>{row['price_stars']} Stars</b>\n"
        f"🟢 Հասանելի\n\n"
        "Սեղմիր վճարման կոճակը՝ Telegram Stars-ով վճարելու համար։",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def create_invoice(query, context: ContextTypes.DEFAULT_TYPE, number_id: int) -> None:
    row = db.get_number(number_id)
    if not row or row["status"] != "available":
        await query.answer("❌ Այս համարը այլևս հասանելի չէ։", show_alert=True)
        return

    user_id = query.from_user.id
    order_id = db.create_pending_order(user_id, number_id, int(row["price_stars"]))

    try:
        await send_number_invoice(
            context,
            query.message.chat_id,
            order_id,
            number_id,
            row["phone_number"],
            int(row["price_stars"]),
        )
        await query.answer("Invoice-ը ուղարկվեց։")
    except Exception:
        db.mark_order_cancelled(order_id)
        logger.exception("Could not create invoice for order %s", order_id)
        await query.answer("❌ Չհաջողվեց ստեղծել վճարումը։", show_alert=True)


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.pre_checkout_query
    parsed = parse_payload(q.invoice_payload)

    if not parsed:
        await q.answer(ok=False, error_message="Invalid payment payload.")
        return

    order_id, number_id = parsed
    order = db.get_order(order_id)

    if not order:
        await q.answer(ok=False, error_message="Order not found.")
        return

    if order["user_id"] != q.from_user.id or order["number_id"] != number_id:
        await q.answer(ok=False, error_message="This invoice does not belong to you.")
        return

    if order["status"] != "pending":
        await q.answer(ok=False, error_message="This order is no longer active.")
        return

    if order["number_status"] != "available":
        await q.answer(ok=False, error_message="This number is no longer available.")
        return

    if q.currency != "XTR" or q.total_amount != order["amount_stars"]:
        await q.answer(ok=False, error_message="Payment amount mismatch.")
        return

    await q.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment = update.message.successful_payment
    parsed = parse_payload(payment.invoice_payload)

    if not parsed:
        logger.error("Received successful payment with invalid payload.")
        await update.message.reply_text(
            "❌ Վճարումը ստացվել է, բայց պատվերի տվյալները սխալ են։ "
            "Խնդրում ենք կապվել ադմինի հետ։"
        )
        return

    order_id, number_id = parsed
    user_id = update.effective_user.id
    charge_id = payment.telegram_payment_charge_id

    # First check that Telegram sent a Stars payment and the expected amount.
    if payment.currency != "XTR":
        logger.error("Unexpected payment currency for order %s: %s", order_id, payment.currency)
        return

    order = db.get_order(order_id)
    if not order:
        logger.error("Payment received for missing order %s", order_id)
        return

    if payment.total_amount != order["amount_stars"]:
        logger.error("Payment amount mismatch for order %s", order_id)
        return

    ok, reason = db.finalize_successful_payment(
        order_id=order_id,
        user_id=user_id,
        number_id=number_id,
        amount_stars=payment.total_amount,
        telegram_payment_id=charge_id,
    )

    if ok:
        await update.message.reply_text(
            "✅ <b>Վճարումը հաստատվեց։</b>\n\n"
            f"📱 Ձեր համար՝ <code>{order['phone_number']}</code>\n"
            f"⭐ Վճարված՝ {payment.total_amount} Stars\n"
            f"🧾 Order ID՝ <code>{order_id}</code>\n\n"
            "Համարը կարող եք տեսնել «📦 Իմ համարները» բաժնում։",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(is_admin(user_id)),
        )
        try:
            await context.bot.send_message(
                OWNER_ID,
                "💰 <b>Նոր վաճառք</b>\n\n"
                f"🧾 Order ID՝ <code>{order_id}</code>\n"
                f"👤 User ID՝ <code>{user_id}</code>\n"
                f"📱 Number՝ <code>{order['phone_number']}</code>\n"
                f"⭐ Stars՝ {payment.total_amount}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.exception("Could not notify owner about order %s", order_id)
        await send_auto_backup(context.bot, f"վաճառք / order {order_id}")
        return

    if reason == "duplicate":
        # Telegram may retry the same update. Do not sell or create anything again.
        await update.message.reply_text("✅ Այս վճարումը արդեն մշակվել է։")
        return

    if reason == "unavailable":
        # Payment succeeded but another transaction won the race.
        # Refund the successful Stars payment because the number cannot be delivered.
        try:
            await context.bot.refund_star_payment(
                user_id=user_id,
                telegram_payment_charge_id=charge_id,
            )
            db.mark_order_refunded(order_id, charge_id)
            await update.message.reply_text(
                "⚠️ Այս համարը վճարման պահին այլևս հասանելի չէր։ "
                "Վճարումը վերադարձվեց Telegram Stars-ով։"
            )
        except Exception:
            logger.exception("Refund failed for order %s", order_id)
            await update.message.reply_text(
                "⚠️ Այս համարը այլևս հասանելի չէ։ "
                "Վերադարձի գործողությունը չհաջողվեց ավտոմատ ավարտել։ "
                "Խնդրում ենք կապվել ադմինի հետ։"
            )
        return

    logger.error("Payment processing failed for order %s: %s", order_id, reason)
    await update.message.reply_text(
        "❌ Չհաջողվեց ավարտել պատվերը։ Խնդրում ենք կապվել ադմինի հետ։"
    )


async def show_my_numbers(query) -> None:
    rows = db.get_user_numbers(query.from_user.id)
    if not rows:
        text = "📦 <b>Իմ համարները</b>\n\nԴուք դեռ գնված համար չունեք։"
    else:
        parts = ["📦 <b>Իմ համարները</b>\n"]
        for row in rows:
            parts.append(
                f"📱 <code>{row['phone_number']}</code>\n"
                f"⭐ {row['price_stars']} Stars\n"
                f"📅 {row['purchased_at']}\n"
            )
        text = "\n".join(parts)

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_keyboard(),
    )


async def show_my_orders(query) -> None:
    rows = db.get_user_orders(query.from_user.id)
    if not rows:
        text = "🧾 <b>Իմ պատվերները</b>\n\nՊատվերներ չկան։"
    else:
        parts = ["🧾 <b>Իմ պատվերները</b>\n"]
        for row in rows:
            status = {
                "paid": "🟢 Վճարված",
                "pending": "🟡 Սպասում է",
                "refunded": "🔄 Վերադարձված",
                "cancelled": "⚪ Չեղարկված",
            }.get(row["status"], row["status"])
            date = row["paid_at"] or row["created_at"]
            parts.append(
                f"🧾 Order ID՝ <code>{row['id']}</code>\n"
                f"📱 {row['phone_number']}\n"
                f"⭐ {row['amount_stars']} Stars\n"
                f"📅 {date}\n"
                f"{status}\n"
            )
        text = "\n".join(parts)

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_keyboard(),
    )


async def show_help(query) -> None:
    text = (
        "ℹ️ <b>Օգնություն</b>\n\n"
        "1. Բացեք «📱 Գնել համար»։\n"
        "2. Ընտրեք հասանելի համարը։\n"
        "3. Սեղմեք «⭐ Վճարել ... Stars-ով»։\n"
        "4. Telegram-ի պաշտոնական վճարման պատուհանում հաստատեք վճարումը։\n"
        "5. Հաջող վճարումից հետո համարը կավելացվի «📦 Իմ համարները» բաժնում։\n\n"
        "Եթե payment error առաջանա, կրկին փորձեք։ Եթե խնդիրը շարունակվի, կապվեք ադմինի հետ։"
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_keyboard(),
    )


async def show_admin(query) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return
    await query.edit_message_text(
        "👑 <b>Admin Panel</b>\n\nԸնտրեք գործողությունը։",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def show_all_numbers(query, page: int = 0) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    total = db.count_numbers()
    rows = db.get_all_numbers(PAGE_SIZE, page * PAGE_SIZE)
    parts = ["📦 <b>Բոլոր համարները</b>\n"]

    for row in rows:
        state = "🟢 Available" if row["status"] == "available" else "🔴 Sold"
        owner = f"<code>{row['owner_id']}</code>" if row["owner_id"] else "—"
        purchased = row["purchased_at"] or "—"
        parts.append(
            f"#{row['id']} 📱 <code>{row['phone_number']}</code>\n"
            f"⭐ {row['price_stars']} | {state}\n"
            f"👤 Owner ID՝ {owner}\n"
            f"📅 {purchased}\n"
        )

    keyboard = []
    nav = pagination_row("all_numbers", page, total)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin")])

    await query.edit_message_text(
        "\n".join(parts) if rows else "📦 Համարներ չկան։",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def start_add_number(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return
    context.user_data["action"] = "add_phone"
    await query.edit_message_text(
        "➕ <b>Ավելացնել համար</b>\n\n"
        "Գրեք միջազգային ձևաչափով համարը, օրինակ՝\n"
        "<code>+374XXXXXXXX</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_admin_keyboard(),
    )


async def show_remove_numbers(query, page: int = 0) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    total = db.count_available_numbers()
    rows = db.get_available_numbers(PAGE_SIZE, page * PAGE_SIZE)
    keyboard = []

    for row in rows:
        keyboard.append([
            InlineKeyboardButton(
                f"🗑️ {row['phone_number']}",
                callback_data=f"remove_confirm:{row['id']}",
            )
        ])

    nav = pagination_row("remove_number", page, total)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin")])

    await query.edit_message_text(
        "🗑️ <b>Հեռացնել համար</b>\n\nԸնտրեք միայն հասանելի համարը։",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def remove_confirm(query, number_id: int) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    row = db.get_number(number_id)
    if not row or row["status"] != "available":
        await query.answer("❌ Համարը հասանելի չէ։", show_alert=True)
        return

    await query.edit_message_text(
        f"⚠️ Համոզվա՞ծ եք, որ ցանկանում եք հեռացնել\n"
        f"<code>{row['phone_number']}</code>։",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Այո", callback_data=f"remove_yes:{number_id}"),
                InlineKeyboardButton("❌ Չեղարկել", callback_data="remove_number:0"),
            ]
        ]),
    )


async def remove_yes(query, number_id: int) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    if db.delete_number(number_id):
        await query.answer("✅ Հեռացված է։")
        await send_auto_backup(query.get_bot(), f"համարի հեռացում / ID {number_id}")
        await show_remove_numbers(query, 0)
    else:
        await query.answer("❌ Չհաջողվեց հեռացնել։", show_alert=True)


async def show_stats(query) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    s = db.get_stats()
    text = (
        "📊 <b>Statistics</b>\n\n"
        f"📱 Ընդհանուր համարներ՝ <b>{s['total_numbers']}</b>\n"
        f"🟢 Ազատ համարներ՝ <b>{s['available']}</b>\n"
        f"🔴 Վաճառված համարներ՝ <b>{s['sold']}</b>\n"
        f"🧾 Ընդհանուր պատվերներ՝ <b>{s['orders']}</b>\n"
        f"⭐ Ընդհանուր հաստատված Stars՝ <b>{s['stars']}</b>\n"
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_admin_keyboard(),
    )


async def show_stars_stats(query) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    s = db.get_stats()
    rows = db.get_recent_paid_orders(15)
    parts = [
        "⭐ <b>Stars Statistics</b>\n",
        f"⭐ Ընդհանուր հաստատված Stars՝ <b>{s['stars']}</b>",
        f"🧾 Հաստատված պատվերներ՝ <b>{s['paid_orders']}</b>",
        f"📱 Վաճառված համարներ՝ <b>{s['sold']}</b>\n",
        "<b>Վերջին վճարումները</b>",
    ]

    if not rows:
        parts.append("Դեռ վճարումներ չկան։")
    else:
        for row in rows:
            parts.append(
                f"\n🧾 #{row['id']} | 👤 <code>{row['user_id']}</code>\n"
                f"📱 #{row['number_id']} {row['phone_number']}\n"
                f"⭐ {row['amount_stars']} | 🟢 {row['status']}\n"
                f"📅 {row['paid_at']}"
            )

    await query.edit_message_text(
        "\n".join(parts),
        parse_mode=ParseMode.HTML,
        reply_markup=back_admin_keyboard(),
    )


async def show_sold_numbers(query, page: int = 0) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    total = db.count_sold_numbers()
    rows = db.get_sold_numbers(PAGE_SIZE, page * PAGE_SIZE)
    parts = ["💰 <b>Վաճառված համարներ</b>\n"]

    for row in rows:
        parts.append(
            f"#{row['id']} 📱 <code>{row['phone_number']}</code>\n"
            f"👤 Owner Telegram ID՝ <code>{row['owner_id']}</code>\n"
            f"⭐ Price՝ {row['price_stars']}\n"
            f"📅 Purchase՝ {row['purchased_at']}\n"
            f"🔴 Sold\n"
        )

    keyboard = []
    nav = pagination_row("sold_numbers", page, total)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin")])

    await query.edit_message_text(
        "\n".join(parts) if rows else "💰 Վաճառված համարներ չկան։",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def create_backup(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    data = db.export_backup()
    temp_path = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="backup_",
            delete=False,
        ) as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path = f.name

        await context.bot.send_document(
            chat_id=OWNER_ID,
            document=temp_path,
            caption="📥 Database backup",
        )
        await query.answer("✅ Backup-ը ուղարկվեց։")
    except Exception:
        logger.exception("Backup creation/sending failed")
        await query.answer("❌ Backup-ը չհաջողվեց ստեղծել։", show_alert=True)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


async def restore_help(query) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return
    context = query._bot if False else None  # no-op; keeps handler simple
    await query.edit_message_text(
        "📤 <b>Restore</b>\n\n"
        "Ուղարկեք <code>backup.json</code> ֆայլը այս չատում։\n"
        "Բոտը կստուգի կառուցվածքը և նախքան restore-ը կպահանջի հաստատում։",
        parse_mode=ParseMode.HTML,
        reply_markup=back_admin_keyboard(),
    )


async def handle_restore_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return

    document = update.message.document
    if not document.file_name.lower().endswith(".json"):
        await update.message.reply_text("❌ Ուղարկեք միայն JSON backup ֆայլ։")
        return

    if document.file_size and document.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("❌ Backup ֆայլը չափազանց մեծ է (առավելագույնը 5 MB)։")
        return

    temp_path = None
    try:
        tg_file = await document.get_file()
        with NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = f.name
        await tg_file.download_to_drive(temp_path)

        raw = Path(temp_path).read_text(encoding="utf-8")
        data = json.loads(raw)
        ok, reason = db.validate_backup(data)
        if not ok:
            await update.message.reply_text(f"❌ Backup-ը անվավեր է.\n{reason}")
            return

        context.user_data["restore_data"] = data

        await update.message.reply_text(
            "⚠️ <b>Restore-ը կփոխի ընթացիկ տվյալների բազան։</b>\n\n"
            f"Users՝ {len(data['users'])}\n"
            f"Numbers՝ {len(data['numbers'])}\n"
            f"Orders՝ {len(data['orders'])}\n\n"
            "Հաստատե՞լ restore-ը։",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Հաստատել Restore", callback_data="restore_yes"),
                    InlineKeyboardButton("❌ Չեղարկել", callback_data="restore_no"),
                ]
            ]),
        )
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Ֆայլը ճիշտ JSON չէ։")
    except Exception:
        logger.exception("Restore file handling failed")
        await update.message.reply_text("❌ Չհաջողվեց կարդալ backup-ը։")
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


async def restore_yes(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return

    data = context.user_data.get("restore_data")
    if not data:
        await query.answer("❌ Restore տվյալները այլևս հասանելի չեն։", show_alert=True)
        return

    try:
        db.restore_backup(data)
        context.user_data.pop("restore_data", None)
        await query.edit_message_text(
            "✅ <b>Restore-ը հաջողությամբ ավարտվեց։</b>\n\n"
            "Հին users/numbers/orders տվյալները վերականգնված են։",
            parse_mode=ParseMode.HTML,
            reply_markup=back_admin_keyboard(),
        )
        await send_auto_backup(context.bot, "restore-ից հետո նոր backup")
    except Exception:
        logger.exception("Database restore failed")
        await query.edit_message_text(
            "❌ Restore-ը չհաջողվեց։ Տվյալների բազան չի փոխվել, եթե սխալը տեղի է ունեցել restore-ի validation փուլից հետո։",
            reply_markup=back_admin_keyboard(),
        )


async def restore_no(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌ Մուտքը թույլատրված չէ։", show_alert=True)
        return
    context.user_data.pop("restore_data", None)
    await query.edit_message_text(
        "❌ Restore-ը չեղարկվեց։",
        reply_markup=back_admin_keyboard(),
    )


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return

    action = context.user_data.get("action")
    if not action:
        return

    if not is_admin(update.effective_user.id):
        context.user_data.pop("action", None)
        return

    text = (update.message.text or "").strip()

    if action == "add_phone":
        if not PHONE_RE.fullmatch(text):
            await update.message.reply_text(
                "❌ Սխալ ձևաչափ։ Օգտագործեք միջազգային ձևաչափ, օրինակ՝ +374XXXXXXXX։"
            )
            return

        # Duplicate check.
        with db.get_db() as conn:
            exists = conn.execute(
                "SELECT id FROM numbers WHERE phone_number=?", (text,)
            ).fetchone()

        if exists:
            await update.message.reply_text("❌ Այս համարը արդեն գոյություն ունի։")
            return

        context.user_data["new_phone"] = text
        context.user_data["action"] = "add_price"
        await update.message.reply_text("⭐ Գրեք գինը Stars-ով, օրինակ՝ 100։")
        return

    if action == "add_price":
        try:
            price = int(text)
        except ValueError:
            await update.message.reply_text("❌ Գինը պետք է լինի ամբողջ թիվ։")
            return

        if price <= 0 or price > 100000:
            await update.message.reply_text("❌ Գինը պետք է լինի 1-ից 100000 Stars։")
            return

        phone = context.user_data.get("new_phone")
        if not phone:
            context.user_data.pop("action", None)
            await update.message.reply_text("❌ Ավելացման գործընթացը կորել է։ Կրկին սկսեք։")
            return

        try:
            number_id = db.add_number(phone, price)
        except Exception:
            logger.exception("Could not add number")
            await update.message.reply_text("❌ Չհաջողվեց ավելացնել համարը։")
            return

        context.user_data.pop("action", None)
        context.user_data.pop("new_phone", None)

        await update.message.reply_text(
            f"✅ Ավելացված է։\n\n"
            f"📱 <code>{phone}</code>\n"
            f"⭐ {price} Stars\n"
            f"🟢 Available\n"
            f"ID՝ <code>{number_id}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )
        await send_auto_backup(context.bot, f"նոր համար / ID {number_id}")


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    try:
        if data == "home":
            context.user_data.pop("action", None)
            await show_home(query)

        elif data.startswith("buy:"):
            page = int(data.split(":")[1])
            await show_buy(query, page)

        elif data.startswith("buy_number:"):
            await show_number_confirmation(query, int(data.split(":")[1]))

        elif data.startswith("pay:"):
            await create_invoice(query, context, int(data.split(":")[1]))

        elif data == "my_numbers":
            await show_my_numbers(query)

        elif data == "my_orders":
            await show_my_orders(query)

        elif data == "help":
            await show_help(query)

        elif data == "admin":
            await show_admin(query)

        elif data.startswith("all_numbers:"):
            await show_all_numbers(query, int(data.split(":")[1]))

        elif data == "add_number":
            await start_add_number(query, context)

        elif data.startswith("remove_number:"):
            await show_remove_numbers(query, int(data.split(":")[1]))

        elif data.startswith("remove_confirm:"):
            await remove_confirm(query, int(data.split(":")[1]))

        elif data.startswith("remove_yes:"):
            await remove_yes(query, int(data.split(":")[1]))

        elif data == "stats":
            await show_stats(query)

        elif data.startswith("sold_numbers:"):
            await show_sold_numbers(query, int(data.split(":")[1]))

        elif data == "stars_stats":
            await show_stars_stats(query)

        elif data == "backup":
            await create_backup(query, context)

        elif data == "restore_help":
            await restore_help(query)

        elif data == "restore_yes":
            await restore_yes(query, context)

        elif data == "restore_no":
            await restore_no(query, context)

    except Exception:
        logger.exception("Callback handler failed for %s", data)
        try:
            await query.answer("❌ Տեղի ունեցավ սխալ։", show_alert=True)
        except Exception:
            pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)


def build_application() -> Application:
    db.init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_restore_document)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_input)
    )
    application.add_handler(
        PreCheckoutQueryHandler(pre_checkout)
    )
    application.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment)
    )
    application.add_handler(
        CallbackQueryHandler(callback_router)
    )
    application.add_error_handler(error_handler)

    return application


def main() -> None:
    app = build_application()
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
