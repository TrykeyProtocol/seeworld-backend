from rest_framework import generics
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from core.models import HotelRoom, Asset, Role
from .serializers import HotelRoomSerializer

class HotelRoomListCreateView(generics.ListCreateAPIView):
    serializer_class = HotelRoomSerializer

    def get_queryset(self):
        hotel_id = self.kwargs['hotel_id']
        # Only allow rooms from the hotel the user has access to
        return HotelRoom.objects.filter(hotel__id=hotel_id, hotel__roles__user=self.request.user)

    def perform_create(self, serializer):
        hotel_id = self.kwargs['hotel_id']
        hotel = get_object_or_404(Asset, id=hotel_id, asset_type='hotel')
        # Check if the user is an admin
        role = Role.objects.filter(user=self.request.user, asset=hotel, role='admin').exists()
        if not role:
            return Response({"error": "You are not authorized to create rooms for this hotel."}, status=403)
        serializer.save(hotel=hotel)

class HotelRoomRetrieveUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = HotelRoomSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return HotelRoom.objects.none()
        # Make sure only admins can update/delete rooms
        room_id = self.kwargs['pk']
        room = get_object_or_404(HotelRoom, id=room_id)
        hotel = room.hotel
        role = Role.objects.filter(user=self.request.user, asset=hotel, role='admin').exists()
        if self.request.method in ['PUT', 'PATCH', 'DELETE'] and not role: #The patch method works to update just a parameter
            return Response({"error": "You are not authorized to modify rooms for this hotel."}, status=403)
        return HotelRoom.objects.filter(id=room_id)
