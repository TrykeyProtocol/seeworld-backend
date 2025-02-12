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
    # path('api/logout/', LogoutView.as_view(), name='logout'),
    path('auth/me/', ProfileView.as_view(), name='profile'),
    path('user-data/', UserDataView.as_view(), name='user-data'),
    path('token/', TokenObtainPairView.as_view(permission_classes=[AllowAny]), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('payment/init/', InitiatePaymentView.as_view(), name='initiate_payment'),
    path('payment/verify/', VerifyPaymentView.as_view(), name='verify_payment'),
    path('transactions/', TransactionListView.as_view(), name='transaction_list'),
    path('transactions/<int:transaction_id>/', TransactionListView.as_view(), name='transaction_detail'),
    path('payment/transfer/init/', InitiateTransferView.as_view(), name='initiate_transfer'),
    path('paystack/webhook/', PaystackWebhookView.as_view(), name='webhook'),
    path('paystack/transfer-confirmation/', PaystackTransferConfirmationView.as_view(), name='transfer_confirmation'),
    ]
