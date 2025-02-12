import logging

from django.core.cache import cache

from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.permissions import OR, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.viewsets import ModelViewSet
from rest_framework.views import APIView
from django.db.models import Count, Case, When, Value, IntegerField

from .serializers import AssetSerializer, AssociateUserSerializer, HotelRoomSerializer, VehicleSerializer, DisassociateUserSerializer, AssetUserSerializer, TransactionHistorySerializer
from core.models import Asset, Role, User, HotelRoom, Vehicle, Transaction
from core.permissions import IsAdmin, IsManager
from assets import ROLE_CHOICES


logger = logging.getLogger(__name__)


class AssetViewSet(ModelViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = AssetSerializer
    lookup_url_kwarg = 'asset_number'
    lookup_field = 'asset_number'

    def get_queryset(self):
        user = self.request.user
        logger.debug(f"Getting queryset for user: {user.id}")
        cache_key = f'user_assets_{user.id}'
        assets = cache.get(cache_key)
        if not assets:
            assets = Asset.objects.filter(roles__user=user).annotate(
                sub_asset_count=Count(
                    Case(
                        When(asset_type='hotel', then='rooms'),
                        When(asset_type='vehicle', then='fleet'),
                        default=Value(None),
                        output_field=IntegerField()
                    )
                )
            )
            cache.set(cache_key, assets, 60 * 5)  # Cache for 5 minutes
        
        logger.debug(f"Queryset count: {assets.count()}")
        return assets

    def get_object(self):
        queryset = self.get_queryset()
        asset_number = self.kwargs.get('asset_number')
        logger.debug(f"Getting object with asset_number: {asset_number}")
        asset = get_object_or_404(queryset, asset_number=asset_number)
        self.check_object_permissions(self.request, asset)
        return asset

    def check_object_permissions(self, request, asset):
        logger.debug(f"Checking object permissions for user {request.user.id} on asset {asset.asset_number}")
        super().check_object_permissions(request, asset)
        if self.action in ['update', 'partial_update', 'destroy']:
            is_admin = Role.objects.filter(user=request.user, asset__asset_number=asset.asset_number, role='admin').exists()
            logger.debug(f"User is admin: {is_admin}")
            if not is_admin:
                logger.debug("Permission denied: User is not admin for this asset")
                self.permission_denied(request, message="You do not have admin permissions for this asset.")
            else:
                logger.debug("User has admin permissions for this asset")

    def perform_create(self, serializer):
        asset = serializer.save(user=self.request.user)
        Role.objects.create(user=self.request.user, asset=asset, role='admin')
        cache.delete(f'user_assets_{self.request.user.id}')

    def perform_destroy(self, instance):
        logger.debug(f"Performing destroy on asset {instance.asset_number}")
        cache.delete(f'user_assets_{self.request.user.id}')
        instance.delete()
        logger.debug(f"Asset {instance.asset_number} deleted")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def destroy(self, request, *args, **kwargs):
        logger.debug(f"Destroy method called by user {request.user.id}")
        instance = self.get_object()
        logger.debug(f"Object to destroy: {instance.id}")
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)
        
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)
        cache.delete(f'user_assets_{self.request.user.id}')


class AssetUsersListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, asset_number):
        asset = get_object_or_404(Asset, asset_number=asset_number)
        users = User.objects.filter(roles__asset__asset_number=asset_number)
        serializer = AssetUserSerializer(users, many=True, context={'asset_number': asset_number})
        return Response(serializer.data)


def get_role_level(role):
    role_hierarchy = {'admin': 3, 'manager': 2, 'viewer': 1}
    return role_hierarchy.get(role, 0)


class AssociateUserView(APIView):
    permission_classes = [IsAuthenticated, (IsAdmin | IsManager)]

    def post(self, request, *args, **kwargs):
        asset_number = kwargs.get('asset_number')
        asset = get_object_or_404(Asset, asset_number=asset_number)

        # Get the role of the requesting user
        requester_role = Role.objects.filter(user=request.user, asset=asset).first()
        if not requester_role:
            return Response({'error': 'You are not associated with this asset.'}, status=status.HTTP_403_FORBIDDEN)

        requester_level = get_role_level(requester_role.role)

        serializer = AssociateUserSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            new_role = serializer.validated_data['role']

            # Check if the new role is at the same level or lower than the requester's role
            if get_role_level(new_role) > requester_level:
                return Response({'error': 'You cannot assign a role higher than your own.'}, status=status.HTTP_403_FORBIDDEN)

            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({'error': 'User with this email does not exist.'}, status=status.HTTP_404_NOT_FOUND)

            # Create or update the role association
            Role.objects.update_or_create(user=user, asset=asset, defaults={'role': new_role})

            return Response({'message': 'User associated with the asset successfully.'}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class DisassociateUserView(APIView):
    permission_classes = [IsAuthenticated, (IsAdmin | IsManager)]

    def post(self, request, *args, **kwargs):
        asset_number = kwargs.get('asset_number')
        asset = get_object_or_404(Asset, asset_number=asset_number)

        # Get the role of the requesting user
        requester_role = Role.objects.filter(user=request.user, asset=asset).first()
        if not requester_role:
            return Response({'error': 'You are not associated with this asset.'}, status=status.HTTP_403_FORBIDDEN)

        requester_level = get_role_level(requester_role.role)

        serializer = DisassociateUserSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']

            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({'error': 'User with this email does not exist.'}, status=status.HTTP_404_NOT_FOUND)

            role = Role.objects.filter(user=user, asset=asset).first()
            if role:
                # Check if the requester has permission to disassociate this user
                if get_role_level(role.role) >= requester_level and requester_role.role != 'admin':
                    return Response({'error': 'You do not have permission to disassociate this user.'}, status=status.HTTP_403_FORBIDDEN)

                if role.role == 'admin' and Role.objects.filter(asset=asset, role='admin').count() == 1:
                    return Response({'error': 'Cannot remove the last admin of the asset.'}, status=status.HTTP_400_BAD_REQUEST)
                
                role.delete()
                return Response({'message': 'User disassociated from the asset successfully.'}, status=status.HTTP_200_OK)
            else:
                return Response({'error': 'User is not associated with this asset.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class HotelRoomViewSet(ModelViewSet):
    serializer_class = HotelRoomSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'room_number'
    lookup_url_kwarg = 'room_number'

    def get_queryset(self):
        asset_number = self.kwargs.get('asset_number')
        asset = get_object_or_404(Asset, asset_number=asset_number)
        if asset.asset_type != 'hotel':
            raise NotFound("This asset is not a hotel.")
        return HotelRoom.objects.filter(hotel__asset_number=asset_number)

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated()]

    def check_permissions(self, request):
        super().check_permissions(request)
        asset_number = self.kwargs.get('asset_number')
        asset = get_object_or_404(Asset, asset_number=asset_number)
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            if not Role.objects.filter(user=request.user, asset__asset_number=asset_number, role='admin').exists():
                self.permission_denied(request, message="You do not have admin permissions for this asset.")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        asset_number = self.kwargs.get('asset_number')
        asset = get_object_or_404(Asset, asset_number=asset_number)
        if asset.asset_type != 'hotel':
            return Response({'error': 'This asset is not a hotel.'}, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(hotel=asset)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VehicleViewSet(ModelViewSet):
    serializer_class = VehicleSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'vehicle_number'
    lookup_url_kwarg = 'vehicle_number'

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        asset_number = self.kwargs.get('asset_number')
        asset = get_object_or_404(Asset, asset_number=asset_number)
        if asset.asset_type != 'vehicle':
            raise NotFound("This asset is not a vehicle fleet.")
        return Vehicle.objects.filter(fleet__asset_number=asset_number)

    def check_permissions(self, request):
        super().check_permissions(request)
        asset_number = self.kwargs.get('asset_number')
        asset = get_object_or_404(Asset, asset_number=asset_number)
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            if not Role.objects.filter(user=request.user, asset__asset_number=asset_number, role='admin').exists():
                raise PermissionDenied("You do not have admin permissions for this asset.")

    def create(self, request, *args, **kwargs):
        asset_number = self.kwargs.get('asset_number')
        asset = get_object_or_404(Asset, asset_number=asset_number)
        if asset.asset_type != 'vehicle':
            return Response({'error': 'This asset is not a vehicle fleet.'}, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(fleet=asset)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        asset_number = self.kwargs.get('asset_number')
        get_object_or_404(Asset, asset_number=asset_number)
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        asset_number = self.kwargs.get('asset_number')
        get_object_or_404(Asset, asset_number=asset_number)
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TransactionHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, asset_number):
        # Get the asset
        asset = get_object_or_404(Asset, asset_number=asset_number)

        # Check if the user has permission to view this asset's transactions
        if not request.user.roles.filter(asset=asset).exists():
            return Response({"error": "You do not have permission to view transactions for this asset."},
                            status=status.HTTP_403_FORBIDDEN)

        # Get all transactions for this asset
        transactions = Transaction.objects.filter(asset=asset).order_by('-timestamp')

        # Serialize the transactions
        serializer = TransactionHistorySerializer(transactions, many=True)

        return Response(serializer.data)