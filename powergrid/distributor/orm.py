"""Django ORM adapters for the distribution use case's ports.

Backs ``distribution.DistributionLogger`` with an insert into ``DistributionRecord``,
and ``distribution.ZoneCapacityRepository`` with the ``ZoneCapacity`` table -- the
concrete Postgres side of the abstractions ``distribution.py`` defines, the same
relationship ``customer.infrastructure.redis`` has to ``customer.application``'s ports.
"""
from django.utils import timezone

from . import models as orm
from .distribution import DistributionLogger, ZoneCapacityRepository
from .domain import ZoneCapacity, ZoneDistribution


class DjangoDistributionLogger(DistributionLogger):
    """Writes one row per merged balance. A plain insert is already a single round
    trip: unlike Producer's per-tick batch of many plants, this is one zone per demand
    reading, so there is no identity-batching concern to work around.

    ``recorded_at`` is when this row was written, not ``distribution.at`` (when the
    demand reading the balance was merged against occurred) -- the two are effectively
    simultaneous here, but they answer different questions.
    """

    def log(self, distribution: ZoneDistribution) -> None:
        orm.DistributionRecord.objects.create(
            zone_id=distribution.zone_id,
            zone_name=distribution.zone_name,
            tick_number=distribution.tick,
            demand_kw=distribution.demand_kw,
            supplied_kw=distribution.supplied_kw,
            balance_kw=distribution.balance_kw,
            recorded_at=timezone.now(),
        )


def _to_domain(row: orm.ZoneCapacity) -> ZoneCapacity:
    return ZoneCapacity(zone_id=row.zone_id, zone_name=row.zone_name, capacity_kw=row.capacity_kw)


class DjangoZoneCapacityRepository(ZoneCapacityRepository):
    """Persists zone-capacity configuration in Postgres."""

    def find_by_id(self, zone_id: str) -> ZoneCapacity | None:
        try:
            return _to_domain(orm.ZoneCapacity.objects.get(pk=zone_id))
        except orm.ZoneCapacity.DoesNotExist:
            return None

    def find_all(self) -> list[ZoneCapacity]:
        return [_to_domain(row) for row in orm.ZoneCapacity.objects.order_by('zone_id')]

    def save(self, capacity: ZoneCapacity) -> None:
        """Adds a zone's capacity, or replaces one with the same id -- an upsert, so
        ``ZoneCapacityService.upsert`` never needs to look one up first."""
        orm.ZoneCapacity.objects.update_or_create(
            zone_id=capacity.zone_id,
            defaults={'zone_name': capacity.zone_name, 'capacity_kw': capacity.capacity_kw},
        )

    def delete(self, zone_id: str) -> None:
        orm.ZoneCapacity.objects.filter(pk=zone_id).delete()
