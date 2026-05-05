import json
from django.http import JsonResponse
from django.views import View
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import DeviceToken


class LogoutView(View):
    """
    Logout view - blacklist refresh token and clear FCM tokens
    """
    def post(self, request):
        try:
            data = json.loads(request.body)
            refresh_token = data.get('refresh_token')
            fcm_token = data.get('fcm_token')
            
            if refresh_token:
                token = RefreshToken(refresh_token)
                
                user = token.payload.get('user_id')
                token.blacklist()
                
                if user and fcm_token:
                    DeviceToken.objects.filter(user_id=user, token=fcm_token).delete()
                    
                    self._send_device_logout_update(user, fcm_token)
            
            return JsonResponse({'message': 'Logout successful'}, status=200)
            
        except Exception as e:
            return JsonResponse({'message': 'Logout successful'}, status=200)

    def _send_device_logout_update(self, user_id, fcm_token):
        """Send WebSocket update when device logs out"""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            from users.models import DeviceToken
            
            channel_layer = get_channel_layer()
            if not channel_layer:
                return
            
            remaining_devices = DeviceToken.objects.filter(user_id=user_id, is_active=True).count()
            
            group_name = f"chat_updates_{user_id}"
            async_to_sync(channel_layer.group_send)(group_name, {
                'type': 'device_token_update',
                'action': 'removed',
                'device_type': 'unknown',  
                'total_devices': remaining_devices
            })
            
        except Exception as e:
            pass  