from django.urls import path

from .api import views

urlpatterns = [
    path('wallets/', views.wallets, name='billing-wallets'),
    path('zones/<str:zone_id>/wallet/', views.zone_wallet, name='billing-zone-wallet'),
    path('zones/<str:zone_id>/history/', views.zone_history, name='billing-zone-history'),
    path('zones/<str:zone_id>/transactions/', views.zone_transactions, name='billing-zone-transactions'),
    path('plants/purchase/', views.purchase_plant, name='billing-plants-purchase'),
    path('plants/upgrade/', views.upgrade_plant, name='billing-plants-upgrade'),
    path('plants/decommission/', views.decommission_plant, name='billing-plants-decommission'),
    path('storage/purchase/', views.purchase_storage, name='billing-storage-purchase'),
    path('unlocks/', views.unlocks, name='billing-unlocks'),
    path('summary/', views.summary, name='billing-summary'),
]
