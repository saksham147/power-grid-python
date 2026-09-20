"""Compresses raw generation history once it ages past retention, and reads it back.

Ported from Power-Grid's ``Producer.history`` package (Java): ``GenerationRollupJob``,
``HistoryProperties``, ``GenerationHistoryQuery``, ``HistoryPoint``, ``RollupResult``.

Rolling, not end-of-day: each run rolls up whatever has aged past RAW_RETENTION, so
the last 24 hours stay raw at every moment, a missed run is absorbed by the next one
with no catch-up logic, and each transaction moves minutes of rows instead of a day's.

In the Java service the job is scheduled on the same single-thread scheduler as the
tick loop, so a rollup can never run concurrently with a tick writing to the same
table. Here both already share a thread for the same reason: ``runsimulation`` fires
``tick_advanced`` and every receiver runs synchronously inside that call, so
``producer.signals`` invokes ``maybe_roll_up`` once per tick and it does nothing
until ROLLUP_INTERVAL has elapsed.
"""
import contextlib
import dataclasses
import datetime
import enum
import logging

from django.db import connection, transaction
from django.utils import timezone

from simulation.clock import SIMULATED_MINUTES_PER_TICK
from simulation.clock import energy_mwh as tick_energy_mwh

from .models import GenerationRecord, GenerationRollup

logger = logging.getLogger(__name__)

# How long per-tick rows stay raw before being rolled up.
RAW_RETENTION = datetime.timedelta(hours=24)

# How often the rollup runs; each run moves only what has aged out since the last.
ROLLUP_INTERVAL = datetime.timedelta(minutes=10)

ROLLUP_ENABLED = True

# When this process last attempted a rollup. None means "not yet", which makes the
# first tick after startup run one immediately -- what absorbs any backlog left while
# nothing was running, the same reason the Java job fires on ApplicationReadyEvent.
_last_run_at: datetime.datetime | None = None


@dataclasses.dataclass(frozen=True)
class RollupResult:
    """What one rollup run did.

    ``cutoff``: rows recorded before this instant were rolled up; always on a whole
    minute. ``raw_deleted`` is normally 12 x ``buckets_written``.
    """

    cutoff: datetime.datetime
    buckets_written: int
    raw_deleted: int


def roll_up(now: datetime.datetime) -> RollupResult:
    """Rolls up and removes every raw row recorded before ``now - RAW_RETENTION``,
    truncated to the minute.

    A run can never double-count or lose a row:

    * the summarising insert and the delete share one transaction and one cutoff, so
      a crash rolls both back and the next run retries from the same state;
    * the cutoff is truncated to a whole minute, so a bucket is only ever rolled
      once and complete -- an untruncated cutoff would split a minute across two
      runs and write two rows for it;
    * the unique key on (plant_id, bucket_start) turns any duplicate that got through
      anyway into a failed run instead of silently doubled energy.
    """
    cutoff = (now - RAW_RETENTION).replace(second=0, microsecond=0)

    record_table = connection.ops.quote_name(GenerationRecord._meta.db_table)
    rollup_table = connection.ops.quote_name(GenerationRollup._meta.db_table)

    with transaction.atomic():
        with connection.cursor() as cursor:
            # Set-based and native: the aggregation runs entirely inside Postgres, so
            # no raw row is ever loaded into this process, however large the backlog.
            # Energy is summed per tick (output held for the tick's simulated minutes)
            # so a bucket's energy_mwh is exactly the total of the rows it replaces.
            cursor.execute(f"""
                insert into {rollup_table}
                    (plant_id, plant_type, bucket_start,
                     avg_output_mw, min_output_mw, max_output_mw,
                     energy_mwh, sample_count, first_tick, last_tick)
                select plant_id,
                       plant_type,
                       date_trunc('minute', recorded_at),
                       avg(output_mw),
                       min(output_mw),
                       max(output_mw),
                       (sum(output_mw) * %s) / 60,
                       count(*),
                       min(tick_number),
                       max(tick_number)
                from {record_table}
                where recorded_at < %s
                group by plant_id, plant_type, date_trunc('minute', recorded_at)
            """, [SIMULATED_MINUTES_PER_TICK, cutoff])
            buckets_written = cursor.rowcount

        raw_deleted, _ = GenerationRecord.objects.filter(recorded_at__lt=cutoff).delete()

    return RollupResult(cutoff=cutoff, buckets_written=buckets_written, raw_deleted=raw_deleted)


def maybe_roll_up(now: datetime.datetime | None = None) -> RollupResult | None:
    """Runs a rollup if ROLLUP_INTERVAL has passed since this process last tried one
    (or none has run yet). Called once per tick from ``producer.signals``.

    A failure is logged and swallowed, and still counts as an attempt: the raw rows
    are untouched by the rolled-back transaction and simply wait for the next run,
    and an error must not be retried on every tick.
    """
    global _last_run_at

    if not ROLLUP_ENABLED:
        return None

    now = now or timezone.now()
    if _last_run_at is not None and now - _last_run_at < ROLLUP_INTERVAL:
        return None
    _last_run_at = now

    try:
        result = roll_up(now)
    except Exception:
        logger.exception('History rollup failed; raw rows are kept and the next run will retry')
        return None

    if result.raw_deleted:
        logger.info('Rolled %s raw rows into %s buckets (before %s)',
                    result.raw_deleted, result.buckets_written, result.cutoff)
    return result


class Resolution(enum.Enum):
    RAW = 'RAW'
    ROLLUP = 'ROLLUP'


@dataclasses.dataclass(frozen=True)
class HistoryPoint:
    """One point in a plant's generation history, from either table.

    Raw and rolled-up rows share this shape so a caller receives one series, but
    ``resolution`` says which it is: a chart must not draw a per-tick reading and an
    hourly average as if they meant the same thing.

    ``at`` is when the reading was taken, or when the bucket began. ``output_mw`` is
    the reading or the bucket average (min/max equal it for a raw point). ``samples``
    is the ticks covered: 1 raw, normally 12 rolled up. ``energy_mwh`` is exact in
    both cases.
    """

    at: datetime.datetime
    resolution: Resolution
    output_mw: float
    min_output_mw: float
    max_output_mw: float
    energy_mwh: float
    samples: int
    first_tick: int
    last_tick: int

    @classmethod
    def from_record(cls, record: GenerationRecord) -> 'HistoryPoint':
        return cls(
            at=record.recorded_at,
            resolution=Resolution.RAW,
            output_mw=record.output_mw,
            min_output_mw=record.output_mw,
            max_output_mw=record.output_mw,
            energy_mwh=tick_energy_mwh(record.output_mw),
            samples=1,
            first_tick=record.tick_number,
            last_tick=record.tick_number,
        )

    @classmethod
    def from_rollup(cls, rollup: GenerationRollup) -> 'HistoryPoint':
        return cls(
            at=rollup.bucket_start,
            resolution=Resolution.ROLLUP,
            output_mw=rollup.avg_output_mw,
            min_output_mw=rollup.min_output_mw,
            max_output_mw=rollup.max_output_mw,
            energy_mwh=rollup.energy_mwh,
            samples=rollup.sample_count,
            first_tick=rollup.first_tick,
            last_tick=rollup.last_tick,
        )


@contextlib.contextmanager
def _consistent_snapshot():
    """Gives every query inside it the same REPEATABLE READ snapshot.

    Load-bearing: the rollup job moves rows *between* the two history tables. Under
    the default READ COMMITTED each query takes its own snapshot, so a rollup
    committing between them could show a minute twice (its raw points and its
    rollup) or drop it entirely. One snapshot puts each minute in exactly one table.

    If the caller is already inside a transaction its isolation level is theirs to
    choose, and Postgres refuses to change it once a query has run, so this
    leaves it alone.
    """
    if connection.in_atomic_block:
        yield
        return
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        yield


def history(plant_id: int, start: datetime.datetime, end: datetime.datetime,
            limit: int) -> list[HistoryPoint]:
    """A plant's history across both tables as one newest-first series over the
    half-open range ``[start, end)``.

    Each table is limited to ``limit`` before the merge; the newest ``limit`` points
    of the combined series are always within those.
    """
    with _consistent_snapshot():
        raw = list(GenerationRecord.objects.history(plant_id, start, end)[:limit])
        rolled = list(GenerationRollup.objects.history(plant_id, start, end)[:limit])

    points = [HistoryPoint.from_record(r) for r in raw] + [HistoryPoint.from_rollup(r) for r in rolled]
    points.sort(key=lambda p: p.at, reverse=True)
    return points[:limit]


def last_known_tick() -> int:
    """The highest tick number either table has ever recorded, across every plant,
    or 0 if there is no history yet.

    Best-effort, not exact: a tick over an empty fleet writes no row at all, so
    ticks issued while every plant was inactive right up to a shutdown are not
    recoverable from here.
    """
    raw_max = GenerationRecord.objects.max_tick_number()
    rolled_max = GenerationRollup.objects.max_last_tick()
    return max(raw_max or 0, rolled_max or 0)
