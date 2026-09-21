from django.urls import path

from .api import views

urlpatterns = [
    path('zones/', views.zones, name='customer-zones'),
    path('zones/<str:zone_id>/', views.zone_detail, name='customer-zone-detail'),
    path('units/', views.units, name='customer-units'),
    path('units/<str:unit_id>/', views.unit_detail, name='customer-unit-detail'),
    path('demand/', views.demand, name='customer-demand'),
]
