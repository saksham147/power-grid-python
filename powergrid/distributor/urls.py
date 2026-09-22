from django.urls import path

from .api import views

urlpatterns = [
    path('status/', views.status, name='distributor-status'),
    path('zones/', views.zones, name='distributor-zones'),
    path('zones/<str:zone_id>/', views.zone_detail, name='distributor-zone-detail'),
]
