from django.http import JsonResponse

from simulation.clock import day_number, time_of_day
from simulation.models import SimulationState

from .models import GenerationRecord, PowerPlant


def status(request):
    """Point-in-time view of the fleet, driven by the shared simulation clock."""
    tick = SimulationState.load().current_tick
    latest_events = GenerationRecord.objects.filter(tick_number=tick)
    fleet_output_mw = sum(event.output_mw for event in latest_events)
    fleet_energy_mwh = sum(PowerPlant.objects.values_list('energy_mwh', flat=True))

    return JsonResponse({
        'tickNumber': tick,
        'simulatedTime': time_of_day(tick),
        'simulatedDay': day_number(tick),
        'plantCount': PowerPlant.objects.active().count(),
        'lastEventCount': latest_events.count(),
        'fleetOutputMw': fleet_output_mw,
        'fleetEnergyMwh': fleet_energy_mwh,
    })
