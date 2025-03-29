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
from django.db.models import Count, Case, When, Value, IntegerField, Sum, Avg, F, ExpressionWrapper, FloatField
from rest_framework.decorators import action
from django.db.models import Prefetch
from datetime import datetime, timedelta
from django.db.models.functions import ExtractHour, ExtractWeekDay, ExtractMonth

from .serializers import AssetSerializer, AssociateUserSerializer, HotelRoomSerializer, VehicleSerializer, DisassociateUserSerializer, AssetUserSerializer, TransactionHistorySerializer
from core.models import Asset, Role, User, HotelRoom, Vehicle, Transaction
from utils.permissions import IsAdmin, IsManager
from assets import ROLE_CHOICES
from utils.helpers import get_vehicle_movement_status
from django.conf import settings


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


class SubAssetInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Returns all vehicles grouped by their fleet, for fleets where the user has admin or manager role.
        Includes movement status from WhatsGPS API.
        """
        try:
            # Get all assets where user is admin or manager
            user_assets = Asset.objects.filter(
                roles__user=request.user,
                roles__role__in=['admin', 'manager'],
                asset_type='vehicle'
            ).prefetch_related(
                Prefetch(
                    'fleet',
                    queryset=Vehicle.objects.all().order_by('vehicle_number')
                )
            )

            # Get WhatsGPS token from settings
            whatsgps_token = getattr(settings, 'WHATSGPS_TOKEN', None)
            if not whatsgps_token:
                logger.error("WhatsGPS token not configured")
                return Response(
                    {"error": "WhatsGPS integration not configured"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Structure the response
            response_data = {}
            for asset in user_assets:
                vehicles = asset.fleet.all()
                response_data[asset.asset_number] = {
                    "fleet_name": asset.asset_name,
                    "vehicles": []
                }

                for vehicle in vehicles:
                    # Get movement status from WhatsGPS
                    movement_status = get_vehicle_movement_status(
                        car_id=vehicle.whatsgps_id,  # Assuming you have this field in your Vehicle model
                        token=whatsgps_token
                    )

                    vehicle_data = {
                        "vehicle_number": vehicle.vehicle_number,
                        "brand": vehicle.brand,
                        "vehicle_type": vehicle.vehicle_type,
                        "status": vehicle.status,
                        "last_latitude": vehicle.last_latitude,
                        "last_longitude": vehicle.last_longitude,
                        "total_distance": vehicle.total_distance,
                        "activation_timestamp": vehicle.activation_timestamp,
                        "expiry_timestamp": vehicle.expiry_timestamp,
                        "movement_status": movement_status
                    }
                    response_data[asset.asset_number]["vehicles"].append(vehicle_data)

            return Response(response_data)

        except Exception as e:
            logger.error(f"Error fetching sub-asset info: {str(e)}", exc_info=True)
            return Response(
                {"error": "Failed to fetch sub-asset information"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VehicleYieldView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Returns yield calculations for vehicles based on transactions.
        Can be called concurrently with SubAssetInfoView.
        """
        try:
            # Get date range from query parameters or default to all time
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            vehicle_numbers = request.query_params.getlist('vehicle_numbers[]')

            # Get all assets where user is admin or manager
            user_assets = Asset.objects.filter(
                roles__user=request.user,
                roles__role__in=['admin', 'manager'],
                asset_type='vehicle'
            )

            # Build the base query for transactions
            transactions_query = Transaction.objects.filter(
                asset__in=user_assets,
                payment_status='successful',
                is_outgoing=False
            )

            # Apply vehicle number filter if provided
            if vehicle_numbers:
                transactions_query = transactions_query.filter(sub_asset_number__in=vehicle_numbers)

            # Apply date filters if provided
            if start_date:
                transactions_query = transactions_query.filter(timestamp__gte=start_date)
            if end_date:
                transactions_query = transactions_query.filter(timestamp__lte=end_date)

            # Get all transactions in one query
            transactions = transactions_query.values(
                'asset__asset_number',
                'sub_asset_number',
                'amount'
            )

            # Calculate yields using a single pass through transactions
            yield_data = {}
            for transaction in transactions:
                asset_number = transaction['asset__asset_number']
                vehicle_number = transaction['sub_asset_number']
                
                if asset_number not in yield_data:
                    yield_data[asset_number] = {}
                
                if vehicle_number not in yield_data[asset_number]:
                    yield_data[asset_number][vehicle_number] = 0.0
                
                yield_data[asset_number][vehicle_number] += float(transaction['amount'])

            return Response({
                "yields": yield_data,
                "currency": "NGN",
                "period_start": start_date,
                "period_end": end_date
            })

        except Exception as e:
            logger.error(f"Error calculating vehicle yields: {str(e)}", exc_info=True)
            return Response(
                {"error": "Failed to calculate vehicle yields"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ExpectedYieldView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Calculates expected yield for vehicles based on historical data and predictive factors.
        """
        try:
            # Get parameters from request
            vehicle_number = request.query_params.get('vehicle_number')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            
            # Convert dates to datetime objects
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
            end_date = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Get the vehicle and its fleet
            vehicle = get_object_or_404(Vehicle, vehicle_number=vehicle_number)
            fleet = vehicle.fleet
            
            # Check user permissions
            if not Role.objects.filter(
                user=request.user,
                asset=fleet,
                role__in=['admin', 'manager']
            ).exists():
                return Response(
                    {"error": "You do not have permission to view this vehicle's data."},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Get historical data for the last 90 days
            historical_start = start_date - timedelta(days=90)
            historical_transactions = Transaction.objects.filter(
                asset=fleet,
                sub_asset_number=vehicle_number,
                payment_status='successful',
                timestamp__gte=historical_start,
                timestamp__lt=start_date
            )

            # Calculate historical metrics
            historical_metrics = historical_transactions.aggregate(
                avg_amount=Avg('amount'),
                total_distance=Sum('total_distance'),
                total_transactions=Count('id'),
                avg_daily_revenue=Avg(
                    ExpressionWrapper(
                        F('amount') / F('total_distance'),
                        output_field=FloatField()
                    )
                )
            )

            # Calculate daily utilization rate
            total_days = (end_date - start_date).days
            expected_utilization_rate = 0.8  # Default 80% utilization
            
            # Calculate expected daily revenue
            expected_daily_revenue = (
                historical_metrics['avg_daily_revenue'] or 0.0
            ) * expected_utilization_rate

            # Calculate seasonal adjustments
            month = start_date.month
            seasonal_factor = self._get_seasonal_factor(month)

            # Calculate special event impacts
            special_events_factor = self._get_special_events_factor(
                start_date, end_date, vehicle.location
            )

            # Calculate maintenance impact
            maintenance_factor = self._calculate_maintenance_factor(
                total_days, vehicle.maintenance_days
            )

            # Calculate total expected yield
            total_days = (end_date - start_date).days
            expected_yield = (
                expected_daily_revenue * 
                total_days * 
                seasonal_factor * 
                special_events_factor * 
                maintenance_factor
            )

            # Calculate costs
            costs = self._calculate_expected_costs(
                vehicle, 
                total_days, 
                expected_daily_revenue,
                historical_metrics
            )

            # Calculate net expected yield
            net_expected_yield = expected_yield - costs

            return Response({
                "vehicle_number": vehicle_number,
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "total_days": total_days
                },
                "historical_metrics": {
                    "avg_amount": float(historical_metrics['avg_amount'] or 0),
                    "total_distance": float(historical_metrics['total_distance'] or 0),
                    "total_transactions": historical_metrics['total_transactions'],
                    "avg_daily_revenue": float(historical_metrics['avg_daily_revenue'] or 0)
                },
                "expected_yield": {
                    "gross": float(expected_yield),
                    "net": float(net_expected_yield),
                    "daily_average": float(expected_daily_revenue),
                    "utilization_rate": expected_utilization_rate
                },
                "factors": {
                    "seasonal": seasonal_factor,
                    "special_events": special_events_factor,
                    "maintenance": maintenance_factor
                },
                "costs": costs
            })

        except Exception as e:
            logger.error(f"Error calculating expected yield: {str(e)}", exc_info=True)
            return Response(
                {"error": "Failed to calculate expected yield"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_seasonal_factor(self, month):
        """Calculate seasonal adjustment factor based on month"""
        # Example seasonal factors (can be adjusted based on historical data)
        seasonal_factors = {
            1: 1.2,  # January (high season)
            2: 1.1,  # February
            3: 1.0,  # March
            4: 0.9,  # April
            5: 0.8,  # May
            6: 0.7,  # June
            7: 0.7,  # July
            8: 0.8,  # August
            9: 0.9,  # September
            10: 1.0, # October
            11: 1.1, # November
            12: 1.2  # December (high season)
        }
        return seasonal_factors.get(month, 1.0)

    def _get_special_events_factor(self, start_date, end_date, location):
        """Calculate impact of special events in the area"""
        # This would typically query a database of events
        # For now, returning a default value
        return 1.0

    def _calculate_maintenance_factor(self, total_days, maintenance_days):
        """Calculate impact of maintenance days on yield"""
        if total_days <= 0:
            return 0.0
        return (total_days - maintenance_days) / total_days

    def _calculate_expected_costs(self, vehicle, total_days, expected_daily_revenue, historical_metrics):
        """Calculate expected costs for the period"""
        # Fuel costs (example: 15% of revenue)
        fuel_cost = expected_daily_revenue * total_days * 0.15

        # Maintenance costs (example: 10% of revenue)
        maintenance_cost = expected_daily_revenue * total_days * 0.10

        # Insurance costs (example: fixed daily rate)
        insurance_cost = 1000 * total_days  # Assuming 1000 NGN per day

        # Other operational costs (example: 5% of revenue)
        other_costs = expected_daily_revenue * total_days * 0.05

        return {
            "fuel": float(fuel_cost),
            "maintenance": float(maintenance_cost),
            "insurance": float(insurance_cost),
            "other": float(other_costs),
            "total": float(fuel_cost + maintenance_cost + insurance_cost + other_costs)
        }

class VehicleStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Returns all vehicles with their WhatsGPS movement status, grouped by fleet.
        This is a separate endpoint from SubAssetInfoView that includes real-time movement status.
        """
        try:
            # Get all assets where user is admin or manager
            user_assets = Asset.objects.filter(
                roles__user=request.user,
                roles__role__in=['admin', 'manager'],
                asset_type='vehicle'
            ).prefetch_related(
                Prefetch(
                    'fleet',
                    queryset=Vehicle.objects.all().order_by('vehicle_number')
                )
            )

            # Get WhatsGPS token from settings
            whatsgps_token = getattr(settings, 'WHATSGPS_TOKEN', None)
            if not whatsgps_token:
                logger.error("WhatsGPS token not configured")
                return Response(
                    {"error": "WhatsGPS integration not configured"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Structure the response
            response_data = {}
            for asset in user_assets:
                vehicles = asset.fleet.all()
                response_data[asset.asset_number] = {
                    "fleet_name": asset.asset_name,
                    "vehicles": []
                }

                for vehicle in vehicles:
                    # Get movement status from WhatsGPS
                    movement_status = get_vehicle_movement_status(
                        car_id=vehicle.whatsgps_id,
                        token=whatsgps_token
                    )

                    vehicle_data = {
                        "vehicle_number": vehicle.vehicle_number,
                        "brand": vehicle.brand,
                        "vehicle_type": vehicle.vehicle_type,
                        "status": vehicle.status,
                        "last_latitude": vehicle.last_latitude,
                        "last_longitude": vehicle.last_longitude,
                        "total_distance": vehicle.total_distance,
                        "activation_timestamp": vehicle.activation_timestamp,
                        "expiry_timestamp": vehicle.expiry_timestamp,
                        "whatsgps_id": vehicle.whatsgps_id,
                        "movement_status": movement_status
                    }
                    response_data[asset.asset_number]["vehicles"].append(vehicle_data)

            return Response(response_data)

        except Exception as e:
            logger.error(f"Error fetching vehicle status: {str(e)}", exc_info=True)
            return Response(
                {"error": "Failed to fetch vehicle status information"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )