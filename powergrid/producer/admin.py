from django.contrib import admin

from .models import GenerationRecord, PowerPlant


@admin.register(PowerPlant)
class PowerPlantAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'type', 'capacity_mw', 'current_output_mw', 'energy_mwh', 'active')
    list_filter = ('type', 'active')
    # current_output_mw is derived (set to base_output_mw on creation, then written
    # back every tick by the simulation) -- never entered by hand.
    readonly_fields = ('current_output_mw', 'energy_mwh')


@admin.register(GenerationRecord)
class GenerationRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'plant_id', 'plant_type', 'tick_number', 'output_mw', 'frequency_deviation', 'recorded_at')
    list_filter = ('plant_type',)
    ordering = ('-tick_number',)

    def has_add_permission(self, request):
        # Insert-only history, written by the simulation loop.
        return False

    def has_change_permission(self, request, obj=None):
        return False
