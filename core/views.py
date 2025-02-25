import json
import logging
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError
from django.db.models import Q, F
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.datetime_safe import datetime

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter

from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from utils.helpers import *  
from core import *  

from .models import (
    User,
    Asset,
    HotelRoom,
    Vehicle,
    Transaction,
    UserToken,
)

from utils.serializers import UserSerializer
from utils.permissions import IsAdmin, IsManager


logger = logging.getLogger()
logger.setLevel(logging.INFO)

User = get_user_model()

# ---------- AUTH VIEWS ----------

class RegisterView(APIView):
    authentication_classes = []
    permission_classes = []
    
    def post(self, request, *args, **kwargs):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
                logger.info(f"User created successfully: {user.email}")
                return Response({
                    'message': 'User created successfully.',
                    'user': UserSerializer(user).data
                }, status=status.HTTP_201_CREATED)
            except IntegrityError as e:
                return Response({'error': f'A user with this email already exists. {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return self.handle_error(e, "Error during user registration")
        else:
            logger.error(f"Serializer validation failed: {serializer.errors}")
            return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class ForgotPasswordView(APIView):
    """
    Handles password reset requests by generating a 6-digit token and emailing it to the user.
    """
    permission_classes = [AllowAny]
    def post(self, request):
        email = request.data.get("email")
        user = get_object_or_404(User, email=email)

        if not user.can_request_reset():
            return Response({"error": "Too many requests. Try again later."}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Delete any existing reset tokens for the user
        UserToken.objects.filter(user=user, token_type="password_reset").delete()

        token = UserToken.objects.create(user=user, token_type="password_reset")
        user.last_password_reset_request = timezone.now()
        user.save()

        # NOTE: send_mail is supposed to be the django function, but due to google smtp constraints I will reimplement a function that uses sendgrid instead
        send_user_email(
            user.email,
            "Password Reset Code",
            f"Your password reset code is: {token.token}",
            FROM_EMAIL,
        )

        return Response({"message": "A reset code has been sent to your email."}, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    """
    Verifies the token and allows the user to reset their password.
    """
    permission_classes = [AllowAny]
    def post(self, request):
        email, token, new_password = request.data.get("email"), request.data.get("token"), request.data.get("new_password")
        user = get_object_or_404(User, email=email)

        # Fetch the reset token
        reset_token = UserToken.objects.filter(user=user, token=token, token_type="password_reset").first()

        if not reset_token or reset_token.expires_at < timezone.now():
            return Response({"error": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)

        # Update user password
        user.password = make_password(new_password)
        user.save()

        # Delete the token after successful reset
        reset_token.delete()

        return Response({"message": "Password reset successful."}, status=status.HTTP_200_OK)

class SendEmailVerificationView(APIView):
    """
    Sends an email verification token to the user.
    """
    permission_classes = [IsAuthenticated]
    def post(self, request):
        email = request.data.get("email")
        user = get_object_or_404(User, email=email)

        # Prevent spamming by deleting existing email verification tokens
        UserToken.objects.filter(user=user, token_type="email_verification").delete()

        # Generate a new email verification token
        token = UserToken.objects.create(user=user, token_type="email_verification")

        # Send verification email
        send_user_email(
            user.email,
            "Email Verification Code",
            f"Your email verification code is: {token.token}",
            FROM_EMAIL,
        )

        return Response({"message": "A verification code has been sent to your email."}, status=status.HTTP_200_OK)


class VerifyEmailView(APIView):
    """
    Verifies a user's email address using a 6-digit token.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    def post(self, request):
        email, token = request.data.get("email"), request.data.get("token")
        user = get_object_or_404(User, email=email)

        # Fetch the verification token
        email_token = UserToken.objects.filter(user=user, token=token, token_type="email_verification").first()

        if not email_token or email_token.expires_at < timezone.now():
            return Response({"error": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)

        # Mark the user as verified
        user.is_email_verified = True
        user.save()

        # Delete the token after successful verification
        email_token.delete()

        return Response({"message": "Email verification successful."}, status=status.HTTP_200_OK)

# ---------- USER VIEWS ----------
class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Profile updated successfully.'})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserDataView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdmin]  
    def get(self, request, *args, **kwargs):
        try:
            users = User.objects.all()
            data = []

            for user in users:
                user_data = self.get_user_data(user)
                data.append(user_data)

            pretty_data = json.dumps(data, indent=4, cls=CustomJSONEncoder)
            return HttpResponse(pretty_data, content_type="application/json")
        except Exception as e:
            return self.handle_error(e, "Error fetching user data")

    def get_user_data(self, user):
        user_data = {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "avatar": user.avatar.url if user.avatar else None,
            "assets": {"hotel": [], "logistics": [], "machinery": []},
            "payments": []
        }

        # Get and append user's assets
        self.add_user_assets(user, user_data)
        # Get and append user's payments
        self.add_user_payments(user, user_data)
        
        return user_data

    def add_user_assets(self, user, user_data):
        assets = Asset.objects.filter(roles__user_id=user)
        for asset in assets:
            asset_data = {
                "asset_id": str(asset.id),
                "asset_name": asset.asset_name,
                "created_at": asset.created_at.isoformat(),
                "location": asset.location,
                "details": asset.details,
            }
            if asset.asset_type == 'hotel':
                asset_data["rooms"] = self.get_asset_rooms(asset)
                user_data["assets"]["hotel"].append(asset_data)
            elif asset.asset_type == 'vehicle':
                asset_data["vehicles"] = self.get_asset_vehicles(asset)
                user_data["assets"]["logistics"].append(asset_data)

    def get_asset_rooms(self, asset):
        rooms = HotelRoom.objects.filter(hotel=asset)
        return [{
            "id": room.id,
            "room_number": room.room_number,
            "room_type": room.room_type,
            "price": room.price,
            "status": "active" if room.status else "inactive"
        } for room in rooms]

    def get_asset_vehicles(self, asset):
        vehicles = Vehicle.objects.filter(fleet=asset)
        return [{
            "id": vehicle.id,
            "vehicle_number": vehicle.vehicle_number,
            "type": vehicle.vehicle_type,
            "brand": vehicle.brand,
            "status": "active" if vehicle.status else "inactive"
        } for vehicle in vehicles]

    def add_user_payments(self, user, user_data):
        assets = Asset.objects.filter(roles__user_id=user)
        payments = Transaction.objects.filter(asset_id__in=assets)
        for payment in payments:
            payment_data = {
                "id": payment.id,
                "asset_id": str(payment.asset_id.id),
                "sub_asset_id": payment.sub_asset_id,
                "amount": payment.amount,
                "status": payment.payment_status,
                "timestamp": payment.timestamp.isoformat(),
                "payment_type": payment.payment_type
            }
            user_data["payments"].append(payment_data)
