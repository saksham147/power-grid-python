"""Compresses raw per-zone balance history once it ages past retention, keyed by
simulated days rather than wall-clock time.

Why simulated days, not wall-clock time: "keep the last 15 simulation days" has to mean
15 days of simulated history regardless of how much real time that took to arrive -- a
session left idle overnight, or a restart mid-run, must not silently change how far back
the raw data reaches. The cutoff is therefore a tick number,
``latest_tick - RAW_RETENTION_DAYS * TICKS_PER_DAY``, not a timestamp comparison the way
``producer.history`` uses.

Rolling, not end-of-day: each attempt rolls up whatever has aged out since the last one,
rather than compressing a simulated day the moment it ends. The last
``RAW_RETENTION_DAYS`` simulated days therefore stay raw at every moment, a missed
attempt is absorbed by the next one with no catch-up logic, and each transaction moves a
bounded slice of rows instead of an unbounded one.

Nothing in this app runs its own scheduler or its own tick loop -- it reacts to producer
output and zone demand as they arrive. ``maybe_roll_up`` is meant to be called from
whatever drives that reaction (a future messaging listener), the same way
``producer.signals`` calls its own app's rollup once per tick: cheap to call often, a
no-op between intervals.
"""
import dataclasses
import datetime
import logging

from django.db import connection, transaction
from django.utils import timezone

from simulation.clock import TICKS_PER_DAY

from .models import DistributionDailyRollup, DistributionRecord

logger = logging.getLogger(__name__)

# Simulated days of per-tick rows kept raw before being rolled up.
RAW_RETENTION_DAYS = 15

# How often a rollup is attempted, in real time; each attempt moves only what has aged
# out since the last one.
ROLLUP_INTERVAL = datetime.timedelta(minutes=10)

ROLLUP_ENABLED = True

# When this process last attempted a rollup. None means "not yet", which makes the
# first call after startup attempt one immediately -- what absorbs any backlog left
# while nothing was running.
_last_run_at: datetime.datetime | None = None


@dataclasses.dataclass(frozen=True)
class RollupResult:
    """What one rollup run did."""

    cutoff_tick: int
    buckets_written: int
    raw_deleted: int


def roll_up(latest_tick: int) -> RollupResult | None:
    """Rolls up and removes every raw row strictly before
    ``latest_tick - RAW_RETENTION_DAYS * TICKS_PER_DAY``.

    Returns None if there is nothing to roll: the cutoff would fall at or before tick 0,
    which is true from startup until at least ``RAW_RETENTION_DAYS`` simulated days'
    worth of ticks have actually happened.

    A run can never double-count or lose a row: the summarising insert and the delete
    share one transaction and one cutoff computed once, so a crash rolls both back and
    the next run retries from the same state; and the unique key on
    ``(zone_id, simulated_day)`` turns any duplicate that got through anyway into a
    failed run rather than silently doubled data.
    """
    cutoff_tick = latest_tick - RAW_RETENTION_DAYS * TICKS_PER_DAY
    if cutoff_tick <= 0:
        return None

    record_table = connection.ops.quote_name(DistributionRecord._meta.db_table)
    rollup_table = connection.ops.quote_name(DistributionDailyRollup._meta.db_table)

    with transaction.atomic():
        with connection.cursor() as cursor:
            # Native, set-based insert: the aggregation runs entirely inside Postgres,
            # so no raw row is ever loaded into this process, however large the backlog.
            # Nothing here is summed the way Producer's energy is -- demand/supplied/
            # balance are instantaneous kW readings, not power held over an interval --
            # so avg/min/max is all a bucket keeps; the tick-by-tick shape within the
            # simulated day is what is given up.
            cursor.execute(f"""
                insert into {rollup_table}
                    (zone_id, zone_name, simulated_day,
                     avg_demand_kw, min_demand_kw, max_demand_kw,
                     avg_supplied_kw, min_supplied_kw, max_supplied_kw,
                     avg_balance_kw, min_balance_kw, max_balance_kw,
                     sample_count, first_tick, last_tick)
                select zone_id,
                       max(zone_name),
                       tick_number / %s,
                       avg(demand_kw), min(demand_kw), max(demand_kw),
                       avg(supplied_kw), min(supplied_kw), max(supplied_kw),
                       avg(balance_kw), min(balance_kw), max(balance_kw),
                       count(*), min(tick_number), max(tick_number)
                from {record_table}
                where tick_number < %s
                group by zone_id, tick_number / %s
            """, [TICKS_PER_DAY, cutoff_tick, TICKS_PER_DAY])
            buckets_written = cursor.rowcount

        raw_deleted = DistributionRecord.objects.delete_before(cutoff_tick)

    return RollupResult(cutoff_tick=cutoff_tick, buckets_written=buckets_written, raw_deleted=raw_deleted)


def maybe_roll_up(now: datetime.datetime | None = None) -> RollupResult | None:
    """Attempts a rollup if ROLLUP_INTERVAL has passed since this process last tried
    one (or none has run yet).

    A failure is logged and swallowed, and still counts as an attempt: the raw rows are
    untouched by the rolled-back transaction and simply wait for the next run, and an
    error must not be retried on every call.
    """
    global _last_run_at

    if not ROLLUP_ENABLED:
        return None

    now = now or timezone.now()
    if _last_run_at is not None and now - _last_run_at < ROLLUP_INTERVAL:
        return None
    _last_run_at = now

    try:
        latest_tick = DistributionRecord.objects.max_tick_number()
        if latest_tick is None:
            return None
        result = roll_up(latest_tick)
    except Exception:
        logger.exception('Distribution history rollup failed; raw rows are kept and the next run will retry')
        return None

    if result and result.raw_deleted:
        logger.info('Rolled %s raw rows into %s zone-day buckets (before tick %s)',
                    result.raw_deleted, result.buckets_written, result.cutoff_tick)
    return result
