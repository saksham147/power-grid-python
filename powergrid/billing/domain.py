"""Framework-free values for the billing app: wallets, wallet ledger movements, plant
and storage kinds, and what one billing cycle produced.

No Django import anywhere in this file, the same discipline ``customer.domain`` and
``distributor.domain`` follow, so these can be reasoned about and tested with no
database, cache or web framework in the picture.
"""
import dataclasses
import datetime
import enum
import math

# The shared wallet that pays for plant/storage purchases and upkeep, and earns what
# every zone is billed. Not tied to any zone id a real installation would ever assign,
# so it can never collide with one.
GRID_WALLET_ID = 'GRID'
GRID_WALLET_NAME = 'Grid Treasury'


def _require_text(value, message: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)


def _require_finite(value, message: str) -> None:
    # Booleans are rejected (bool is a subclass of int), and so are NaN and Infinity,
    # which would otherwise slip past comparisons and corrupt every total they joined.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(message)


def _require_non_negative_finite(value, message: str) -> None:
    _require_finite(value, message)
    if value < 0:
        raise ValueError(message)


class PlantType(enum.Enum):
    """The kinds of generation this simulation models -- billing's own copy of
    ``producer.models.PlantType``, kept as its own type rather than importing it, so a
    plant's purchase price can be computed from the same type Producer will build
    without coupling this app to Producer's module structure."""

    THERMAL = 'THERMAL'
    SOLAR = 'SOLAR'
    WIND = 'WIND'


class StorageKind(enum.Enum):
    """The kinds of storage this simulation models -- billing's own copy, the same
    convention ``PlantType`` already follows."""

    BATTERY = 'BATTERY'
    HYDROGEN = 'HYDROGEN'


class TransactionType(enum.Enum):
    """What kind of wallet movement a ``WalletTransaction`` represents."""

    # A consumption charge, applied automatically every tick regardless of balance.
    BILL_DEBIT = 'BILL_DEBIT'
    # A voluntary spend -- building a new plant -- refused rather than allowed to push
    # the wallet into debt. See WalletSpendingService.
    PLANT_PURCHASE = 'PLANT_PURCHASE'
    # A voluntary spend -- growing an existing plant's capacity -- charged only the
    # difference between its old and new price.
    PLANT_UPGRADE = 'PLANT_UPGRADE'
    # A mandatory, unconditional charge -- per-tick upkeep on every active plant,
    # applied regardless of balance the same way BILL_DEBIT is.
    PLANT_MAINTENANCE = 'PLANT_MAINTENANCE'
    # A credit -- the partial refund paid out when a plant is decommissioned.
    PLANT_DECOMMISSION = 'PLANT_DECOMMISSION'
    # A voluntary spend -- building a new storage unit.
    STORAGE_PURCHASE = 'STORAGE_PURCHASE'
    # A credit to the Grid wallet -- the operator's side of a customer's BILL_DEBIT,
    # one per bill and for the same amount, so what consumers pay is what the grid
    # earns. Kept separate from BILL_DEBIT on purpose: revenue is summed from
    # BILL_DEBIT rows, and counting both sides of one payment would double it.
    BILL_REVENUE = 'BILL_REVENUE'


@dataclasses.dataclass(frozen=True)
class Wallet:
    """A running balance -- a zone's, or the shared Grid wallet. One per zone,
    created lazily the first time that zone is billed or spends.

    ``balance_rupees`` is allowed to go negative: a real ledger permits debt rather
    than silently clamping at zero and losing track of what a wallet actually owes.
    Only a voluntary spend (see ``WalletSpendingService.spend``) is ever refused for
    insufficient funds; a mandatory billing charge always applies.
    """

    zone_id: str
    zone_name: str
    balance_rupees: float
    updated_at: datetime.datetime | None = None

    def __post_init__(self):
        _require_text(self.zone_id, 'zone_id must not be blank')
        _require_text(self.zone_name, f'wallet {self.zone_id} must have a name')
        _require_finite(self.balance_rupees, f'wallet {self.zone_id} must have a finite balance_rupees')


@dataclasses.dataclass(frozen=True)
class WalletTransaction:
    """One wallet ledger movement. Insert-only, and deliberately separate from a
    billing record: a billing record is *why* a charge happened (the kWh and rate
    behind it); this is the wallet movement itself. They carry near-identical numbers
    for a billing charge, but a non-billing debit (spending the wallet on a new plant)
    has a transaction with no billing record behind it.
    """

    zone_id: str
    type: TransactionType
    amount_rupees: float
    balance_after_rupees: float
    occurred_at: datetime.datetime

    def __post_init__(self):
        _require_text(self.zone_id, 'zone_id must not be blank')
        if not isinstance(self.type, TransactionType):
            raise ValueError(f'transaction for {self.zone_id} must have a type')
        _require_non_negative_finite(self.amount_rupees, f'transaction for {self.zone_id} must have a non-negative, finite amount_rupees')
        _require_finite(self.balance_after_rupees, f'transaction for {self.zone_id} must have a finite balance_after_rupees')


@dataclasses.dataclass(frozen=True)
class BillingResult:
    """One zone's billing cycle outcome: what it consumed, what it cost, and the
    wallet balance after the charge was applied.

    ``overage_kwh`` is how much of ``kwh`` was above the zone's assigned capacity (0
    for an uncapped zone, or one drawing within its capacity). ``overage_cost_rupees``
    is the portion of ``cost_rupees`` charged at the overage rate -- already included
    in ``cost_rupees``, broken out here for transparency.
    """

    zone_id: str
    zone_name: str
    tick: int
    kwh: float
    overage_kwh: float
    rate_per_kwh: float
    cost_rupees: float
    overage_cost_rupees: float
    balance_after_rupees: float
    timestamp: datetime.datetime

    def __post_init__(self):
        _require_text(self.zone_id, 'zone_id must not be blank')
        _require_text(self.zone_name, f'zone {self.zone_id} must have a name')
        for field, message in (
            (self.kwh, 'kwh'), (self.overage_kwh, 'overage_kwh'), (self.rate_per_kwh, 'rate_per_kwh'),
            (self.cost_rupees, 'cost_rupees'), (self.overage_cost_rupees, 'overage_cost_rupees'),
        ):
            _require_non_negative_finite(field, f'zone {self.zone_id} must have a non-negative, finite {message}')
        _require_finite(self.balance_after_rupees, f'zone {self.zone_id} must have a finite balance_after_rupees')
