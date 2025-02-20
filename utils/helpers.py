from decimal import Decimal
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from seeworld import settings

import hmac
import hashlib


# TODO: concurrent emails
# import celery
# import sendgrid
# from sendgrid.helpers.mail import *

from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
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
# def send_user_email(user_email, subject, message):

#     send_mail(
#         subject,
#         message,
#         settings.DEFAULT_FROM_EMAIL,
#         [user_email],
#         fail_silently=False
#     )
#     """Function that sends emails to users
    
#     Args: receiver_email: str , message_details:{}
#     Return: None
#     """

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

# -----------  Auth helpers -------------