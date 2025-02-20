import json
import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q, F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.datetime_safe import datetime

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.helpers import *
from utils.payment import *
from core import *

from .models import (
    User,
    Asset,
    HotelRoom,
    Transaction,
    Vehicle,
    PaystackTransferRecipient,
)

from utils.serializers import UserSerializer, TransactionSerializer
from utils.permissions import IsAdmin, IsManager


# ---------- PAYMENT VIEWS ----------

class InitiatePaymentView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        tx_ref = generate_transaction_reference()

        try:
            # Validate and retrieve fields
            customer_email = validate_field(request.data, "email", [str])
            customer_name = validate_field(request.data, "name", [str])
            customer_phonenumber = validate_field(request.data, "phonenumber", [str])
            amount = validate_field(request.data, "amount", [float, int])  # Allow int for amounts as well
            redirect_url = validate_field(request.data, "redirect_url", [str])
            title = validate_field(request.data, "title", [str])
            description = validate_field(request.data, "description", [str])
            asset_number = validate_field(request.data, "asset_number", [str])
            sub_asset_number = validate_field(request.data, "sub_asset_number", [str])
            sub_asset_type = validate_field(request.data, "sub_asset_type", [str], required=False)
            
            # Optional fields
            currency = validate_field(request.data, "currency", [str], required=False, default="NGN")
            is_outgoing = validate_field(request.data, "is_outgoing", [bool], required=False, default=False)

            # check if the asset and subasset exist
            asset = Asset.objects.filter(asset_number=asset_number).exists()
            if not asset:
                raise ValueError("Asset not found.")

            # Determine if we should filter by a specific sub-asset type
            if sub_asset_type:
                sub_asset = None
                if sub_asset_type == "vehicle":
                    sub_asset = Vehicle.objects.filter(vehicle_number=sub_asset_number).exists()
                elif sub_asset_type == "hotel_room":
                    sub_asset = HotelRoom.objects.filter(room_number=sub_asset_number).exists()
                
                if not sub_asset:
                    raise ValueError(f"{sub_asset_type.capitalize()} sub-asset not found.")
            else:
                # Check all sub-assets for the given asset number
                vehicle_sub_assets = Vehicle.objects.filter(vehicle_number=sub_asset_number).exists()
                hotel_room_sub_assets = HotelRoom.objects.filter(room_number=sub_asset_number).exists()

                if not vehicle_sub_assets and not hotel_room_sub_assets:
                    raise ValueError("No sub-assets found for the given sub-asset number.")

        except KeyError as e:
            return Response({"error": f"Missing required field: {e.args[0]}"}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        payment_data = {
            "email": customer_email,
            "amount": amount,
            "currency": currency,
            "callback_url": redirect_url,
            "reference": tx_ref
        }


        payment_link, error = initiate_paystack_payment(payment_data)

        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        if payment_link:
            try:
                with transaction.atomic(): #start a transaction to ensure that the database is consistent
                    asset = Asset.objects.get(asset_number=asset_number)
                    if not asset:
                        return Response({"error": f"Asset ({asset_number}) does not exist"}, status=status.HTTP_400_BAD_REQUEST)
                    transaction_obj = Transaction.objects.create(
                        asset=asset,
                        sub_asset_number=sub_asset_number,
                        payment_status='pending',
                        payment_type='card',  # TODO: confirm if card payment, adjust if needed
                        amount=amount,
                        currency=currency,
                        transaction_ref=tx_ref,
                        name=customer_name,
                        email=customer_email,
                        description=description,
                        is_outgoing=is_outgoing
                    )
                return Response({
                    "payment_link": payment_link,
                    "transaction_ref": tx_ref
                }, status=status.HTTP_200_OK)
            except Asset.DoesNotExist:
                return Response({"error": "Invalid asset number"}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({"error": f"Failed to create transaction: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({"error": "Payment link not found"}, status=status.HTTP_400_BAD_REQUEST)
        
class VerifyPaymentView(APIView):
    """
    TODO: restructure the post requests to allow execution without calling verify_paystack payment when the route is called from
     the paystack webhook
    """
    permission_classes = [AllowAny]
    def get(self, request):
        tx_ref = request.GET.get('trxref')
        if not tx_ref:
            return Response({"error": "Missing required parameters"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                db_transaction = Transaction.objects.select_for_update().get(transaction_ref=tx_ref)
                
                if db_transaction.is_verified: 
                    logger.info(f"Transaction {tx_ref} already verified")
                    return Response({"message": "Payment already verified"}, status=status.HTTP_200_OK)

                # Verify the transaction status with Paystack
                transaction_data, error = verify_paystack_payment(tx_ref)
                if error:
                    logger.error(f"Error verifying transaction: {error}")
                    return Response({"error": "Failed to verify transaction"}, status=status.HTTP_400_BAD_REQUEST)

                if not transaction_data:
                    logger.error("No transaction data received")
                    return Response({"error": "No transaction data received"}, status=status.HTTP_400_BAD_REQUEST)

                transaction_status =  "completed" if transaction_data['message'] == "Verification successful" else "failed"
                self.process_transaction(db_transaction, transaction_status)
                if transaction_status == 'completed':
                    return Response({"message": "Payment verified successfully"}, status=status.HTTP_200_OK)
                else:
                    return Response({"message": f"Payment status updated to {transaction_status}"}, status=status.HTTP_200_OK)

        except Transaction.DoesNotExist:
            logger.error(f"Transaction {tx_ref} not found in database")
            return Response({"error": "Transaction not found"}, status=status.HTTP_404_NOT_FOUND)
        except KeyError as e:
            logger.error(f"Error parsing api response: {e}")
            return Response({"error": "Merchant error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"Error processing transaction {tx_ref}: {str(e)}")
            return Response({"error": "Error processing payment"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def process_transaction(self, transaction, status_param):
        self.update_transaction(transaction, status_param)
        if status_param == 'completed' and not transaction.is_outgoing:
            self.update_asset_revenue(transaction)
            self.update_sub_asset(transaction)

        # Trigger async tasks
        # send_user_sms.delay() # NOTE: these are currently unimplemented

    def update_transaction(self, transaction, status_param):
        transaction.payment_status = status_param
        transaction.is_verified = True
        transaction.save()
        logger.info(f"Transaction {transaction.transaction_ref} updated successfully")

    def update_asset_revenue(self, transaction):
        Asset.objects.filter(asset_number=transaction.asset.asset_number).update(
            total_revenue=F('total_revenue') + transaction.amount
        )
        logger.info(f"Updated total revenue for asset {transaction.asset.asset_number}")

    def update_sub_asset(self, transaction):
        asset = transaction.asset
        sub_asset_number = transaction.sub_asset_number
        current_time = timezone.now()

        if asset.asset_type == 'hotel':
            room = HotelRoom.objects.get(hotel=asset, room_number=sub_asset_number)
            duration_days = math.ceil(float(transaction.amount) / float(room.price))

            if room.status and room.expiry_timestamp > current_time:
                # Room is already active, extend the expiry
                if settings.DEBUG is True:
                    new_expiry = room.expiry_timestamp + timedelta(minutes=duration_days)
                else:
                    new_expiry = room.expiry_timestamp + timedelta(days=duration_days)
            else:
                # Room is not active or has expired, set new activation and expiry
                room.activation_timestamp = current_time
                if settings.DEBUG is True:
                    new_expiry = current_time + timedelta(minutes=duration_days)
                else:
                    new_expiry = current_time + timedelta(days=duration_days)

            send_control_request.apply_async(args=[asset.asset_number, sub_asset_number, "access", "unlock"])
            room.status = True
            room.expiry_timestamp = new_expiry
            room.save()
            
            # Cancel any existing expiry task and schedule a new one
            schedule_sub_asset_expiry.apply_async(
                args=[asset.asset_number, sub_asset_number, "access", "lock", True],
                eta=new_expiry
            )
            
            logger.info(f"Updated HotelRoom {room.room_number} status and timestamps. New expiry: {new_expiry}")

        elif asset.asset_type == 'vehicle':
            vehicle = Vehicle.objects.get(fleet=asset, vehicle_number=sub_asset_number)
            duration_days = 1  # Assuming 1 day per payment, adjust as needed

            if vehicle.status and vehicle.expiry_timestamp > current_time:
                # Vehicle is already active, extend the expiry
                new_expiry = vehicle.expiry_timestamp + timedelta(days=duration_days)
            else:
                # Vehicle is not active or has expired, set new activation and expiry
                vehicle.activation_timestamp = current_time
                new_expiry = current_time + timedelta(days=duration_days)
            send_control_request.apply_async(args=[asset.asset_number, sub_asset_number, "ignition", "turn_on"], eta=datetime.now())
            vehicle.status = True
            vehicle.expiry_timestamp = new_expiry
            vehicle.save()
            # Cancel any existing expiry task and schedule a new one
            schedule_sub_asset_expiry.apply_async(
                args=[asset.asset_number, sub_asset_number, "ignition", "turn_off", True],
                eta=new_expiry
            )
            logger.info(f"Updated Vehicle {vehicle.vehicle_number} status and timestamps. New expiry: {new_expiry}")

        else:
            logger.warning(f"Unsupported asset type: {asset.asset_type}")

class TransactionListView(APIView):
    pagination_class = TransactionPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['payment_status', 'payment_type', 'currency', 'is_outgoing']
    ordering_fields = ['timestamp', 'amount']
    ordering = ['-timestamp']  # Default ordering

    def get_queryset(self):
        user = self.request.user
        
        if IsAdmin():
            queryset = Transaction.objects.all()
        elif IsManager():
            queryset = Transaction.objects.filter(asset__manager=user)
        else:
            # For non-admin, non-manager users, return an empty queryset or handle as needed
            queryset = Transaction.objects.none()

        search_query = self.request.query_params.get('search', None)
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(transaction_ref__icontains=search_query)
            )
        return queryset

    def get(self, request, transaction_id=None):
        if transaction_id:
            transaction = get_object_or_404(Transaction, id=transaction_id)
            if not IsAdmin() and (not IsManager() or transaction.asset.manager != request.user):
                return Response({"detail": "You do not have permission to view this transaction."}, status=status.HTTP_403_FORBIDDEN)
            serializer = TransactionSerializer(transaction)
            return Response(serializer.data, status=status.HTTP_200_OK)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = TransactionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = TransactionSerializer(queryset, many=True)
        return Response(serializer.data)

    def filter_queryset(self, queryset):
        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(self.request, queryset, self)
        return queryset

    @property
    def paginator(self):
        if not hasattr(self, '_paginator'):
            if self.pagination_class is None:
                self._paginator = None
            else:
                self._paginator = self.pagination_class()
        return self._paginator

    def paginate_queryset(self, queryset):
        if self.paginator is None:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data)

class InitiateTransferView(APIView):
    permission_classes = [] #TODO: this needs to be IsAuthenticated and IsAdmin. It is currently not working

    def post(self, request, *args, **kwargs):
        try:
            amount = float(request.data.get('amount'))
        except ValueError:
            logger.info("Invalid amount passed into InitiateTransferView")
            return Response({"detail": "Invalid amount passed into InitiateTransfer"}, status=status.HTTP_400_BAD_REQUEST)
        bank_account_number = request.data.get('bank_account_number')
        bank_code = request.data.get('bank_code')
        bank_account_name = request.data.get('bank_account_name')

        if not all([amount, bank_account_number, bank_code, bank_account_name]):
            logger.error(
                "Validation failed: missing required fields - Amount,  bank_account_number, bank_code, bank_account_name.")
            return Response({"error": "Amount,  bank_account_number, bank_code, bank_account_name"},
                            status=status.HTTP_400_BAD_REQUEST)
        if float(transfer_policy_config['min_amount']) > float(amount) or float(amount) > float(transfer_policy_config['max_amount']):
            min_amount = f"{transfer_policy_config['min_amount']:,.2f}"
            max_amount = f"{transfer_policy_config['max_amount']:,.2f}"

            logger.error(
                f"Invalid transfer amount: {amount}. Must be between ₦{min_amount} and ₦{max_amount}.")
            return Response({"error": f"Amount must be between ₦{min_amount} and ₦{max_amount}"},
                            status.HTTP_400_BAD_REQUEST)

        recipient_code =  self.get_paystack_recipient(bank_code, bank_account_number)
        if recipient_code is None:
            paystack_recipient_data = {
                "bank_account_name": bank_account_name,
                "account_number": bank_account_number,
                "bank_code": bank_code,
                "description": f"Paystack recipient for {User.username}",
            }

            logger.info(
                f"Paystack recipient does not exist. Creating recipient with bank number {bank_account_number} for bank code {bank_code}")

            # Call the method to create a new Paystack recipient
            response_data = self.create_new_paystack_recipient(paystack_recipient_data)
            if response_data is None:
                return Response({"error": "Could not create paystack recipient."}, status=status.HTTP_400_BAD_REQUEST)
            recipient_code = response_data['recipient_code']
            bank_name = response_data['details']['bank_name']
            bank_account_name = response_data['details']['account_name']
            paystack_recipient_local = PaystackTransferRecipient(
                user=self.request.user,
                recipient_code=recipient_code,
                bank_account_number=bank_account_number,
                bank_code=bank_code,
                bank_account_name=bank_account_name,
                bank_name=bank_name
            )
            paystack_recipient_local.save()
            logger.info(f"Paystack recipient created successfully: {recipient_code}")

        txn_reference = generate_transaction_reference()
        success, message, response_data = initiate_paystack_transfer(amount, recipient_code, txn_reference)

        if success:
            # Create a pending transaction in the database
            outgoing_transaction = self.create_pending_transaction(amount, recipient_code,txn_reference)
            outgoing_transaction.save()
            logger.info(f"Transaction object created successfully: {outgoing_transaction}")
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            # If transfer initiation failed, mark the transaction as failed
            logger.error(f"Failed to initiate paystack transfer: {message}")
            return Response(f"Failed to initiate paystack transfer: {message}", status=status.HTTP_400_BAD_REQUEST)

    def create_pending_transaction(self, amount, recipient, txn_reference):
        transaction = Transaction.objects.create(
            name=f"Withdrawal to recipient_code:{recipient}",
            amount=amount,
            description=None,
            asset=None,
            sub_asset_number=None,
            transaction_ref=txn_reference,
            payment_status='pending',
            payment_type='transfer',
            is_outgoing=True
        )
        return transaction


    def get_paystack_recipient(self, bank_code, bank_account_number):
        """
        Get the Paystack transfer recipient for the current user.
        Returns None if the recipient doesn't exist or doesn't belong to the current user.
        """
        recipient = PaystackTransferRecipient.objects.filter(
            bank_account_number=bank_account_number,
            bank_code=bank_code
        )
        return recipient.first().recipient_code if recipient.exists() else None

    def create_new_paystack_recipient(self, data):
        # check if recipient with given account number and bank exists already
        saved_paystack_recipient = PaystackTransferRecipient.objects.filter(
            user=self.request.user,
            bank_account_number=data['account_number'],
            bank_code=data['bank_code']
        )
        if saved_paystack_recipient.exists():
            logger.info(f"Paystack recipient already exists: {saved_paystack_recipient}")
            return {
                "recipient_code": saved_paystack_recipient.first().recipient_code,
                "bank_name": saved_paystack_recipient.first().bank_name,
                "account_name": saved_paystack_recipient.first().bank_account_name,
            }
        status, recipient_data, message = create_paystack_recipient(
            user=self.request.user,
            name= data['bank_account_name'],
            account_number=data['account_number'],
            bank_code=data['bank_code'],
            currency='NGN',
            description=data['description'],
        )

        if status:
            logger.info(f"PaystackTransferRecipient object created in the database for user {self.request.user.username}")
            return recipient_data
        else:
            logger.error(f"Could not create paystack recipient. Error: {message}")
            return None

class FinalizeTransferView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        pass

class PaystackTransferConfirmationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        """
        Handle Paystack transfer confirmation webhook.
        Validates that a pending transaction exists and is within the allowed confirmation window.

        Expected request data:
        {
            "trxref": "transaction_reference"
        }
        """
        try:
            trxref = request.data['data']['details']['body'].get('reference')
            amount = request.data['data']['details']['body'].get('amount')
            if not trxref or not amount:
                error_msg = "No transaction reference provided" if not trxref else "No amount provided"
                logger.critical(f"Transfer confirmation failed: {error_msg}. Transaction may not have come from paystack")
                return Response(
                    {"error": error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except KeyError:
            error_msg = "Invalid response package format"
            logger.error(error_msg)
            return Response(
                {"error": error_msg},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Get the transaction and check its status
            transaction = Transaction.objects.get(transaction_ref=trxref)

            # Calculate the expiry time for pending transactions
            expiry_time = timezone.now() - timedelta(
                seconds=transfer_policy_config['pending_transfer_expiry']
            )

            if int(transaction.amount)*100 != int(amount):
                logger.error(
                    f"Transfer confirmation failed: Amount {amount} is not  "
                    f"{transaction.amount}'"
                )
                return Response(status=status.HTTP_400_BAD_REQUEST)
            # Check if transaction is pending and within time window
            if (transaction.payment_status == 'pending' and
                    transaction.timestamp >= expiry_time):
                logger.info(
                    f"Valid pending transfer confirmation received for transaction: {trxref}"
                )
                return Response(status=status.HTTP_200_OK)

            # Log different failure cases
            if transaction.payment_status != 'pending':
                logger.error(
                    f"Transfer confirmation failed: Transaction {trxref} status is "
                    f"{transaction.payment_status}, expected 'pending'"
                )
            else:
                logger.error(
                    f"Transfer confirmation failed: Transaction {trxref} has expired. "
                    f"Created at {transaction.timestamp}, expiry time was {expiry_time}"
                )

            return Response(
                {"error": "Invalid or expired transaction"},
                status=status.HTTP_400_BAD_REQUEST
            )

        except Transaction.DoesNotExist:
            error_msg = f"Transaction with reference {trxref} not found"
            logger.error(f"Transfer confirmation failed: {error_msg}")
            return Response(
                {"error": error_msg},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            error_msg = f"Unexpected error processing transfer confirmation: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class PaystackWebhookView(APIView):
    """
    Webhook to handle events from Paystack such as transfer.success and transfer.failed.
    Implements comprehensive handling of transfer events with proper error handling,
    idempotency checks, and transaction management.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # Verify webhook signature
        if not self._verify_signature(request):
            return Response(
                {'error': 'Invalid signature'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            event_data = json.loads(request.body)
            event = event_data.get('event', '').split('.')

            if len(event) != 2:
                logger.error(f"Invalid event format received: {event_data.get('event')}")
                return Response(
                    {'error': 'Invalid event format'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            event_type, event_status = event[0], event[1]

            # Handle transfer events
            if event_type == 'transfer':
                return self._handle_transfer_event(event_status, event_data)

            # Log non-transfer events
            logger.info(f"Received non-transfer webhook: {event}")
            return Response({'status': 'success'}, status=status.HTTP_200_OK)

        except json.JSONDecodeError:
            logger.error("Failed to decode webhook payload", exc_info=True)
            return Response(
                {'error': 'Invalid payload'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected error processing webhook: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Internal server error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _verify_signature(self, request):
        """
        Verify that the webhook request came from Paystack.
        """
        paystack_signature = request.headers.get('x-paystack-signature')
        if not paystack_signature:
            logger.warning("Missing Paystack signature in webhook request")
            return False

        # Use a dedicated webhook secret instead of the general SECRET_KEY
        secret_key = settings.PAYSTACK_SECRET_KEY

        computed_signature = hmac_sha512(secret_key, request.body)
        return computed_signature == paystack_signature

    def _handle_transfer_event(self, event_status, event_data):
        """
        Handle different transfer event types with proper transaction management.
        """
        try:
            transfer_data = event_data.get('data', {})
            transfer_reference = transfer_data.get('reference')
            amount = transfer_data.get('amount')

            if not transfer_reference:
                logger.error("Missing required transfer data in webhook payload")
                return Response(
                    {'error': 'Missing required transfer data'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Handle the event within a transaction
            with transaction.atomic():
                # Select the transaction for update to prevent race conditions
                try:
                    txn = Transaction.objects.select_for_update().get(
                        transaction_ref=transfer_reference
                    )
                except Transaction.DoesNotExist:
                    logger.error(f"Transaction not found for reference: {transfer_reference}")
                    return Response(
                        {'error': 'Transaction not found'},
                        status=status.HTTP_404_NOT_FOUND
                    )

                # Handle different event statuses
                if event_status == 'success':
                    return self._handle_transfer_success(txn, transfer_data)
                elif event_status == 'failed':
                    return self._handle_transfer_failure(txn, transfer_data)
                elif event_status == 'reversed':
                    return self._handle_transfer_reversal(txn, transfer_data)
                else:
                    logger.warning(f"Unknown transfer status received: {event_status}")
                    return Response(
                        {'status': 'ignored'},
                        status=status.HTTP_200_OK
                    )

        except Exception as e:
            logger.error(
                f"Error processing transfer event: {str(e)}",
                exc_info=True
            )
            return Response(
                {'error': 'Internal server error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _handle_transfer_success(self, transaction, transfer_data):
        """
        Handle successful transfer events.
        """
        if transaction.payment_status == 'success':
            logger.info(f"Transfer already marked as successful: {transaction.transaction_ref}")
            return Response({'status': 'success'}, status=status.HTTP_200_OK)

        transaction.payment_status = 'success'
        transaction.completed_at = datetime.now()
        transaction.save()

        logger.info(f"Successfully processed transfer: {transaction.transaction_ref}")
        return Response({'status': 'success'}, status=status.HTTP_200_OK)

    def _handle_transfer_failure(self, transaction, transfer_data):
        """
        Handle failed transfer events.
        """
        transaction.payment_status = 'failed'
        transaction.failure_reason = transfer_data.get('reason', 'Unknown failure reason')
        transaction.metadata = {
            **transaction.metadata,
            'paystack_transfer_data': transfer_data
        }
        transaction.save()

        logger.error(
            f"Transfer failed for transaction {transaction.transaction_ref}: "
            f"{transaction.failure_reason}"
        )
        return Response({'status': 'success'}, status=status.HTTP_200_OK)

    def _handle_transfer_reversal(self, transaction, transfer_data):
        """
        Handle transfer reversal events.
        """
        transaction.payment_status = 'reversed'
        transaction.metadata = {
            **transaction.metadata,
            'paystack_transfer_data': transfer_data,
            'reversal_reason': transfer_data.get('reason', 'Unknown reversal reason')
        }
        transaction.save()

        logger.warning(
            f"Transfer reversed for transaction {transaction.transaction_ref}: "
            f"{transaction.metadata.get('reversal_reason')}"
        )
        return Response({'status': 'success'}, status=status.HTTP_200_OK)

    def get(self, request, *args, **kwargs):
        """
        Handle GET requests to the webhook endpoint.
        """
        return Response(
            {'error': 'Method not allowed'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )
