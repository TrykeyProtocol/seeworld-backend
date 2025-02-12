from rest_framework import generics
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from core.models import Vehicle, Asset, Role, AssetEvent
from .serializers import VehicleSerializer
from django.contrib.contenttypes.models import ContentType

class VehicleListCreateView(generics.ListCreateAPIView):
    serializer_class = VehicleSerializer

    def get_queryset(self):
        # Only return vehicles owned by the logged-in user
        return Vehicle.objects.filter(fleet__roles__user=self.request.user)

    def perform_create(self, serializer):
        fleet_id = self.request.data.get('fleet')  # Get the fleet ID from the request, 
        # Fleet ID is the ID of the asset when it is a vehicle asset
        fleet = get_object_or_404(Asset, id=fleet_id, asset_type='vehicle')

        # Check if the user is an admin of this fleet
        role = Role.objects.filter(user=self.request.user, asset=fleet, role='admin').exists()
        if not role:
            return Response({"error": "You are not authorized to add vehicles to this fleet."}, status=403)
        
        serializer.save(fleet=fleet)

class VehicleRetrieveUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = VehicleSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Vehicle.objects.none()
        # Ensure the user has permission to view/update/delete the vehicle
        vehicle_id = self.kwargs['pk']
        vehicle = get_object_or_404(Vehicle, id=vehicle_id)
        fleet = vehicle.fleet
        role = Role.objects.filter(user=self.request.user, asset=fleet).exists()
        if self.request.method in ['PUT', 'DELETE']:
            # Only allow admins to update or delete vehicles
            is_admin = Role.objects.filter(user=self.request.user, asset=fleet, role='admin').exists()
            if not is_admin:
                return Response({"error": "You are not authorized to modify this vehicle."}, status=403)
        return Vehicle.objects.filter(id=vehicle_id)


class VehicleStatusView(generics.RetrieveAPIView):
    # Endpoint to retrieve vehicle status
    serializer_class = VehicleSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Vehicle.objects.none()
        return Vehicle.objects.all()

    def get(self, request, *args, **kwargs):   
        vehicle_id = self.kwargs['pk']
        
        # Fetch the vehicle and ensure the user has access
        vehicle = get_object_or_404(Vehicle, id=vehicle_id)
        fleet = vehicle.fleet

        # Check if the user has any role associated with the vehicle's fleet
        has_access = Role.objects.filter(user=request.user, asset=fleet).exists()
        if not has_access:
            return Response({"error": "You are not authorized to view the status of this vehicle."}, status=403)

        # Fetch the latest AssetEvents for this vehicle (e.g., location, passenger count, ignition)
        vehicle_content_type = ContentType.objects.get_for_model(Vehicle)
        events = AssetEvent.objects.filter(
            content_type=vehicle_content_type, object_id=vehicle.id
        ).order_by('-timestamp')

        # Organize the events by event_type (e.g., latest location, passenger count, etc.)
        event_data = {}
        for event_type in ['location', 'passenger_count', 'ignition']:
            latest_event = events.filter(event_type=event_type).first()
            if latest_event:
                event_data[event_type] = latest_event.data

        # Prepare the vehicle status response
        status_data = {
            'vehicle_number': vehicle.vehicle_number,
            'status': vehicle.status,
            'events': event_data  # Include the event data (location, passenger count, ignition, etc.)
        }

        return Response(status_data)