import json
import re
from django.http import JsonResponse
from django.views import View
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import User


class LoginView(View):
    def post(self, request):

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)

        phone = str(data.get('phonenumber') or '').strip()
        fcm_token = str(data.get('fcm_token') or '').strip()
        device_type = str(data.get('device_type') or 'android').strip()

        if not phone:
            return JsonResponse({'error': 'Phone number is required'}, status=400)

        normalized_phone = re.sub(r'[^\d+]', '', phone)

        if not normalized_phone.startswith('+'):
            return JsonResponse({'error': 'Phone number must include country code'}, status=400)

        digits_only = re.sub(r'\D', '', normalized_phone)

        if len(digits_only) < 8 or len(digits_only) > 15:
            return JsonResponse({'error': 'Invalid phone number'}, status=400)

        try:
            user = User.objects.get(phonenumber=normalized_phone)

            if not user.is_active or user.is_deleted:
                return JsonResponse({'error': 'User account is not active'}, status=401)

            if fcm_token and len(fcm_token) >= 10:
                from users.models import DeviceToken
                DeviceToken.objects.update_or_create(
                    user=user,
                    token=fcm_token,
                    defaults={
                        'device_type': device_type,
                        'is_active': True
                    }
                )

            refresh = RefreshToken.for_user(user)

            return JsonResponse({
                'user_exist': True,
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
                    'access': str(refresh.access_token),
                    'refresh': str(refresh)
                }
            }, status=200)

        except User.DoesNotExist:
            return JsonResponse({
                'user_exist': False
            }, status=200)