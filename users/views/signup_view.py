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

            # Get or create user - if user exists, is_new_user will be False
            user, is_new_user = User.objects.get_or_create(
                phonenumber=normalized_phone
            )
            was_deleted = user.is_deleted

            if was_deleted:
                user.is_deleted = False
                user.is_active = True
                user.save(update_fields=['is_deleted', 'is_active', 'updated_at'])

            # Update or create FCM token for both new and existing users
            if fcm_token and len(fcm_token) >= 10:
                DeviceToken.objects.update_or_create(
                    user=user,
                    token=fcm_token,
                    defaults={
                        'device_type': device_type,
                        'is_active': True
                    }
                )

            # Check if user account is active
            if not user.is_active:
                return Response(
                    {'error': 'User account is not active'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            # Generate tokens for both new and existing users
            refresh = RefreshToken.for_user(user)

            # Determine response status based on whether user is new
            response_status = status.HTTP_201_CREATED if is_new_user else status.HTTP_200_OK
            if is_new_user:
                response_message = 'User created successfully'
            elif was_deleted:
                response_message = 'Account reactivated successfully'
            else:
                response_message = 'Login successful'

            return Response({
                'message': response_message,
                'is_new_user': is_new_user,
                'user': {
                    'id': user.id,
                    'phonenumber': user.phonenumber
                },
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh)
                }
            }, status=response_status)

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
        role = request.data.get('role')

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

        if role is not None:
            role_value = role.strip().lower() if isinstance(role, str) else role
            valid_roles = {choice[0] for choice in User.ROLE_CHOICES}
            if role_value not in valid_roles:
                return Response(
                    {'error': f"Invalid role. Allowed values: {', '.join(sorted(valid_roles))}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            user.role = role_value

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
                'phonenumber': user.phonenumber,
                'role': user.role
            }
        }, status=status.HTTP_200_OK)
