import json
from django.http import JsonResponse
from django.views import View
from rest_framework_simplejwt.tokens import RefreshToken


class RefreshTokenView(View):
    """
    Simple token refresh view
    """
    def post(self, request):
        try:
            data = json.loads(request.body)
            refresh_token = data.get('refresh')
            
            if not refresh_token:
                return JsonResponse({'error': 'Refresh token is required'}, status=400)
            
            token = RefreshToken(refresh_token)
            access_token = token.access_token
            
            return JsonResponse({
                'access': str(access_token)
            }, status=200)
            
        except Exception as e:
            return JsonResponse({'error': 'Invalid refresh token'}, status=401)