"""HTTP endpoints for the billing app, all under ``/api/billing/``:

* ``wallets/``                    -- every wallet's current balance.
* ``zones/<id>/wallet/``          -- one zone's wallet (404 if it has never been billed).
* ``zones/<id>/history/``         -- a zone's billing charges, newest first.
* ``zones/<id>/transactions/``    -- a zone's wallet ledger, newest first.
* ``plants/purchase/``            -- buy a new plant against the shared Grid wallet.
* ``plants/upgrade/``             -- grow an existing plant, charged the price delta.
* ``plants/decommission/``        -- retire a plant for a partial refund.
* ``storage/purchase/``           -- buy a new storage unit against the Grid wallet.
* ``unlocks/``                    -- which plant types are currently purchasable.
* ``summary/``                    -- grid-wide revenue vs. spend, all time.

None of this touches the billing cycle itself: ``BillingCycleService`` keeps billing
every zone off its own demand readings regardless of what happens here.
"""
import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .. import models as orm
from .. import wiring
from ..billing import PlantPricing, PlantTypeLockedException, StoragePricing, UnlockThresholds
from ..domain import GRID_WALLET_ID, GRID_WALLET_NAME, PlantType, TransactionType
from . import dto
from .errors import handle_api_errors
from .exceptions import RequestValidationError, UnsupportedMediaTypeError, ZoneNotBilledException

DEFAULT_LIMIT = 50
# A zone's full billing/ledger history in one response is never a legitimate ask.
MAX_LIMIT = 1000


def api_view(*methods):
    """Method filter + uniform error mapping for a JSON API view.

    CSRF is exempt because this is a token-less machine API, not a browser form; the
    cross-site-POST hole that leaves is closed by ``_read_json_body`` insisting on a
    JSON content type.
    """

    def decorator(view):
        return csrf_exempt(require_http_methods(methods)(handle_api_errors(view)))

    return decorator


def _read_json_body(request) -> dict:
    if request.content_type != 'application/json':
        raise UnsupportedMediaTypeError(
            f"Content-Type must be application/json, got {request.content_type or 'none'!r}")
    body = json.loads(request.body)
    if not isinstance(body, dict):
        raise RequestValidationError(['body: must be a JSON object'])
    return body


def _int_param(request, name: str, default: int) -> int:
    value = request.GET.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f'{name} must be an integer, got {value!r}')


def _grid_balance() -> float:
    """The Grid wallet's current balance, read plainly (no row lock): every mutating
    endpoint below takes its own lock via ``WalletSpendingService``, so this is only
    ever used where no write is about to follow, the same read distributor's views
    take of ``ZoneCapacity.updated_at`` alongside its own ports."""
    balance = orm.Wallet.objects.filter(pk=GRID_WALLET_ID).values_list('balance_rupees', flat=True).first()
    return balance if balance is not None else wiring.STARTING_BALANCE


@api_view('GET')
def wallets(request):
    return JsonResponse([dto.wallet_response(w) for w in orm.Wallet.objects.order_by('zone_id')], safe=False)


@api_view('GET')
def zone_wallet(request, zone_id):
    wallet = orm.Wallet.objects.filter(pk=zone_id).first()
    if wallet is None:
        raise ZoneNotBilledException(zone_id)
    return JsonResponse(dto.wallet_response(wallet))


@api_view('GET')
def zone_history(request, zone_id):
    limit = _int_param(request, 'limit', DEFAULT_LIMIT)
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f'limit must be between 1 and {MAX_LIMIT}, got {limit}')
    records = orm.BillingRecord.objects.filter(zone_id=zone_id)[:limit]
    return JsonResponse([dto.billing_record_response(r) for r in records], safe=False)


@api_view('GET')
def zone_transactions(request, zone_id):
    limit = _int_param(request, 'limit', DEFAULT_LIMIT)
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f'limit must be between 1 and {MAX_LIMIT}, got {limit}')
    txns = orm.WalletTransaction.objects.filter(zone_id=zone_id)[:limit]
    return JsonResponse([dto.transaction_response(t) for t in txns], safe=False)


@api_view('POST')
def purchase_plant(request):
    """Buys a new plant against the shared Grid wallet. The price is never taken from
    the request -- it is computed here from ``PlantPricing``, keyed on the same type
    and capacity Producer will build, so the frontend's own estimate can never under-
    or over-charge it. Unlike a billing charge, this is refused (402) rather than
    applied when the wallet can't cover it.
    """
    plant_type, capacity_mw = dto.parse_plant_purchase_request(_read_json_body(request))

    sold = wiring.unlock_service().cumulative_kwh_sold()
    if not UnlockThresholds.is_unlocked(plant_type, sold):
        raise PlantTypeLockedException(plant_type, UnlockThresholds.threshold_for(plant_type), sold)

    cost = PlantPricing.cost(plant_type, capacity_mw)
    with transaction.atomic():
        balance = wiring.wallet_spending_service().spend(
            GRID_WALLET_ID, GRID_WALLET_NAME, cost, TransactionType.PLANT_PURCHASE)
    return JsonResponse(dto.plant_spend_response(GRID_WALLET_ID, GRID_WALLET_NAME, cost, balance))


@api_view('POST')
def upgrade_plant(request):
    """Grows an existing plant's capacity, charged only the difference between its
    old and new price. A change that doesn't raise the price (a downgrade, or no
    capacity change) costs nothing and is never sent to spend, so it can't be refused
    for insufficient funds.
    """
    plant_type, old_capacity_mw, new_capacity_mw = dto.parse_plant_upgrade_request(_read_json_body(request))

    old_cost = PlantPricing.cost(plant_type, old_capacity_mw)
    new_cost = PlantPricing.cost(plant_type, new_capacity_mw)
    extra_cost = max(0.0, new_cost - old_cost)

    if extra_cost > 0:
        with transaction.atomic():
            balance = wiring.wallet_spending_service().spend(
                GRID_WALLET_ID, GRID_WALLET_NAME, extra_cost, TransactionType.PLANT_UPGRADE)
    else:
        balance = _grid_balance()

    return JsonResponse(dto.plant_spend_response(GRID_WALLET_ID, GRID_WALLET_NAME, extra_cost, balance))


@api_view('POST')
def decommission_plant(request):
    """Decommissions a plant, crediting the shared Grid wallet a fraction of what it
    would cost to buy that plant fresh today. A credit can never be refused, so
    unlike a purchase there is no 402 path here.
    """
    plant_type, capacity_mw = dto.parse_plant_decommission_request(_read_json_body(request))
    refund = wiring.DECOMMISSION_REFUND_RATIO * PlantPricing.cost(plant_type, capacity_mw)
    with transaction.atomic():
        balance = wiring.wallet_spending_service().credit(
            GRID_WALLET_ID, GRID_WALLET_NAME, refund, TransactionType.PLANT_DECOMMISSION)
    return JsonResponse(dto.plant_spend_response(GRID_WALLET_ID, GRID_WALLET_NAME, refund, balance))


@api_view('POST')
def purchase_storage(request):
    """Buys a new storage unit against the shared Grid wallet -- same shape as
    ``purchase_plant``, no unlock gate (storage isn't tech-tree gated)."""
    kind, capacity_kwh = dto.parse_storage_purchase_request(_read_json_body(request))
    cost = StoragePricing.cost(kind, capacity_kwh)
    with transaction.atomic():
        balance = wiring.wallet_spending_service().spend(
            GRID_WALLET_ID, GRID_WALLET_NAME, cost, TransactionType.STORAGE_PURCHASE)
    return JsonResponse(dto.plant_spend_response(GRID_WALLET_ID, GRID_WALLET_NAME, cost, balance))


@api_view('GET')
def unlocks(request):
    """Which plant types are currently purchasable, and how far off the next one is.
    The frontend can use this to grey out a locked type, but ``purchase_plant``
    enforces the same rule server-side regardless."""
    sold = wiring.unlock_service().cumulative_kwh_sold()
    unlocked_types = [t for t in PlantType if UnlockThresholds.is_unlocked(t, sold)]
    next_locked = wiring.unlock_service().next_locked()
    next_unlock = (next_locked, UnlockThresholds.threshold_for(next_locked) - sold) if next_locked else None
    return JsonResponse(dto.unlocks_response(unlocked_types, sold, next_unlock))


@api_view('GET')
def summary(request):
    """Revenue vs. spend, all time. No new persistence: both sides are summed fresh
    from wallet transactions on every request."""
    revenue = orm.WalletTransaction.objects.sum_by_types([TransactionType.BILL_DEBIT])
    spend = orm.WalletTransaction.objects.sum_by_types([
        TransactionType.PLANT_PURCHASE, TransactionType.PLANT_UPGRADE,
        TransactionType.PLANT_MAINTENANCE, TransactionType.STORAGE_PURCHASE,
    ])
    return JsonResponse(dto.summary_response(revenue, spend))
