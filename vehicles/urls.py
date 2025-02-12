from django.urls import path
from .views import VehicleListCreateView, VehicleRetrieveUpdateDeleteView, VehicleStatusView

urlpatterns = [
    # Vehicle Management Endpoints
    path('vehicles/', VehicleListCreateView.as_view(), name='vehicle-list-create'),
    path('vehicles/<int:pk>/', VehicleRetrieveUpdateDeleteView.as_view(), name='vehicle-detail'),
    path('vehicles/<int:pk>/status/', VehicleStatusView.as_view(), name='vehicle-status'),
]
