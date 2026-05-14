import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from firebase_admin import auth
from users.models import DeviceToken, User
from rest_framework.permissions import IsAuthenticated


class SignupView(APIView):
    permission_classes = []

    def post(self, request):
        id_token = request.data.get('id_token')
        phone = str(request.data.get('phonenumber') or '').strip()
        fcm_token = str(request.data.get('fcm_token') or '').strip()
        device_type = str(request.data.get('device_type') or 'android').strip()

        if not id_token or not phone:
            return Response(
                {'error': 'id_token and phonenumber are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        normalized_phone = re.sub(r'[^\d+]', '', phone)

        if not normalized_phone.startswith('+'):
            return Response(
                {'error': 'Phone number must include country code'},
                status=status.HTTP_400_BAD_REQUEST
            )

        digits_only = re.sub(r'\D', '', normalized_phone)

        if len(digits_only) < 8 or len(digits_only) > 15:
            return Response(
                {'error': 'Invalid phone number'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            decoded_token = auth.verify_id_token(id_token)

            firebase_phone = decoded_token.get('phone_number')
            if not firebase_phone:
                return Response(
                    {'error': 'Phone number not found in token'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            firebase_normalized = re.sub(r'[^\d+]', '', firebase_phone)
            firebase_digits = re.sub(r'\D', '', firebase_normalized)

            if firebase_digits != digits_only:
                return Response(
                    {'error': 'Phone number mismatch'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            if User.objects.filter(phonenumber=normalized_phone).exists():
                return Response(
                    {'error': 'User already exists'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            user = User.objects.create(
                phonenumber=normalized_phone
            )

            if fcm_token and len(fcm_token) >= 10:
                DeviceToken.objects.update_or_create(
                    user=user,
                    token=fcm_token,
                    defaults={
                        'device_type': device_type,
                        'is_active': True
                    }
                )

            if not user.is_active or user.is_deleted:
                return Response(
                    {'error': 'User account is not active'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            refresh = RefreshToken.for_user(user)

            return Response({
                'message': 'User created successfully',
                'is_new_user': True,
                'user': {
                    'id': user.id,
                    'phonenumber': user.phonenumber
                },
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh)
                }
            }, status=status.HTTP_201_CREATED)

        except auth.InvalidIdTokenError:
            return Response(
                {'error': 'Invalid ID token'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        except auth.ExpiredIdTokenError:
            return Response(
                {'error': 'Token expired'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
class CreateProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        full_name = str(request.data.get('full_name') or '').strip()
        email = str(request.data.get('email') or '').strip().lower()

        if not full_name:
            return Response(
                {'error': 'Full name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        name_parts = full_name.split()

        if len(name_parts) == 1:
            firstname = name_parts[0]
            lastname = ''
        elif len(name_parts) == 2:
            firstname, lastname = name_parts
        else:
            firstname = " ".join(name_parts[:-1])
            lastname = name_parts[-1]

        user.firstname = firstname
        user.lastname = lastname

        if email:
            if User.objects.filter(email=email).exclude(id=user.id).exists():
                return Response(
                    {'error': 'Email already in use'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            user.email = email

        user.save()

        return Response({
            'message': 'Profile Created successfully',
            'user': {
                'id': user.id,
                'firstname': user.firstname,
                'lastname': user.lastname,
                'full_name': user.full_name,
                'email': user.email,
                'phonenumber': user.phonenumber
            }
        }, status=status.HTTP_200_OK)
