"""Wire-shaped payloads Producer publishes.

Ported from Power-Grid's ``Producer.event`` (Java). A plain frozen dataclass rather
than a model or a dict, so it crosses ``producer.kafka`` the way it would cross a
real topic: a documented, structural shape, not a live ORM object a subscriber could
accidentally mutate or re-save.

The other Java record, ``GridTickEvent``, is what Producer *consumes*. Here that is
the shared clock's ``simulation.signals.tick_advanced`` signal, whose keyword
arguments (``tick_number``, ``frequency_deviation``) are exactly its fields, so
Producer keeps no local mirror of it.
"""
import dataclasses
import datetime


@dataclasses.dataclass(frozen=True)
class ProducerOutputEvent:
    """One plant's contribution for one tick.

    ``timestamp`` is the same instant stamped on that plant's ``GenerationRecord``
    for the tick, so a history row and its event match exactly.

    In Kafka this is keyed by ``producer_id``, which pins one plant's history to one
    ordered partition for every downstream consumer. There is no partition to order
    across here, so the field is kept for shape parity, not for ordering.
    """

    producer_id: int
    tick_number: int
    output_mw: float
    timestamp: datetime.datetime
