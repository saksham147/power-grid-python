import time

from django.core.management.base import BaseCommand

from simulation.clock import REAL_TIME_PER_TICK_SECONDS, day_number, time_of_day
from simulation.models import SimulationState
from simulation.services import advance_tick
from simulation.signals import tick_advanced


class Command(BaseCommand):
    help = (
        'Runs the shared simulation clock: one tick every '
        f'{REAL_TIME_PER_TICK_SECONDS} real second(s) (288 ticks = 1 simulated day). '
        'Every app subscribed to simulation.signals.tick_advanced reacts '
        "independently, the same way Producer/Customer/Distributor/Billing each "
        "react to Grid's grid.tick topic in Power-Grid."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--once', action='store_true',
            help='Run a single tick and exit, instead of looping.',
        )

    def handle(self, *args, **options):
        state = SimulationState.load()
        if state.current_tick:
            self.stdout.write(
                f'Resuming at tick {state.current_tick} '
                f'(day {day_number(state.current_tick)}, {time_of_day(state.current_tick)})'
            )

        try:
            while True:
                state = advance_tick()
                tick_advanced.send(
                    sender=self.__class__,
                    tick_number=state.current_tick,
                    frequency_deviation=state.frequency_deviation_hz,
                )
                self.stdout.write(
                    f'tick {state.current_tick:>6}  day {day_number(state.current_tick):>3}  '
                    f'{time_of_day(state.current_tick)}  '
                    f'deviation {state.frequency_deviation_hz:+.3f} Hz'
                )
                if options['once']:
                    break
                time.sleep(REAL_TIME_PER_TICK_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Simulation stopped.'))
