"""The billing-cycle use case, the voluntary-spend use case, server-side pricing, and
unlock/tech-tree gating.

Deliberately free of Django: both services depend only on the ports below, which is
what keeps the pricing math testable with fakes and no database or messaging in the
picture -- the same shape ``distributor.distribution.DistributionService`` already
uses. ``ZoneCapacityCache`` is an exception to "no framework specifics", but it is
itself framework-free (a plain, lock-guarded map), so it costs these services nothing
to depend on directly -- there is no adapter seam worth a third port for a read this
cheap.

Callers pass plain values, not a wire-shaped event -- the same shape
``distributor.distribution.DistributionService.on_zone_demand`` takes. Unpacking an
incoming message into these values belongs to a future messaging adapter, not here.
"""
import abc
import datetime
import logging
import threading

from simulation.clock import SIMULATED_MINUTES_PER_TICK

from .domain import BillingResult, PlantType, StorageKind, TransactionType, Wallet, WalletTransaction

logger = logging.getLogger(__name__)

_MINUTES_PER_HOUR = 60.0


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ZoneCapacityCache:
    """Billing's read-only mirror of Distributor's zone-capacity configuration, kept
    in memory rather than a database table -- the same reasoning
    ``distributor.distribution.GridStateTracker`` already gives for its own in-memory
    maps: this is Distributor's data, rebuilt from its broadcast rather than queried
    back or duplicated into a table Billing would then have to keep in sync itself.

    A zone absent from this cache is uncapped: billed at the normal rate only. A
    capacity *removal* ends up looking exactly the same, since ``set`` evicts the
    entry rather than storing ``None``.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._capacity_kw_by_zone: dict[str, float] = {}

    def set(self, zone_id: str, capacity_kw: float | None) -> None:
        with self._lock:
            if capacity_kw is None:
                self._capacity_kw_by_zone.pop(zone_id, None)
            else:
                self._capacity_kw_by_zone[zone_id] = capacity_kw

    def get(self, zone_id: str) -> float | None:
        with self._lock:
            return self._capacity_kw_by_zone.get(zone_id)


class PlantPricing:
    """What a new plant costs to build, by type and capacity -- the authoritative
    formula. A client-supplied amount is never trusted; this is the one that actually
    gets charged.

    ``cost = max(minimum, base + progressive per-MW cost)``: base is the fixed setup
    cost, minimum is a floor so a tiny plant is never near-free. The per-MW cost is
    banded rather than flat -- like a tax bracket, each band only charges its own rate
    on the slice of capacity that falls inside it, and the rate rises band to band.
    This keeps a plant's marginal MW getting steadily more expensive as it grows,
    without changing the shape of a purchase or an upgrade: ``cost`` still takes just a
    type and a capacity, so an upgrade's ``new_cost - old_cost`` delta needs no special
    handling.
    """

    # (base, minimum, [(upto_mw, per_mw), ...]) -- bands must be given in ascending
    # upto_mw order; the last band's upto_mw should cover any realistic capacity.
    _RATES = {
        PlantType.THERMAL: (2000, 5000, ((300, 8), (600, 10), (float('inf'), 14))),
        PlantType.WIND: (1000, 3000, ((50, 16), (100, 20), (float('inf'), 26))),
        PlantType.SOLAR: (500, 2000, ((50, 8), (150, 10), (float('inf'), 13))),
    }

    @classmethod
    def cost(cls, plant_type: PlantType, capacity_mw: float) -> float:
        base, minimum, bands = cls._RATES[plant_type]

        banded_cost = 0.0
        covered_mw = 0.0
        for upto_mw, per_mw in bands:
            mw_in_band = max(0.0, min(capacity_mw, upto_mw) - covered_mw)
            banded_cost += mw_in_band * per_mw
            covered_mw = upto_mw
            if capacity_mw <= upto_mw:
                break

        return max(minimum, base + banded_cost)


class StoragePricing:
    """What a new storage unit costs to build, by kind and energy capacity -- kept
    separate from ``PlantPricing``/``PlantType`` entirely, so adding a storage kind
    never risks a lookup miss against a type it was never designed for.

    ``cost = max(minimum, base + per_kwh * capacity_kwh)``.
    """

    # (base, per_kwh, minimum)
    _RATES = {
        StorageKind.BATTERY: (1500, 5, 3000),
        StorageKind.HYDROGEN: (3000, 8, 6000),
    }

    @classmethod
    def cost(cls, storage_kind: StorageKind, capacity_kwh: float) -> float:
        base, per_kwh, minimum = cls._RATES[storage_kind]
        return max(minimum, base + per_kwh * capacity_kwh)


class UnlockThresholds:
    """kWh-sold thresholds that unlock each plant type for purchase. THERMAL is
    unlocked from zero (every simulation starts able to build one); SOLAR and WIND sit
    behind reachable thresholds so a fresh grid has something to work toward before the
    full fleet is available.
    """

    _THRESHOLDS = {
        PlantType.THERMAL: 0.0,
        PlantType.SOLAR: 50_000.0,
        PlantType.WIND: 150_000.0,
    }

    @classmethod
    def threshold_for(cls, plant_type: PlantType) -> float:
        return cls._THRESHOLDS[plant_type]

    @classmethod
    def is_unlocked(cls, plant_type: PlantType, cumulative_kwh_sold: float) -> bool:
        return cumulative_kwh_sold >= cls.threshold_for(plant_type)


class BillingHistoryReader(abc.ABC):
    """Outbound port: cumulative energy billed so far, across both raw and rolled-up
    history -- a rollup is expected to replace the raw rows it summarises rather than
    sit alongside them, so a correct implementation never double-counts either side."""

    @abc.abstractmethod
    def cumulative_kwh_sold(self) -> float:
        ...


class UnlockService:
    """Turns cumulative kWh sold, grid-wide, into which plant types are currently
    purchasable."""

    def __init__(self, history: BillingHistoryReader):
        self._history = history

    def cumulative_kwh_sold(self) -> float:
        return self._history.cumulative_kwh_sold()

    def is_unlocked(self, plant_type: PlantType) -> bool:
        return UnlockThresholds.is_unlocked(plant_type, self.cumulative_kwh_sold())

    def next_locked(self) -> PlantType | None:
        """The next type still locked, ordered by threshold, or None if every type is
        unlocked."""
        sold = self.cumulative_kwh_sold()
        locked = [t for t in PlantType if not UnlockThresholds.is_unlocked(t, sold)]
        return min(locked, key=UnlockThresholds.threshold_for) if locked else None


class BillingLedger(abc.ABC):
    """Outbound port: applies one zone's already-computed billing cycle charge.

    One method, not the two smaller ports ("record the bill" and "debit the wallet")
    that would otherwise match the rest of this project's outbound-port style. A
    billing charge is one atomic fact -- the record of what was billed and the wallet
    debit it caused must commit or fail together, or a crash between two separate
    calls could either charge a wallet with no record of why, or leave a billing
    record with no debit behind it. The idempotency guard against redelivery lives
    here too, for the same reason: checking "already billed?" and then writing must
    not be two separate steps another delivery of the same reading could interleave
    with.

    A concrete implementation is also expected to credit the shared Grid wallet by the
    same amount (what a zone pays is what the grid earns), creating either wallet with
    the starting balance on its first-ever movement.
    """

    @abc.abstractmethod
    def apply(self, zone_id: str, zone_name: str, tick: int, kwh: float, overage_kwh: float,
              rate_per_kwh: float, cost_rupees: float, overage_cost_rupees: float,
              at: datetime.datetime) -> BillingResult | None:
        """Returns the result, or None if ``(zone_id, tick)`` was already billed -- a
        duplicate delivery of the same reading, applied as a no-op rather than a
        double charge."""


class BillingCycleService:
    """Turns one zone's tick-end demand reading into a billing charge.

    Why every tick is a billing cycle: the shared clock fixes one tick at exactly 5
    simulated minutes, so there is no separate billing-period clock to track -- this
    reacts to every zone-demand reading directly, exactly once per zone per tick, with
    no scheduler of its own, the same reasoning ``DistributionService`` documents for
    why it has no shared-clock listener either.

    The overage surcharge: a zone can draw more than its assigned capacity -- that
    demand is never refused here, Distributor never caps delivery either -- but the
    portion above capacity is billed at ``rate_per_kwh * overage_rate_multiplier``
    rather than the normal rate. A zone with no capacity assigned (nothing in
    ``ZoneCapacityCache``) is uncapped: entirely at the normal rate.
    """

    def __init__(self, rate_per_kwh: float, overage_rate_multiplier: float,
                 capacities: ZoneCapacityCache, ledger: BillingLedger):
        self._rate_per_kwh = rate_per_kwh
        self._overage_rate_multiplier = overage_rate_multiplier
        self._capacities = capacities
        self._ledger = ledger

    def on_zone_demand(self, zone_id: str, zone_name: str, tick: int, demand_kw: float,
                        at: datetime.datetime) -> BillingResult | None:
        """Returns the applied charge, or None if this tick was already billed for
        this zone (a duplicate delivery of the same reading)."""
        kwh = demand_kw * (SIMULATED_MINUTES_PER_TICK / _MINUTES_PER_HOUR)

        capacity_kw = self._capacities.get(zone_id)
        if capacity_kw is not None and demand_kw > capacity_kw:
            overage_kwh = kwh - capacity_kw * (SIMULATED_MINUTES_PER_TICK / _MINUTES_PER_HOUR)
        else:
            overage_kwh = 0.0
        within_kwh = kwh - overage_kwh

        overage_cost = overage_kwh * self._rate_per_kwh * self._overage_rate_multiplier
        cost = within_kwh * self._rate_per_kwh + overage_cost

        return self._ledger.apply(zone_id, zone_name, tick, kwh, overage_kwh, self._rate_per_kwh,
                                  cost, overage_cost, at)


class InsufficientFundsException(Exception):
    """A wallet -- a zone's, or the shared Grid wallet -- was asked to spend more
    than it holds."""

    def __init__(self, wallet_id: str, balance_rupees: float, amount_rupees: float):
        super().__init__(f'Wallet {wallet_id} has ₹{balance_rupees:.2f} but this costs ₹{amount_rupees:.2f}')


class WalletRepository(abc.ABC):
    """Outbound port: reads and writes a wallet -- a zone's, or the shared Grid
    wallet.

    ``get_for_update`` is expected to take a row-level lock held until the surrounding
    transaction ends, for wallets several writers change at once (the Grid wallet
    above all: every customer bill credits it, every plant purchase and maintenance
    charge debits it). A plain read followed by a write is a read-modify-write, and
    two of those overlapping would each start from the same balance and the later
    commit would silently erase the earlier one.
    """

    @abc.abstractmethod
    def get_for_update(self, wallet_id: str) -> Wallet | None:
        ...

    def save(self, wallet: Wallet) -> None:
        """Adds a wallet, or replaces one with the same id."""
        raise NotImplementedError


class WalletTransactionRepository(abc.ABC):
    """Outbound port: records one wallet ledger movement. Insert-only."""

    @abc.abstractmethod
    def save(self, transaction: WalletTransaction) -> None:
        ...


class WalletSpendingService:
    """Voluntary spending from a wallet -- a plant purchase today, more later.

    Deliberately separate from ``BillingCycleService``/``BillingLedger``: a billing
    charge always applies, because a zone cannot refuse to have consumed power it
    already consumed; a spend can be refused, because nothing forces a zone to buy a
    plant it can't afford. Collapsing the two would mean either letting consumption
    charges bounce (wrong) or letting purchases push a wallet into debt (also wrong).
    """

    def __init__(self, wallets: WalletRepository, transactions: WalletTransactionRepository,
                 starting_balance: float):
        self._wallets = wallets
        self._transactions = transactions
        self._starting_balance = starting_balance

    def spend(self, wallet_id: str, wallet_name: str, amount_rupees: float,
              transaction_type: TransactionType = TransactionType.PLANT_PURCHASE) -> float:
        """Returns the balance after the spend.

        Raises ``InsufficientFundsException`` if the wallet cannot cover
        ``amount_rupees``.
        """
        wallet = self._wallets.get_for_update(wallet_id) or Wallet(wallet_id, wallet_name, self._starting_balance)

        if wallet.balance_rupees < amount_rupees:
            raise InsufficientFundsException(wallet_id, wallet.balance_rupees, amount_rupees)

        return self._move(wallet, wallet_name, -amount_rupees, transaction_type, amount_rupees)

    def credit(self, wallet_id: str, wallet_name: str, amount_rupees: float,
               transaction_type: TransactionType) -> float:
        """The symmetric counterpart to ``spend`` -- a credit can never fail, so
        unlike a spend there is no ``InsufficientFundsException`` path here.

        Returns the balance after the credit.
        """
        wallet = self._wallets.get_for_update(wallet_id) or Wallet(wallet_id, wallet_name, self._starting_balance)
        return self._move(wallet, wallet_name, amount_rupees, transaction_type, amount_rupees)

    def _move(self, wallet: Wallet, wallet_name: str, delta_rupees: float,
              transaction_type: TransactionType, amount_rupees: float) -> float:
        now = _now()
        new_balance = wallet.balance_rupees + delta_rupees
        updated = Wallet(wallet.zone_id, wallet_name, new_balance, now)

        self._wallets.save(updated)
        self._transactions.save(WalletTransaction(wallet.zone_id, transaction_type, amount_rupees, new_balance, now))

        return new_balance
