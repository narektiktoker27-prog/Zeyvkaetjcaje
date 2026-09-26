from telegram import LabeledPrice
from telegram.ext import ContextTypes

import database as db


def build_payload(order_id: int, number_id: int) -> str:
    return f"number:{order_id}:{number_id}"


def parse_payload(payload: str) -> tuple[int, int] | None:
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "number":
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


async def send_number_invoice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    order_id: int,
    number_id: int,
    phone_number: str,
    amount_stars: int,
) -> None:
    payload = build_payload(order_id, number_id)

    await context.bot.send_invoice(
        chat_id=chat_id,
        title="Telegram number",
        description=f"Purchase {phone_number}",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=f"{phone_number}", amount=amount_stars)],
        provider_token="",
    )
