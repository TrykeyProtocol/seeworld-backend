from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from geopy.distance import geodesic

from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError

from core import * #import the global variables from conf


class User(AbstractUser):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=255, unique=True)
    avatar = models.ImageField(upload_to='avatars/', default='default_avatars/default_avatar.png', blank=True, null=True)

    bank_name = models.CharField(max_length=20, blank=True, null=True)
    bank_code = models.IntegerField(blank=True, null=True)
    bank_currency = models.CharField(max_length=20, blank=True, null=True, default='NGN')
    bank_account_number = models.CharField(max_length=10, blank=True, null=True)
    bank_account_name = models.CharField(max_length=30, blank=True, null=True)

    def save(self, *args, **kwargs):
        self.username = self.email
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class Transaction(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=3, default='NGN')
    description = models.TextField(null=True, blank=True)

    asset = models.ForeignKey('Asset', to_field='asset_number', related_name='transactions', on_delete=models.CASCADE, null=True)
    sub_asset_number = models.CharField(max_length=10, null=True)

    transaction_ref = models.CharField(max_length=255, unique=True)
    processor_ref = models.CharField(max_length=255, null=True, blank=True)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES)
    payment_type = models.CharField(max_length=100, choices=[('card','Card'), ('transfer', 'Transfer'),('mobile_money', 'Mobile_money')])

    is_outgoing = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)

    timestamp = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment {self.id} of {self.currency}{self.amount} by {self.name}"

    class Meta:
        indexes = [
            models.Index(fields=['transaction_ref']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['timestamp']),
        ]


class PaystackTransferRecipient(models.Model):
    # ForeignKey to the User model (many transfer recipients to one user)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='paystack_transfer_recipients')

    # Recipient details from Paystack
    recipient_code = models.CharField(max_length=63, unique=True)  # Unique ID from Paystack
    bank_account_number = models.CharField(max_length=15)  # Bank account number
    bank_code = models.CharField(max_length=15)  # Code of the recipient's bank
    bank_name = models.CharField(max_length=32)
    bank_account_name = models.CharField(max_length=127)  # The name of the bank account holder
    currency = models.CharField(max_length=4, default='NGN')  # Default to Nigerian Naira (NGN)

    # Optional fields for tracking creation and modification time
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.bank_account_name} - {self.bank_account_number}"

    class Meta:
        verbose_name = 'Transfer Recipient'
        verbose_name_plural = 'Transfer Recipients'
        unique_together = ['bank_account_number', 'bank_code']  # Ensure combination of account and bank is unique


class Asset(models.Model):
    asset_number = models.CharField(max_length=255, unique=True, editable=False)
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES)
    asset_name = models.CharField(max_length=100)
    location = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    total_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    details = models.JSONField()
    account_number = models.CharField(max_length=10)
    bank = models.CharField(max_length=20)

    def save(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        if not self.asset_number and user:
            user_id = str(user.id).zfill(4)
            
            # Get the last asset where the user's role is admin
            last_admin_asset = Asset.objects.filter(
                roles__user=user, 
                roles__role='admin'
            ).order_by('-asset_number').first()

            if last_admin_asset:
                # Extract the last three digits and increment
                last_count = int(last_admin_asset.asset_number[-3:])
                asset_count = last_count + 1
            else:
                # If no previous admin assets, start with 1
                asset_count = 1

            self.asset_number = f"TAS-{user_id}-{str(asset_count).zfill(3)}"
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.asset_number}: {self.asset_name}"


class AssetEvent(models.Model):
    asset = models.ForeignKey(Asset, to_field='asset_number', on_delete=models.CASCADE, null=True) # Retain events even if asset is deleted
    event_type = models.CharField(max_length=50, choices=EVENT_TYPE_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    data = models.CharField(max_length=255)

    # Generic Foreign Key fields
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=10)
    sub_asset = GenericForeignKey('content_type', 'object_id')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.event_type} for {self.asset.asset_name if self.asset else 'Unknown Asset'} at {self.timestamp}"


class Role(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='roles')
    asset = models.ForeignKey(Asset, to_field='asset_number', on_delete=models.CASCADE, related_name='roles')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('user', 'asset')

    def __str__(self):
        return f"{self.user} is a {self.role} of {self.asset}"


class HotelRoom(models.Model):
    hotel = models.ForeignKey(Asset, to_field='asset_number', on_delete=models.CASCADE, related_name='rooms', limit_choices_to={'asset_type': 'hotel'})
    room_number = models.CharField(max_length=10)
    room_type = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.BooleanField(default=False)
    activation_timestamp = models.DateTimeField(blank=True, null=True)
    expiry_timestamp = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ['hotel', 'room_number']

    def __str__(self):
        return f"{self.room_number} - {self.room_type} in {self.hotel.asset_name}"

    def clean(self):
        if self.price <= 0:
            raise ValidationError('Price must be greater than 0')

    def save(self, *args, **kwargs):
        self.clean()  # Call the clean method before saving
        super().save(*args, **kwargs)

class Vehicle(models.Model):
    fleet = models.ForeignKey(Asset, to_field='asset_number', on_delete=models.CASCADE, related_name='fleet', limit_choices_to={'asset_type': 'vehicle'})
    last_latitude = models.FloatField(null=True, default=0)
    last_longitude = models.FloatField(null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    total_distance = models.FloatField(default=0.0)  # in kilometers
    vehicle_number = models.CharField(max_length=10)
    brand = models.CharField(max_length=255)
    vehicle_type = models.CharField(max_length=255)
    status = models.BooleanField(default=False)
    activation_timestamp = models.DateTimeField(blank=True, null=True)
    expiry_timestamp = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ['fleet', 'vehicle_number']

    def __str__(self):
        return f"{self.vehicle_number} - {self.brand} {self.vehicle_type} in {self.fleet.asset_name}"

    def update_location(self, latitude, longitude):
        new_location = (latitude, longitude)
        if self.last_latitude is not None and self.last_longitude is not None:
            last_location = (self.last_latitude, self.last_longitude)
            distance = geodesic(last_location, new_location).kilometers
            self.total_distance += distance
        self.last_latitude = latitude
        self.last_longitude = longitude
        self.save()

    def get_location(self):
        if self.last_latitude is not None and self.last_longitude is not None:
            return {
                'latitude': self.last_latitude,
                'longitude': self.last_longitude
            }
        return None