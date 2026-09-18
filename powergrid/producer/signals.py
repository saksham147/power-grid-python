"""Connects Producer to the shared simulation clock's tick broadcast.

Ported from ``Producer.simulation.SimulationRunner.onGridTick`` -- there, a
``@KafkaListener`` on ``grid.tick``; here, a receiver on
``simulation.signals.tick_advanced``. Same shape: one call to the generation
service per tick, a failure logged and swallowed rather than raised, so one bad
tick doesn't take down every tick after it.
"""
import logging

from django.dispatch import receiver

from simulation.signals import tick_advanced

from .generation import handle_tick

logger = logging.getLogger(__name__)


@receiver(tick_advanced, dispatch_uid='producer.on_tick_advanced')
def on_tick_advanced(sender, tick_number, frequency_deviation, **kwargs):
    try:
        events = handle_tick(tick_number, frequency_deviation)
    except Exception:
        logger.exception('Tick %s failed in producer; the clock continues', tick_number)
        return
    logger.debug('Producer handled tick %s: %d plants', tick_number, len(events))
