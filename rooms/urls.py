from django.urls import path
from . import views

urlpatterns = [
    path('hotels/<int:hotel_id>/rooms/', views.HotelRoomListCreateView.as_view(), name='hotel-room-list-create'),
    path('hotels/rooms/<int:pk>/', views.HotelRoomRetrieveUpdateDeleteView.as_view(), name='hotel-room-detail'),
]
