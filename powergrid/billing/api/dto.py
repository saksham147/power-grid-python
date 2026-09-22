"""Request and response bodies for the billing HTTP API.

Plain functions rather than a serializer framework: there is no DRF here and each
shape is a handful of fields.
"""
import math
from http import HTTPStatus

from django.utils import timezone

from .. import models as orm
from ..domain import PlantType, StorageKind
from .exceptions import RequestValidationError


def _number(body: dict, key: str, errors: list[str], *, positive: bool):
    """The value as a float, or None after recording why it is not acceptable.

    Booleans are rejected (``True`` is an ``int`` in Python) and so are NaN and
    Infinity, which Python's JSON parser accepts but which would slip past every
    ``> 0`` / ``>= 0`` comparison downstream.
    """
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append(f'{key}: must be a number')
    elif positive and value <= 0:
        errors.append(f'{key}: must be positive')
    elif not positive and value < 0:
        errors.append(f'{key}: must be positive or zero')
    else:
        return float(value)
    return None


def _plant_type(body: dict, errors: list[str]) -> PlantType | None:
    value = body.get('plantType')
    try:
        return PlantType(value)
    except ValueError:
        errors.append(f'plantType: must be one of {[t.value for t in PlantType]}')
        return None


def _storage_kind(body: dict, errors: list[str]) -> StorageKind | None:
    value = body.get('kind')
    try:
        return StorageKind(value)
    except ValueError:
        errors.append(f'kind: must be one of {[k.value for k in StorageKind]}')
        return None


def parse_plant_purchase_request(body: dict) -> tuple[PlantType, float]:
    """A request to buy a new plant. Carries ``plantType``/``capacityMw`` rather than
    a price: the amount charged is computed server-side from ``billing.PlantPricing``,
    so a client can never dictate what it pays.

    No zone is named: a plant is not owned by any zone, so its price is charged
    against the single shared Grid wallet.
    """
    errors: list[str] = []
    plant_type = _plant_type(body, errors)
    capacity_mw = _number(body, 'capacityMw', errors, positive=True)
    if errors:
        raise RequestValidationError(errors)
    return plant_type, capacity_mw


def parse_plant_upgrade_request(body: dict) -> tuple[PlantType, float, float]:
    """A request to grow an existing plant's capacity -- charges only the difference
    between what it costs at ``oldCapacityMw`` and at ``newCapacityMw``, so shrinking a
    plant (or leaving it unchanged) costs nothing."""
    errors: list[str] = []
    plant_type = _plant_type(body, errors)
    old_capacity_mw = _number(body, 'oldCapacityMw', errors, positive=False)
    new_capacity_mw = _number(body, 'newCapacityMw', errors, positive=True)
    if errors:
        raise RequestValidationError(errors)
    return plant_type, old_capacity_mw, new_capacity_mw


def parse_plant_decommission_request(body: dict) -> tuple[PlantType, float]:
    """A request to decommission a plant and receive a partial refund, computed the
    same way a purchase's price is: server-side, from ``billing.PlantPricing``, keyed
    on the same type/capacity the plant was actually built with."""
    errors: list[str] = []
    plant_type = _plant_type(body, errors)
    capacity_mw = _number(body, 'capacityMw', errors, positive=True)
    if errors:
        raise RequestValidationError(errors)
    return plant_type, capacity_mw


def parse_storage_purchase_request(body: dict) -> tuple[StorageKind, float]:
    """Mirrors ``parse_plant_purchase_request``: no price, no owning zone -- storage
    serves the whole grid the same way a plant does, so this always charges the
    shared Grid wallet."""
    errors: list[str] = []
    kind = _storage_kind(body, errors)
    capacity_kwh = _number(body, 'capacityKwh', errors, positive=True)
    if errors:
        raise RequestValidationError(errors)
    return kind, capacity_kwh


def wallet_response(wallet: 'orm.Wallet') -> dict:
    return {
        'zoneId': wallet.zone_id,
        'zoneName': wallet.zone_name,
        'balanceRupees': wallet.balance_rupees,
        'updatedAt': wallet.updated_at.isoformat() if wallet.updated_at else None,
    }


def billing_record_response(record: 'orm.BillingRecord') -> dict:
    return {
        'zoneId': record.zone_id,
        'zoneName': record.zone_name,
        'tickNumber': record.tick_number,
        'kwh': record.kwh,
        'overageKwh': record.overage_kwh,
        'ratePerKwh': record.rate_per_kwh,
        'costRupees': record.cost_rupees,
        'overageCostRupees': record.overage_cost_rupees,
        'recordedAt': record.recorded_at.isoformat(),
    }


def transaction_response(transaction: 'orm.WalletTransaction') -> dict:
    return {
        'zoneId': transaction.zone_id,
        'type': transaction.type,
        'amountRupees': transaction.amount_rupees,
        'balanceAfterRupees': transaction.balance_after_rupees,
        'occurredAt': transaction.occurred_at.isoformat(),
    }


def plant_spend_response(wallet_id: str, wallet_name: str, amount_rupees: float, balance_rupees: float) -> dict:
    """What a plant/storage purchase, upgrade or decommission actually charged (or
    refunded) against the shared Grid wallet -- the server-computed amount, not an
    echo of the request. ``amountRupees`` is 0 for an upgrade that didn't raise the
    plant's price (e.g. a downgrade)."""
    return {
        'walletId': wallet_id,
        'walletName': wallet_name,
        'amountRupees': amount_rupees,
        'balanceRupees': balance_rupees,
        'occurredAt': timezone.now().isoformat(),
    }


def unlocks_response(unlocked_types: list[PlantType], cumulative_kwh_sold: float,
                      next_unlock: tuple[PlantType, float] | None) -> dict:
    return {
        'unlockedTypes': [t.value for t in unlocked_types],
        'cumulativeKwhSold': cumulative_kwh_sold,
        'nextUnlock': {'type': next_unlock[0].value, 'kwhRemaining': next_unlock[1]} if next_unlock else None,
    }


def summary_response(revenue_rupees: float, spend_rupees: float) -> dict:
    return {'revenueRupees': revenue_rupees, 'spendRupees': spend_rupees}


def api_error(status: HTTPStatus, message: str, details: list[str] | None = None) -> dict:
    """The single error shape for this API."""
    return {
        'timestamp': timezone.now().isoformat(),
        'status': status.value,
        'error': status.phrase,
        'message': message,
        'details': details or [],
    }
