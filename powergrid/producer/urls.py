from django.urls import path

from .api import views

urlpatterns = [
    path('status/', views.status, name='producer-status'),
    path('plants/', views.plants, name='producer-plants'),
    path('plants/<int:plant_id>/', views.plant_detail, name='producer-plant-detail'),
    path('plants/<int:plant_id>/active/', views.plant_active, name='producer-plant-active'),
    path('plants/<int:plant_id>/history/', views.plant_history, name='producer-plant-history'),
]
