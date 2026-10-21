from decimal import Decimal, ROUND_HALF_UP


def dollars_to_cents(value: str | Decimal) -> int:
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def format_cents(cents: int, currency: str = "USD") -> str:
    return f"{cents / 100:,.2f} {currency}"
