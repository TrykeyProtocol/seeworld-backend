from rest_framework import serializers
from core.models import Vehicle

class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ['id', 'fleet', 'brand', 'vehicle_type', 'vehicle_number', 'status']
        read_only_fields = ['id']
        ref_name = 'VehiclesVehicleSerializer'

