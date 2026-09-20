"""Stands in for Producer's Kafka publisher (the ``producer.output`` topic).

Ported from ``Producer.kafka.ProducerOutputPublisher``. This project has no broker,
so publishing is a Django signal: any app -- Grid summing fleet supply, Distributor
merging it against demand -- subscribes without importing ``producer``, the same
"one publish, N independent consumers" shape Kafka gives the Java services::

    from django.dispatch import receiver
    from producer.kafka import output_published

    @receiver(output_published)
    def on_output(sender, event, **kwargs):  # event: producer.events.ProducerOutputEvent
        ...
"""
import logging

import django.dispatch

from .events import ProducerOutputEvent

logger = logging.getLogger(__name__)

TOPIC = 'producer.output'

output_published = django.dispatch.Signal()


def publish(events: list[ProducerOutputEvent]) -> None:
    """One dispatch per plant, mirroring the Java publisher's one message per plant.

    Uses ``send_robust`` so a broken subscriber is logged and skipped rather than
    raised into Producer: like a broker outage in the Java service, a bad consumer
    is expected to cost itself its events, never the tick or the other subscribers.
    Django logs each failure's traceback itself; the line below only adds which
    event it was.
    """
    for event in events:
        for subscriber, response in output_published.send_robust(sender=None, event=event):
            if isinstance(response, Exception):
                logger.error('%s subscriber %r failed on plant %s tick %s: %r',
                             TOPIC, subscriber, event.producer_id, event.tick_number, response)
