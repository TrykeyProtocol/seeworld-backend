from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
# from rest_framework_simplejwt.token_blacklist.views import BlacklistView


# Get All Tables
router = DefaultRouter()

urlpatterns = [
    path('', include(router.urls)),
    path('auth/register/', RegisterView.as_view(), name='register'),
    # path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/me/', ProfileView.as_view(), name='profile'),
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('auth/reset-password/', ResetPasswordView.as_view(), name='reset-password'),
    path("auth/send-email-verification/", SendEmailVerificationView.as_view(), name="send-email-verification"),
    path('auth/verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('user-data/', UserDataView.as_view(), name='user-data'),
    path('token/', TokenObtainPairView.as_view(permission_classes=[AllowAny]), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    
    ]
