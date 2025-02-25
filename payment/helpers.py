import requests
from django.conf import settings
from rest_framework import status
import random
import string
import logging
from decimal import Decimal
from typing import Dict, Union, Tuple
from django.conf import settings
from requests.exceptions import RequestException
from http import HTTPStatus

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def initiate_flutterwave_payment(payment_data):
    payment_url = "https://api.flutterwave.com/v3/payments"
    headers = {
        "Authorization": f"Bearer {settings.FLW_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(payment_url, json=payment_data, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        payment_link = response_data.get('data', {}).get('link')
        return payment_link, None
    except requests.RequestException as e:
        return None, f"Failed to initiate payment: {str(e)}"
    
def verify_flutterwave_transaction(transaction_id):
    url = f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.FLW_SECRET_KEY}"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)  # Increased timeout
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.Timeout:
        return None, "Connection timed out"
    except requests.exceptions.RequestException as e:
        return None, f"Connection error: {str(e)}"
    except ValueError:  # Includes JSONDecodeError
        return None, "Invalid response from Flutterwave"
    
def initiate_paystack_payment(payment_data):
    payment_url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    try:
        payment_data['amount'] = str(100 * float(payment_data['amount']))
        response = requests.post(payment_url, json=payment_data, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        payment_link = response_data.get('data', {}).get('authorization_url')
        return payment_link, None
    except ValueError as e:
        return None, f"Failed to convert amount to appropriate format: {str(e)}"
    except requests.RequestException as e:
        return None, f"Failed to initiate payment: {str(e)}"
    


def verify_paystack_payment(transaction_ref):
    url = f"https://api.paystack.co/transaction/verify/{transaction_ref}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)  # Increased timeout
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.Timeout:
        return None, "Connection timed out"
    except requests.exceptions.RequestException as e:
        return None, f"Connection error: {str(e)}"
    except ValueError:  # Includes JSONDecodeError
        return None, "Invalid response from Flutterwave"




def initiate_paystack_transfer(amount, recipient, reference, reason = None):
    """
    Initiates a transfer using the Paystack API with comprehensive error handling and logging.

    Args:
        amount (float): Amount to transfer in smallest currency unit (kobo for NGN)
        recipient (str): Paystack recipient code
        reference (str):Transfer reference
        reason (str, optional): Reason for the transfer

    Returns:
        Tuple[bool, Dict, str]: Contains:
            - success (bool): Whether the request was successful
            - response_data (Dict): The processed response data or error details
            - message (str): A human-readable message describing the result

    Raises:
        None: All exceptions are caught and logged
    """
    url = "https://api.paystack.co/transfer"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    # Validate input parameters
    if not isinstance(amount, (int, float, Decimal)) or amount <= 0:
        error_msg = f"Invalid amount: {amount}. Amount must be a positive number."
        logger.error(error_msg)
        return False, {}, error_msg

    if not isinstance(recipient, str) or not recipient.strip():
        error_msg = "Invalid recipient code: Recipient code must be a non-empty string."
        logger.error(error_msg)
        return False, {}, error_msg

    data = {
        "source": "balance",
        "amount": float(amount * 100),  # Convert to kobo
        "recipient": recipient.strip(),
        "reference": reference,
        "reason": reason.strip() if reason else None
    }

    try:
        logger.info(f"Initiating Paystack transfer of {amount} to recipient {recipient}")
        response = requests.post(url, json=data, headers=headers, timeout=30)

        # Log the response status
        logger.info(f"Paystack API response status: {response.status_code}")

        # Handle different HTTP status codes
        if response.status_code == HTTPStatus.OK:  # 200
            response_data = response.json()

            # Verify the response structure
            if not isinstance(response_data, dict):
                error_msg = "Invalid response format from Paystack"
                logger.error(error_msg)
                return False, response_data, error_msg

            status = response_data.get('status', False)
            if status:
                transfer_data = response_data.get('data', {})
                transfer_code = transfer_data.get('transfer_code')
                logger.info(f"Transfer initiated successfully. Transfer code: {transfer_code}")
                return True, response_data, "Transfer initiated successfully"
            else:
                error_msg = response_data.get('message', 'Transfer initiation failed')
                logger.error(f"Paystack error: {error_msg}")
                return False, response_data, error_msg

        elif response.status_code == HTTPStatus.UNAUTHORIZED:  # 401
            error_msg = "Authentication failed. Please check your Paystack API key."
            logger.error(error_msg)
            return False, {"status_code": 401}, error_msg

        elif response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:  # 422
            error_msg = "Invalid transfer parameters or insufficient balance"
            logger.error(f"{error_msg}. Response: {response.text}")
            return False, response.json(), error_msg

        elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:  # 429
            error_msg = "Rate limit exceeded. Please try again later."
            logger.warning(error_msg)
            return False, {"status_code": 429}, error_msg

        else:
            error_msg = f"Unexpected response from Paystack. Status code: {response.status_code}"
            logger.error(f"{error_msg}. Response: {response.text}")
            return False, {"status_code": response.status_code}, error_msg

    except requests.exceptions.Timeout:
        error_msg = "Request timed out while connecting to Paystack"
        logger.error(error_msg)
        return False, {"error": "timeout"}, error_msg

    except requests.exceptions.ConnectionError:
        error_msg = "Failed to connect to Paystack API"
        logger.error(error_msg)
        return False, {"error": "connection_error"}, error_msg

    except ValueError as e:
        error_msg = f"Invalid JSON response from Paystack: {str(e)}"
        logger.error(error_msg)
        return False, {"error": "invalid_json"}, error_msg

    except Exception as e:
        error_msg = f"Unexpected error during transfer initiation: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, {"error": "unexpected_error"}, error_msg

def create_paystack_recipient(user, name, account_number, bank_code, currency='NGN', description=None):
    """
    Create a new Paystack transfer recipient and save it to the database.

    Args:
    user (User): The user creating this recipient
    name (str): The recipient's name according to their account registration
    account_number (str): The recipient's bank account number
    bank_code (str): The recipient's bank code
    currency (str, optional): Currency for the account. Defaults to 'NGN'
    description (str, optional): A description for this recipient

    Returns:
    tuple: (success (bool), recipient_data (json), message (str)
    """
    url = "https://api.paystack.co/transferrecipient"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "type": "nuban",
        "name": name,
        ""
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": currency
    }
    if description:
        data["description"] = description

    # Log the initiation of recipient creation
    logger.info(f"Creating Paystack recipient for user {user.username} with account {account_number}")

    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()  # Raises an error for non-2xx responses
        recipient_data = response.json()['data']

        # Log the successful API response
        logger.info(f"Paystack recipient created successfully for user {user}, Paystack response: {recipient_data}")

        return True, recipient_data, "Recipient created successfully"

    except requests.exceptions.RequestException as e:
        # Log the HTTP-related errors
        logger.error(f"HTTP error while creating recipient for user {user}: {str(e)}")
        return False, f"Error creating recipient: {str(e)}", None
    except KeyError as e:
        # Log the unexpected response format errors
        logger.error(f"KeyError in Paystack response for user {user}: {str(e)}")
        return False, f"Unexpected response format: {str(e)}", None
    except Exception as e:
        # Log any other unexpected errors
        logger.exception(f"Unexpected error occurred while creating recipient for user {user}: {str(e)}")
        return False, f"An unexpected error occurred: {str(e)}", None

def generate_transaction_reference():
    """
    Generates the transaction reference given a prefix
    """
    alphabet = string.digits + string.ascii_lowercase
    ref = ''.join(random.choice(alphabet) + ('-' if i in {8, 12, 16, 20} else '') for i in range(1, 33))
    return ref
