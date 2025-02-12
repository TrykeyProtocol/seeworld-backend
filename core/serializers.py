from rest_framework import serializers
from .models import User, Transaction
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    account_number = serializers.CharField(required=False, allow_blank=True)
    bank = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    confirm_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    avatar = serializers.ImageField(required=False)

    class Meta:
        model = User
        fields = ['first_name', 'last_name',
                'email', 'password',
                'confirm_password', 'account_number',
                  'bank', 'avatar']

    def validate(self, data):
        if data.get('account_number') and not data.get('bank'):
            raise serializers.ValidationError({"bank": "Bank information is required when account number is provided."})
        
        if data.get('password') != data.get('confirm_password'):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        
        return data

    def create(self, validated_data):
        # Remove confirm_password from the data used to create the user
        validated_data.pop('confirm_password', None)
        password = validated_data.pop('password')
        
        # Set default avatar if not provided
        if 'avatar' not in validated_data:
            validated_data['avatar'] = 'default_avatars/default_avatar.png'
        
        email = validated_data.pop('email')  # Remove email from validated_data
        
        user = User.objects.create_user(
            email=email,
            username=email,  # Set username to email
            password=password,
            **validated_data
        )
        return user
    
class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            'id', 
            'name', 
            'email', 
            'transaction_ref', 
            'amount', 
            'currency', 
            'payment_status', 
            'payment_type', 
            'is_outgoing', 
            'timestamp'
        ]