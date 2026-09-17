"""In-process pub/sub standing in for Grid's ``grid.tick`` Kafka topic.

In Power-Grid, Producer/Customer/Distributor/Billing each subscribe to the tick topic
independently and react in parallel, with no orchestrator waiting for all of them.
Since this is one Django process rather than five independently deployed services,
a Django signal gives the same "publish once, N independent reactors" shape without
a broker.

Any app can subscribe, typically in its ``AppConfig.ready()``::

    from django.dispatch import receiver
    from simulation.signals import tick_advanced

    @receiver(tick_advanced)
    def on_tick(sender, tick_number, frequency_deviation, **kwargs):
        ...

``runsimulation`` sends this once per tick, after persisting the new
:class:`~simulation.models.SimulationState`, so every receiver can safely call
``SimulationState.load()`` and see a consistent value.
"""
import django.dispatch

tick_advanced = django.dispatch.Signal()
