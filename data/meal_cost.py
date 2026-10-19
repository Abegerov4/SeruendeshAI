"""Complete payable cost of one source-confirmed dine-in offering."""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math


def valid_cost_terms(cost, *, require_complete: bool = True) -> bool:
    if (not isinstance(cost, dict) or type(cost.get("complete")) is not bool
            or require_complete and cost["complete"] is not True or cost.get("scope") != "one_offering"):
        return False
    known = 0
    for key in ("service_percent", "mandatory_fixed_amount", "minimum_payable_amount"):
        value = cost.get(key)
        if value is None and cost["complete"] is False:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            return False
        known += 1
    return known > 0 and (cost.get("service_percent") is None or cost["service_percent"] <= 100)


def cost_evidence_current(menu: dict, today: date) -> bool:
    from data.place_details import _evidence_valid
    from urllib.parse import urlsplit

    cost, branch = menu.get("cost"), menu.get("branch_confirmation")
    if not valid_cost_terms(cost, require_complete=False) or not isinstance(branch, dict):
        return False
    if not all(isinstance(branch.get(k), str) and branch[k].strip() for k in ("source_name", "source_address")):
        return False
    if not _evidence_valid(cost, branch, today, 30):
        return False
    if (menu.get("price") or {}).get("channel") == "dine_in":
        source = cost["source"]
        host = urlsplit(source["url"]).hostname or ""
        if source.get("channel") in {"delivery", "takeaway"} or host == "wolt.com" or host.endswith(".wolt.com"):
            return False
    return True


def complete_meal_price(menu: dict, today: date) -> dict | None:
    """Unknown charges stay unknown; a menu base price is never its own proof."""
    from data.place_details import _price_valid

    price, cost = menu.get("price"), menu.get("cost")
    branch = menu.get("branch_confirmation")
    if (not _price_valid(price, menu=True) or price["channel"] != "dine_in"
            or price["unit"] not in {"item", "portion", "dish", "meal", "порция", "блюдо", "позиция"}
            or not valid_cost_terms(cost) or not isinstance(branch, dict)
            or not all(isinstance(branch.get(k), str) and branch[k].strip() for k in ("source_name", "source_address"))
            or not cost_evidence_current(menu, today)):
        return None
    try:
        base = Decimal(str(price["amount"]))
        total = max(base * (1 + Decimal(str(cost["service_percent"])) / 100)
                    + Decimal(str(cost["mandatory_fixed_amount"])), Decimal(str(cost["minimum_payable_amount"])))
        amount = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, OverflowError, ValueError):
        return None
    if not math.isfinite(amount):
        return None
    return {**price, "amount": amount}
