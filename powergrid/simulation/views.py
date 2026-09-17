from django.http import JsonResponse

from .clock import REAL_TIME_PER_TICK_SECONDS, day_number, time_of_day
from .models import SimulationState


def status(request):
    """Point-in-time view of the shared clock, mirroring Power-Grid's
    GET /api/grid/status."""
    state = SimulationState.load()
    return JsonResponse({
        'tickNumber': state.current_tick,
        'simulatedTime': time_of_day(state.current_tick),
        'simulatedDay': day_number(state.current_tick),
        'tickIntervalSeconds': REAL_TIME_PER_TICK_SECONDS,
        'frequencyDeviation': state.frequency_deviation_hz,
        'autoControl': state.auto_control,
    })
