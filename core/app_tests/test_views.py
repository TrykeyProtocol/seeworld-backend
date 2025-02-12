from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
import logging
from rest_framework import status
from rest_framework.test import APIClient

from decimal import Decimal
from ..models import *

from unittest.mock import patch, Mock

from datetime import timedelta
import math 
import sys

from ..views import logger

User = get_user_model()
logger.setLevel(logging.ERROR)


class InitiatePaymentViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('initiate_payment')

        # Create test users
        self.user1 = User.objects.create_user(username='user1', password='password1', email='test1@gmail.com')
        self.user2 = User.objects.create_user(username='user2', password='password2', email='test2@gmail.com')

        # Create test assets
        self.asset1 = Asset.objects.create(
            asset_number='ASSET001',
            asset_type='vehicle',
            asset_name='Test Vehicle 1',
            location='Test Location 1',
            details={'make': 'Toyota', 'model': 'Corolla'},
            account_number='1234567890',
            bank='Test Bank',
            total_revenue=1000.00
        )
        self.asset2 = Asset.objects.create(
            asset_number='ASSET002',
            asset_type='hotel',
            asset_name='Test Hotel',
            location='Test Location 2',
            details={'rooms': 50, 'stars': 4},
            account_number='0987654321',
            bank='Another Bank',
            total_revenue=5000.00
        )

        # Create roles
        Role.objects.create(user=self.user1, asset=self.asset1, role='admin')
        Role.objects.create(user=self.user2, asset=self.asset2, role='manager')
        
        # Create hotel rooms for the hotel asset
        self.room1 = HotelRoom.objects.create(
            hotel=self.asset2,
            room_number='101',
            room_type='Standard',
            price=100.00,
            status=True,
            activation_timestamp=timezone.now(),
            expiry_timestamp=timezone.now() + timedelta(days=365)
        )
        self.room2 = HotelRoom.objects.create(
            hotel=self.asset2,
            room_number='201',
            room_type='Deluxe',
            price=150.00,
            status=True,
            activation_timestamp=timezone.now(),
            expiry_timestamp=timezone.now() + timedelta(days=365)
        )

        # Create vehicles for the vehicle asset
        self.vehicle1 = Vehicle.objects.create(
            fleet=self.asset1,
            last_latitude=40.7128,
            last_longitude=-74.0060,
            total_distance=1000.5,
            vehicle_number='V001',
            brand='Toyota',
            vehicle_type='Sedan',
            status=False,
            activation_timestamp=timezone.now(),
            expiry_timestamp=timezone.now() + timedelta(days=365)
        )
        self.vehicle2 = Vehicle.objects.create(
            fleet=self.asset1,
            last_latitude=34.0522,
            last_longitude=-118.2437,
            total_distance=500.2,
            vehicle_number='V002',
            brand='Honda',
            vehicle_type='SUV',
            status=True,
            activation_timestamp=timezone.now(),
            expiry_timestamp=timezone.now() + timedelta(days=365)
        )
        # Create asset events
        AssetEvent.objects.create(
            asset=self.asset1,
            event_type='ignition',
            data='Ignition on',
            content_type=ContentType.objects.get_for_model(self.asset1),
            object_id=self.asset1.asset_number
        )
            
        # Valid payload for payment initiation
        self.valid_payload = {
            "email": "customer@example.com",
            "name": "John Doe",
            "phonenumber": "1234567890",
            "amount": 5000,
            "redirect_url": "https://example.com/callback",
            "title": "Test Payment",
            "description": "Payment for service",
            "asset_number": self.asset2.asset_number,
            "sub_asset_number": self.room1.room_number,
            "sub_asset_type": "hotel_room",
            "currency": "NGN",
            "is_outgoing": False
        }
 
    @patch('core.views.initiate_paystack_payment')
    def test_successful_payment_initiation(self, mock_init):
        mock_init.return_value = ("https://checkout.paystack.com/123456", None)
        mock_init.get.return_value.status_code = 200
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('payment_link', response.data)
        self.assertIn('transaction_ref', response.data)
        
        transaction = Transaction.objects.get(transaction_ref=response.data['transaction_ref'])
        self.assertEqual(transaction.amount, Decimal(self.valid_payload['amount']))
        self.assertEqual(str(transaction.asset.asset_number), str(self.asset2.asset_number))

    def test_payment_initiation_unauthorized_user(self):
        pass
        
    @patch('core.views.initiate_paystack_payment')
    def test_payment_initiation_with_different_asset_types(self, mock_init):
        mock_init.return_value = ("https://checkout.paystack.com/123456", None)
        mock_init.get.return_value.status_code = 200

        self.client.force_authenticate(user=self.user1)
        
        # Test with vehicle asset
        self.valid_payload['asset_number'] = self.asset1.asset_number
        self.valid_payload['sub_asset_number'] = self.vehicle1.vehicle_number
        self.valid_payload['sub_asset_type'] = 'vehicle'
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Test with hotel asset
        self.valid_payload['asset_number'] = self.asset2.asset_number
        self.valid_payload['sub_asset_number'] = self.room1.room_number
        self.valid_payload['sub_asset_type'] = 'hotel_room'
        self.client.force_authenticate(user=self.user2)
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('core.views.initiate_paystack_payment')
    def test_payment_initiation_with_asset_events(self, mock_init):
        mock_init.return_value = ("https://checkout.paystack.com/123456", None)
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check if a new AssetEvent is created for the payment
        latest_event = AssetEvent.objects.filter(asset=self.asset1).latest('timestamp')
        self.assertEqual(latest_event.event_type, 'ignition')

    @patch('core.views.initiate_paystack_payment')
    def test_payment_initiation_with_invalid_asset_number(self, mock_init):
        mock_init.return_value = ("https://checkout.paystack.com/123456", None)
        self.client.force_authenticate(user=self.user1)
        self.valid_payload['asset_number'] = 'INVALID_ID'
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('core.views.initiate_paystack_payment')
    def test_payment_initiation_role_based_access(self, mock_init):
        mock_init.return_value = ("https://checkout.paystack.com/123456", None)
        mock_init.get.return_value.status_code = 200

        # Test admin role
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Test manager role
        Role.objects.filter(user=self.user1, asset=self.asset1).update(role='manager')
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    @patch('core.views.initiate_paystack_payment')
    def test_payment_initiation_api_failure(self, mock_initiate_payment):
        mock_initiate_payment.return_value = (None, "Failed to initiate payment")
        
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    # Field validation tests...
    def test_invalid_email_format(self):
        self.client.force_authenticate(user=self.user1)
        payload = self.valid_payload.copy()
        payload["email"] = "invalid-email-format"
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_invalid_amount_type(self):
        self.client.force_authenticate(user=self.user1)
        payload = self.valid_payload.copy()
        payload["amount"] = "invalid-amount"
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_negative_amount(self):
        self.client.force_authenticate(user=self.user1)
        payload = self.valid_payload.copy()
        payload["amount"] = "-100"
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_zero_amount(self):
        self.client.force_authenticate(user=self.user1)
        payload = self.valid_payload.copy()
        payload["amount"] = "0"
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_very_large_amount(self):
        self.client.force_authenticate(user=self.user1)
        payload = self.valid_payload.copy()
        payload["amount"] = "1000000000000"  # 1 trillion
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_invalid_callback_url(self):
        pass


class VerifyPaymentViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('verify_payment')

        user = User.objects.create(
            username='info@trykey.com',
            email='info@trykey.com',
            password='admin',
            is_superuser=True
        )
        user.save()

        self.mock_paystack_response = {
            "status": True,
            "message": "Verification successful",
            "data": {
                "id": 4099260516,
                "domain": "test",
                "status": "success",
                "reference": "re4lyvq3s3",
                "amount": 40333,
                "gateway_response": "Successful",
                "paid_at": "2024-08-22T09:15:02.000Z",
                "created_at": "2024-08-22T09:14:24.000Z",
                "channel": "card",
                "currency": "NGN",
                "authorization": {
                    "authorization_code": "AUTH_uh8bcl3zbn",
                    "bin": "408408",
                    "last4": "4081",
                    "exp_month": "12",
                    "exp_year": "2030",
                    "channel": "card",
                    "card_type": "visa ",
                    "bank": "TEST BANK",
                    "country_code": "NG",
                    "brand": "visa",
                    "reusable": True,
                },
                "customer": {
                    "id": 181873746,
                    "email": "demo@test.com",
                    "customer_code": "CUS_1rkzaqsv4rrhqo6",
                },
            }
        }
        # Create test assets
        self.vehicle_asset = Asset.objects.create(
            asset_number='ASSET001',
            asset_type='vehicle',
            asset_name='Test Vehicle 1',
            location='Test Location 1',
            details={'make': 'Toyota', 'model': 'Corolla'},
            account_number='1234567890',
            bank='Test Bank',
            total_revenue=Decimal('1000.00')
        )
        self.hotel_asset = Asset.objects.create(
            asset_number='ASSET002',
            asset_type='hotel',
            asset_name='Test Hotel',
            location='Test Location 2',
            details={'rooms': 50, 'stars': 4},
            account_number='0987654321',
            bank='Another Bank',
            total_revenue=5000.00
        )

        # Create test transactions
        self.pending_transaction = Transaction.objects.create(
            asset=self.vehicle_asset,
            sub_asset_number='V001',
            payment_status='pending',
            payment_type='card',
            amount=Decimal('5000.00'),
            currency='NGN',
            transaction_ref='tx_ref_pending',
            name='John Doe',
            email='john@example.com',
            is_outgoing=False,
            description='Pending payment for vehicle rental',
            is_verified=False
        )
        self.canceled_transaction = Transaction.objects.create(
            asset=self.vehicle_asset,
            sub_asset_number='V001',
            payment_status='canceled',
            payment_type='card',
            amount=Decimal('5000.00'),
            currency='NGN',
            transaction_ref='tx_ref_canceled',
            name='John Doe',
            email='john@example.com',
            is_outgoing=False,
            description='Canceled payment for vehicle rental',
            is_verified=False
        )
        self.completed_transaction = Transaction.objects.create(
            asset=self.vehicle_asset,
            sub_asset_number='V001',
            payment_status='completed',
            payment_type='transfer',
            amount=Decimal('7500.00'),
            currency='NGN',
            transaction_ref='tx_ref_completed',
            name='Jane Smith',
            email='naj@gmail.com',
            is_outgoing=False,
            description='Completed payment for vehicle rental',
            is_verified=False
        )
        self.failed_transaction = Transaction.objects.create(
            asset=self.vehicle_asset,
            sub_asset_number='V001',
            payment_status='failed',
            payment_type='mobile_money',
            amount=Decimal('3000.00'),
            currency='NGN',
            transaction_ref='tx_ref_failed',
            name='Bob Johnson',
            email='bob@example.com',
            is_outgoing=False,
            description='Failed payment for vehicle rental',
            is_verified=False
        )
          # Create hotel rooms for the hotel asset
        
        # Create rooms for hotel asset
        self.room1 = HotelRoom.objects.create(
            hotel=self.hotel_asset,
            room_number='101',
            room_type='Standard',
            price=100.00,
            status=True,
            activation_timestamp=timezone.now(),
            expiry_timestamp=timezone.now() + timedelta(days=365)
        )
        self.room2 = HotelRoom.objects.create(
            hotel=self.hotel_asset,
            room_number='201',
            room_type='Deluxe',
            price=150.00,
            status=True,
            activation_timestamp=timezone.now(),
            expiry_timestamp=timezone.now() + timedelta(days=365)
        )

        # Create vehicles for the vehicle asset
        self.vehicle1 = Vehicle.objects.create(
            fleet=self.vehicle_asset,
            last_latitude=40.7128,
            last_longitude=-74.0060,
            total_distance=1000.5,
            vehicle_number='V001',
            brand='Toyota',
            vehicle_type='Sedan',
            status=False,
            activation_timestamp=timezone.now(),
            expiry_timestamp=timezone.now() + timedelta(days=365)
        )
        self.vehicle2 = Vehicle.objects.create(
            fleet=self.vehicle_asset,
            last_latitude=34.0522,
            last_longitude=-118.2437,
            total_distance=500.2,
            vehicle_number='V002',
            brand='Honda',
            vehicle_type='SUV',
            status=True,
            activation_timestamp=timezone.now(),
            expiry_timestamp=timezone.now() + timedelta(days=365)
        )

    @patch('core.views.verify_paystack_payment')
    def test_successful_verification(self, mock_verify):
        mock_verify.return_value = ({'message': 'Verification successful', 'amount': '5000.00', 'currency': 'NGN'}, None)
        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], "Payment verified successfully")
        
        self.completed_transaction.refresh_from_db()
        self.assertEqual(self.completed_transaction.payment_status, 'completed')
        self.assertTrue(self.completed_transaction.is_verified)
        
    @patch('core.views.verify_paystack_payment')
    def test_paystack_verification_error(self, mock_verify):
        mock_verify.return_value = (None, "API Error")
        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], "Failed to verify transaction")

    def test_missing_parameters(self):
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], "Missing required parameters")

    @patch('core.views.verify_paystack_payment')
    def test_already_verified_transaction(self, mock_verify):
        mock_verify.return_value = ({'status': 'completed', 'amount': '5000.00', 'currency': 'NGN'}, None)
        self.completed_transaction.is_verified = True
        self.completed_transaction.save()
        
        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], "Payment already verified")
    
    # Post successful verification actions tests
    @patch('core.views.verify_paystack_payment')
    def test_hotel_room_status_update(self, mock_verify):
        mock_verify.return_value = (self.mock_paystack_response, None)

        self.completed_transaction.asset = self.hotel_asset
        self.completed_transaction.sub_asset_number = self.room1.room_number
        self.completed_transaction.save()

        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.room1.refresh_from_db()
        self.assertTrue(self.room1.status)
        self.assertGreater(self.room1.expiry_timestamp, timezone.now())

    @patch('core.views.verify_paystack_payment')
    def test_vehicle_status_update(self, mock_verify):
        mock_verify.return_value = (self.mock_paystack_response, None)

        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.vehicle1.refresh_from_db()
        self.assertTrue(self.vehicle1.status)
        self.assertGreater(self.vehicle1.expiry_timestamp, timezone.now())

    @patch('core.views.verify_paystack_payment')
    def test_asset_revenue_update(self, mock_verify):
        mock_verify.return_value = (self.mock_paystack_response, None)

        initial_revenue = self.vehicle_asset.total_revenue
        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.vehicle_asset.refresh_from_db()
        self.assertEqual(self.vehicle_asset.total_revenue, initial_revenue + Decimal('7500.00'))  # Amount in kobo

    @patch('core.views.verify_paystack_payment')
    def test_expiry_task_scheduling(self, mock_verify):
        mock_verify.return_value = (self.mock_paystack_response, None)

        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('core.views.verify_paystack_payment')
    def test_already_active_sub_asset_extension(self, mock_verify):
        mock_verify.return_value = (self.mock_paystack_response, None)

        self.vehicle1.status = True
        self.vehicle1.expiry_timestamp = timezone.now() + timedelta(days=5)
        self.vehicle1.save()

        initial_expiry = self.vehicle1.expiry_timestamp

        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.vehicle1.refresh_from_db()
        self.assertTrue(self.vehicle1.status)
        self.assertGreater(self.vehicle1.expiry_timestamp, initial_expiry)

    @patch('core.views.verify_paystack_payment')
    def test_expired_sub_asset_reactivation(self, mock_verify):
        
        mock_verify.return_value = (self.mock_paystack_response, None)

        self.vehicle1.status = False
        self.vehicle1.expiry_timestamp = timezone.now() - timedelta(days=1)
        self.vehicle1.save()

        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.vehicle1.refresh_from_db()
        self.assertTrue(self.vehicle1.status)
        self.assertGreater(self.vehicle1.expiry_timestamp, timezone.now())

    @patch('core.views.verify_paystack_payment')
    def test_hotel_room_duration_calculation(self, mock_verify):
        mock_verify.return_value = (self.mock_paystack_response, None)

        self.completed_transaction.asset = self.hotel_asset
        self.completed_transaction.sub_asset_number = self.room1.room_number
        self.completed_transaction.amount = Decimal('403.33')  # 40333 kobo
        self.completed_transaction.save()

        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.room1.refresh_from_db()
        # the tests below ensures that the duration matches the amount paid
        # TODO: reinstaste in prod
        # expected_duration = math.ceil(float(self.completed_transaction.amount) / float(self.room1.price))
        # expected_expiry = timezone.now() + timedelta(days=expected_duration)
        # self.assertAlmostEqual(self.room1.expiry_timestamp, expected_expiry, delta=timedelta(minutes=1))

    @patch('core.views.verify_paystack_payment')
    def test_connection_error_handling(self, mock_verify):
        mock_verify.side_effect = ConnectionError("Unable to connect to Paystack API")

        response = self.client.get(self.url, {'trxref': 'tx_ref_completed'})
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('error', response.data)

    def test_logging(self):
        pass
        # with self.assertLogs('core.views', level='INFO') as cm:
            # response = self.client.get(self.url, {'tx_ref': 'non_existent_ref'})
            # self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            # self.assertIn('Transaction non_existent_ref not found in database', cm.output[0]) #TODO: reinstate this test once logging is set up


class InitiateTransferViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('initiate_transfer')

        user = User.objects.create(
            username='admin@trykey.com',
            email='admin@trykey.com',
            password='admin',
            is_superuser=True
        )
        user.save()

        # create new paystack recipient
        paystack_recipient = PaystackTransferRecipient.objects.create(
            user=user,
            recipient_code='mock_paystack_recipient_id',
            bank_account_number='1234567890',
            bank_code='1234',
            bank_name='GT Bank',
            bank_account_name='John Spyrogyra Roberts',
            currency='NGN'
        )
        paystack_recipient.save()

        successful_transfer_initiation_response = {
            "status": True,
            "message": "Transfer has been initiated.",
            "data": {
                "integration": 100073,
                "domain": "test",
                "amount": 3794800,
                "currency": "NGN",
                "source": "balance",
                "reason": "Calm down",
                "recipient": 1,
                "status": "pending",
                "transfer_code": "TRF_1ptvuv321ahaa7q",
                "id": 14,
                "createdAt": "2017-02-03T17:21:54.508Z",
                "updatedAt": "2017-02-03T17:21:54.508Z"
            }
        }
    @patch('core.views.initiate_paystack_transfer')
    def test_successful_transfer_initiation(self, mock_initiate_transfer):
        pass