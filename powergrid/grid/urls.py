from django.urls import path

from .api import views

urlpatterns = [
    path('status/', views.status, name='grid-status'),
    path('frequency-deviation/', views.frequency_deviation, name='grid-frequency-deviation'),
]
