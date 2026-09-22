from django.contrib import admin

from .models import DistributionDailyRollup, DistributionRecord, ZoneCapacity


@admin.register(DistributionRecord)
class DistributionRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'zone_id', 'zone_name', 'tick_number', 'demand_kw', 'supplied_kw', 'balance_kw', 'recorded_at')
    list_filter = ('zone_id',)
    ordering = ('-tick_number',)

    def has_add_permission(self, request):
        # Insert-only history, written by the distribution logger.
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ZoneCapacity)
class ZoneCapacityAdmin(admin.ModelAdmin):
    list_display = ('zone_id', 'zone_name', 'capacity_kw', 'updated_at')
    readonly_fields = ('updated_at',)


@admin.register(DistributionDailyRollup)
class DistributionDailyRollupAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'zone_id', 'simulated_day', 'avg_demand_kw', 'avg_supplied_kw',
        'avg_balance_kw', 'sample_count',
    )
    list_filter = ('zone_id',)
    ordering = ('-simulated_day',)

    def has_add_permission(self, request):
        # Written only by the rollup job's INSERT...SELECT.
        return False

    def has_change_permission(self, request, obj=None):
        return False
