from django.contrib import admin

from .models import SimulationState


@admin.register(SimulationState)
class SimulationStateAdmin(admin.ModelAdmin):
    list_display = ('current_tick', 'frequency_deviation_hz', 'auto_control')
    readonly_fields = ('current_tick',)

    def has_add_permission(self, request):
        return not SimulationState.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
