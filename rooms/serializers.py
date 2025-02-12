from rest_framework import serializers
from core.models import HotelRoom
from django.contrib.auth import get_user_model

User= get_user_model()

class HotelRoomSerializer(serializers.ModelSerializer):

    status = serializers.BooleanField(required=True) #Explicitly calling out status, if there might be
    # a need to modify it.

    class Meta:
        model = HotelRoom
        fields = ['id', 'room_number', 'room_type', 'price', 'status']
        read_only_fields = ['id']
        ref_name = 'RoomsHotelRoomSerializer'
