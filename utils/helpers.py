from decimal import Decimal
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from seeworld import settings
from google.cloud import translate_v2 as translate

import hmac
import hashlib
import requests
import os

from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response

from django.contrib.auth import get_user_model
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


def get_system_user_token():
    system_user = User.objects.get(username='info@trykey.com')
    refresh = RefreshToken.for_user(system_user)
    return str(refresh.access_token)


# ----------- Data helpers -------------
def get_cached_data(cache_key, queryset):
    data = cache.get(cache_key)
    if not data:
        data = list(queryset)
        cache.set(cache_key, data, timeout=60 * 15)  # Cache for 15 minutes
    return data

class CustomJSONEncoder(DjangoJSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class TransactionPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

def validate_field(data, field_name: str, expected_types, required: bool = True, default = None):
    value = data.get(field_name, default)

    if field_name == 'email':
        validate_email(value)
    
    if required and value is None:
        raise KeyError(field_name)
    results = set()
    for expected_type in expected_types:
        if value is not None and not isinstance(value, expected_type):
            results.add(False)
        else:
            results.add(True)
    if True not in results:
        raise ValueError(f"Invalid data type for {field_name}. Expected {expected_types}.")
    
    return value

# ----------- Email & sms helpers -------------
# @shared_task
def send_user_email(user_email, subject, message, from_email):
    """Uses sendgrid to send an email to a user
    
    Keyword arguments:
    email -- email address of the recipient
    subject -- Email subject
    message -- Email body
    from_email -- specify the from email. Default is configured in conf.yml
    Return: return_description
    """
    
    # send_mail(
    #     subject,
    #     message,
    #     settings.DEFAULT_FROM_EMAIL,
    #     [user_email],
    #     fail_silently=False
    # )

    # Log that the email has been sent (as a placeholder for SendGrid integration)
    logger.info(f"Email sent to {user_email} with subject '{subject}'")

    return True


# @shared_task
# def send_user_sms(**kwargs):
#     """Function that sends SMS messages to users
    
#     Args: receiver_number: str , message_details:{}
#     Return: None
#     """
    
#     pass

# ----------- API helpers -------------

class CustomPageNumberPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

# ----------- SHA512 signature helpers -------------
def hmac_sha512(key:str, message:bytes) -> str:
    key = key.encode('utf-8')
    hashed_payload = hmac.new(key, message, digestmod=hashlib.sha512).hexdigest()
    return hashed_payload

# -----------  Error handling helpers -------------
def handle_error(e, custom_message=None):
    logger.error(str(e), exc_info=True)
    return Response({'error': custom_message or 'An unexpected error occurred.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# -----------  Google maps -------------
def get_street_name(lat, lon, api_key):
    """
    Retrieves the street name if available; otherwise, returns the formatted address components (Lugbe and Kabusa) for a given latitude and longitude using the Google Maps Geocoding API.
    
    :param lat: Latitude of the location.
    :param lon: Longitude of the location.
    :param api_key: Your Google Maps API key.
    :return: A string containing the street name if found, otherwise Lugbe and Kabusa.
    """
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={api_key}"
    response = requests.get(url)
    data = response.json()
    
    if data["status"] == "OK":
        street_name = None
        locality = None
        administrative_area = None
        
        for result in data["results"]:
            for component in result["address_components"]:
                if "route" in component["types"]:
                    street_name = component["long_name"]
                if "locality" in component["types"]:
                    locality = component["long_name"]
                if "administrative_area_level_3" in component["types"]:
                    administrative_area = component["long_name"]
        
        if street_name and street_name.lower() != "unnamed road":
            return street_name
        elif locality and administrative_area:
            return f"{locality}, {administrative_area}"
        elif locality:
            return locality
        elif administrative_area:
            return administrative_area
    
    return None

# ----------- Translation helpers -------------
def translate_chinese_to_english(message: str) -> str:
    """
    Translates Chinese text to English using Google Cloud Translation API
    
    Args:
        message (str): The Chinese text to translate
        
    Returns:
        str: The translated English text
        
    Raises:
        Exception: If translation fails
    """
    try:
        # Initialize the translation client
        translate_client = translate.Client()
        
        # Perform the translation
        result = translate_client.translate(
            message,
            target_language='en',
            source_language='zh'
        )
        
        return result['translatedText']
        
    except Exception as e:
        logger.error(f"Translation error: {str(e)}", exc_info=True)
        raise Exception("Failed to translate text")

def translate_api_response(response: dict) -> dict:
    """
    Translates the 'msg' field in an API response from Chinese to English while preserving the response structure
    
    Args:
        response (dict): The API response containing Chinese message in 'msg' field
        
    Returns:
        dict: The API response with translated message in 'msg' field
        
    Raises:
        Exception: If translation fails
    """
    try:
        # Create a copy of the response to avoid modifying the original
        translated_response = response.copy()
        
        # Translate only the msg field if it exists
        if 'msg' in translated_response:
            translated_response['msg'] = translate_chinese_to_english(translated_response['msg'])
            
        return translated_response
        
    except Exception as e:
        logger.error(f"API response translation error: {str(e)}", exc_info=True)
        raise Exception("Failed to translate API response")

def get_vehicle_movement_status(car_id: str, token: str) -> dict:
    """
    Gets vehicle movement status from WhatsGPS API
    
    Args:
        car_id (str): The vehicle ID from WhatsGPS
        token (str): The authentication token
        
    Returns:
        dict: Movement status data or error response
    """
    try:
        url = "https://www.whatsgps.com/car/getCarAndStatus.do"
        params = {
            "token": token,
            "carId": car_id
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        
        data = response.json()
        
        # Check for API error response
        if data.get('code') != '0':
            logger.error(f"WhatsGPS API error: {data.get('msg')}")
            return {
                "status": "error",
                "message": data.get('msg', 'Unknown error')
            }
            
        return {
            "status": "success",
            "data": data
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching vehicle status: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "message": "Failed to fetch vehicle status"
        }

