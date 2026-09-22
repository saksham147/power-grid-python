from django.contrib import admin

from .models import BillingDailyRollup, BillingRecord, Wallet, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('zone_id', 'zone_name', 'balance_rupees', 'updated_at')


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'zone_id', 'type', 'amount_rupees', 'balance_after_rupees', 'occurred_at')
    list_filter = ('zone_id', 'type')
    ordering = ('-occurred_at',)

    def has_add_permission(self, request):
        # Insert-only ledger, written by the billing/spending services.
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'zone_id', 'zone_name', 'tick_number', 'kwh', 'cost_rupees', 'recorded_at')
    list_filter = ('zone_id',)
    ordering = ('-tick_number',)

    def has_add_permission(self, request):
        # Insert-only history, written by the billing ledger.
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BillingDailyRollup)
class BillingDailyRollupAdmin(admin.ModelAdmin):
    list_display = ('id', 'zone_id', 'simulated_day', 'total_kwh', 'total_cost_rupees', 'sample_count')
    list_filter = ('zone_id',)
    ordering = ('-simulated_day',)

    def has_add_permission(self, request):
        # Written only by the rollup job's INSERT...SELECT.
        return False

    def has_change_permission(self, request, obj=None):
        return False
