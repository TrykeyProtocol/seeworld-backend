from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AssetViewSet, AssociateUserView, VehicleViewSet, HotelRoomViewSet, DisassociateUserView, AssetUsersListView, TransactionHistoryView


router = DefaultRouter()
router.register(r'assets/(?P<asset_number>[^/.]+)/rooms', HotelRoomViewSet, basename='hotel-room')
router.register(r'assets/(?P<asset_number>[^/.]+)/vehicles', VehicleViewSet, basename='vehicle')
router.register('assets', AssetViewSet, basename='asset')


urlpatterns = [
    path('', include(router.urls)),
    path('assets/invite/<str:asset_number>/', AssociateUserView.as_view(), name='invite-user'),
    path('assets/kick/<str:asset_number>/', DisassociateUserView.as_view(), name='kick-user'),
    path('assets/<str:asset_number>/rooms/<str:room_number>/', HotelRoomViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='hotel-room-detail'),
    path('assets/<str:asset_number>/vehicles/<str:vehicle_number>/', VehicleViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='vehicle-detail'),
    path('assets/<str:asset_number>/users/', AssetUsersListView.as_view(), name='asset-users-list'),
    path('assets/<str:asset_number>/transactions/', TransactionHistoryView.as_view(), name='asset-transaction-history'),
]

urlpatterns += router.urls
