from django.urls import path
from .views import *

urlpatterns = [
    path('payment/init/', InitiatePaymentView.as_view(), name='initiate_payment'),
    path('payment/verify/', VerifyPaymentView.as_view(), name='verify_payment'),
    path('transactions/', TransactionListView.as_view(), name='transaction_list'),
    path('transactions/<int:transaction_id>/', TransactionListView.as_view(), name='transaction_detail'),
    path('payment/transfer/init/', InitiateTransferView.as_view(), name='initiate_transfer'),
    path('paystack/webhook/', PaystackWebhookView.as_view(), name='webhook'),
    path('paystack/transfer-confirmation/', PaystackTransferConfirmationView.as_view(), name='transfer_confirmation'),
]