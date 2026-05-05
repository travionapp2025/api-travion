import json
from django.http import JsonResponse
from django.views import View
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import User
import re


class LoginView(View):
    """
    User login view with JWT tokens supporting both email and phone number authentication
    """
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)
        
        identifier = data.get('email', '') or data.get('identifier', '')
        identifier = identifier.strip()
        password = data.get('password', '')
        fcm_token = data.get('fcm_token', '').strip()
        device_type = data.get('device_type', 'android')
        
        if not identifier or not password:
            return JsonResponse({'error': 'Email/phone number and password are required'}, status=400)
        
        user = None
        
        if '@' in identifier:
            user = authenticate(username=identifier.lower(), password=password)
        else:
            clean_phone = re.sub(r'[^\d+]', '', identifier)
            
            try:
                user_obj = User.objects.get(phonenumber=clean_phone)
                user = authenticate(username=user_obj.email, password=password)
            except User.DoesNotExist:
                user = authenticate(username=identifier.lower(), password=password)
        
        if not user and '@' not in identifier:
            user = authenticate(username=identifier.lower(), password=password)
        
        if not user:
            return JsonResponse({'error': 'Invalid credentials'}, status=401)
        
        if not user.is_active:
            return JsonResponse({'error': 'User account is disabled'}, status=401)
        
        if user.is_deleted:
            return JsonResponse({'error': 'User account has been deleted'}, status=401)
        
        if fcm_token and len(fcm_token) >= 10:
            from ..models import DeviceToken
            DeviceToken.objects.update_or_create(
                user=user,
                token=fcm_token,
                defaults={'device_type': device_type, 'is_active': True}
            )
        
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        
        return JsonResponse({
            'message': 'Login successful',
            'user': {
                'id': user.id,
                'email': user.email,
                'firstname': user.firstname,
                'lastname': user.lastname,
                'phonenumber': user.phonenumber,
                'role': user.role,
                'full_name': user.full_name,
                'subscription_type': user.subscription_type
            },
            'tokens': {
                'access': str(access_token),
                'refresh': str(refresh)
            }
        }, status=200)