from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from core.models import HotelRoom, Vehicle, Role, Transaction, AssetEvent, Asset
from django.db.models import Count

User = get_user_model()

class TransactionHistorySerializer(serializers.ModelSerializer):
    date_time = serializers.DateTimeField(source='timestamp', format="%Y-%m-%d %H:%M:%S")

    class Meta:
        model = Transaction
        fields = ['name', 'amount', 'sub_asset_number', 'payment_status', 'date_time']
        

class AssetSerializer(serializers.ModelSerializer):
    user_role = serializers.SerializerMethodField()
    sub_asset_count = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = ['asset_number', 'asset_type', 'asset_name', 'location', 'created_at', 'total_revenue', 'details', 'account_number', 'bank', 'user_role', 'sub_asset_count']
        read_only_fields = ['asset_number', 'created_at', 'total_revenue', 'user_role', 'sub_asset_count']

    def get_user_role(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            role = Role.objects.filter(user=request.user, asset=obj).first()
            return role.role if role else None
        return None

    def get_sub_asset_count(self, obj):
        if obj.asset_type == 'hotel':
            return obj.rooms.count()
        elif obj.asset_type == 'vehicle':
            return obj.fleet.count()
        return 0

    def create(self, validated_data):
        user = validated_data.pop('user', None)
        asset = Asset(**validated_data)
        asset.save(user=user)
        return asset

    def update(self, instance, validated_data):
        user = validated_data.pop('user', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save(user=user)
        return instance


class AssetUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    role_association_timestamp = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['full_name', 'username', 'last_login', 'role', 'role_association_timestamp']

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or obj.username

    def get_role(self, obj):
        asset_number = self.context.get('asset_number')
        role = obj.roles.filter(asset__asset_number=asset_number).first()
        return role.role if role else None

    def get_role_association_timestamp(self, obj):
        asset_number = self.context.get('asset_number')
        role = obj.roles.filter(asset__asset_number=asset_number).first()
        return role.created_at if role else None


class AssociateUserSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    role = serializers.ChoiceField(choices=['admin', 'manager', 'viewer'])


class DisassociateUserSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class HotelRoomSerializer(serializers.ModelSerializer):
    occupancy = serializers.SerializerMethodField()

    class Meta:
        model = HotelRoom
        ref_name='AssetHotelRoomSerializer'
        fields = ['id', 'room_number', 'room_type', 'price', 'status', 'hotel', 'occupancy']
        read_only_fields = ['id', 'hotel']

    def get_occupancy(self, obj):
        hotel_room_content_type = ContentType.objects.get_for_model(HotelRoom)
        last_event = AssetEvent.objects.filter(
            content_type=hotel_room_content_type,
            object_id=obj.room_number,
            event_type='occupancy'
        ).order_by('-timestamp').first()

        if last_event:
            return last_event.data
        return 0  # Or any default value you prefer


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ['id', 'vehicle_number', 'brand', 'vehicle_type', 'status', 'fleet']
        read_only_fields = ['id', 'fleet']
        ref_name = 'AssetVehicleSerializer'
        extra_kwargs = {
            'vehicle_number': {'required': True}
        }
