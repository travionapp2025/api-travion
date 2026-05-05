from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from users.models import User
from users.constants.languages import LANGUAGES
from users.models import Language
import logging

logger = logging.getLogger(__name__)


class UserProfileView(APIView):
    """
    API view to retrieve user profile information
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            profile_data = {
                'id': user.id,
                'email': user.email,
                'firstname': user.firstname,
                'lastname': user.lastname,
                'phonenumber': user.phonenumber,
                'role': user.role,
                'gender': user.gender,
                'bio': user.bio,
                'profile_picture': user.profile_picture.url if user.profile_picture else None,
                'date_joined': user.date_joined,
                'updated_at': user.updated_at,
                'full_name': user.full_name,
                'languages': [
                    {'code': l.code, 'name': l.name} for l in user.languages.all().order_by('name')
                ],
                'subscription_type': user.subscription_type,
            }
            
            return Response(profile_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error retrieving profile for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve profile'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UpdateUserProfileView(APIView):
    """
    API view to update user profile information including role, profile picture and bio
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def put(self, request):
        try:
            user = request.user
            firstname = request.data.get('firstname')
            lastname = request.data.get('lastname')
            name = request.data.get('name')
            phonenumber = request.data.get('phonenumber')
            bio = request.data.get('bio')
            role = request.data.get('role')
            gender = request.data.get('gender')
            languages = request.data.get('languages')
            profile_picture = None
            if hasattr(request, 'FILES') and 'profile_picture' in request.FILES:
                profile_picture = request.FILES.get('profile_picture')
            
            if firstname is not None:
                if not firstname.strip():
                    return Response(
                        {'error': 'First name cannot be empty'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                user.firstname = firstname.strip()
            
            if lastname is not None:
                if not lastname.strip():
                    return Response(
                        {'error': 'Last name cannot be empty'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                user.lastname = lastname.strip()

            # Support single 'name' field for editing full name
            if name is not None:
                name_str = name.strip()
                if not name_str:
                    return Response({'error': 'Name cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)
                parts = name_str.split()
                user.firstname = parts[0]
                user.lastname = ' '.join(parts[1:]) if len(parts) > 1 else ''
            
            if phonenumber is not None:
                user.phonenumber = phonenumber.strip() if phonenumber.strip() else None
            
            if bio is not None:
                if len(bio) > 500:
                    return Response(
                        {'error': 'Bio cannot exceed 500 characters'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                user.bio = bio.strip() if bio.strip() else None

            # Update role if provided and valid
            if role is not None:
                role_value = role.strip().lower() if isinstance(role, str) else role
                valid_roles = {choice[0] for choice in User.ROLE_CHOICES}
                if role_value not in valid_roles:
                    return Response(
                        {'error': f"Invalid role. Allowed values: {', '.join(sorted(valid_roles))}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                user.role = role_value

            # Update gender if provided and valid
            if gender is not None:
                gender_value = gender.strip().lower() if isinstance(gender, str) else gender
                valid_genders = {choice[0] for choice in User.GENDER_CHOICES}
                if gender_value not in valid_genders:
                    return Response(
                        {'error': f"Invalid gender. Allowed values: {', '.join(sorted(valid_genders))}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                user.gender = gender_value

            # Update languages if provided
            if languages is not None:
                if not isinstance(languages, list):
                    return Response({'error': 'Languages must be a list of codes'}, status=status.HTTP_400_BAD_REQUEST)
                valid_codes = {code for code, _ in LANGUAGES}
                invalid = [c for c in languages if c not in valid_codes]
                if invalid:
                    return Response({'error': f"Invalid language codes: {', '.join(invalid)}"}, status=status.HTTP_400_BAD_REQUEST)

                # Ensure codes exist in DB and set M2M
                code_to_name = {code: name for code, name in LANGUAGES}
                for code in languages:
                    Language.objects.get_or_create(code=code, defaults={'name': code_to_name[code]})

                if len(languages) == 0:
                    user.languages.clear()
                else:
                    qs = Language.objects.filter(code__in=languages)
                    user.languages.set(list(qs))
            
            if profile_picture is not None:
                if profile_picture.size > 5 * 1024 * 1024:
                    return Response(
                        {'error': 'Profile picture size cannot exceed 5MB'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
                if profile_picture.content_type not in allowed_types:
                    return Response(
                        {'error': 'Profile picture must be a JPEG, PNG, or GIF image'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                user.profile_picture = profile_picture
            
            user.save()
            logger.info(f"Profile updated successfully for user {user.email}")
            
            profile_data = {
                'id': user.id,
                'email': user.email,
                'firstname': user.firstname,
                'lastname': user.lastname,
                'phonenumber': user.phonenumber,
                'role': user.role,
                'gender': user.gender,
                'bio': user.bio,
                'profile_picture': user.profile_picture.url if user.profile_picture else None,
                'date_joined': user.date_joined,
                'updated_at': user.updated_at,
                'full_name': user.full_name,
                'languages': [
                    {'code': l.code, 'name': l.name} for l in user.languages.all().order_by('name')
                ]
            }
            
            return Response(
                {
                    'message': 'Profile updated successfully',
                    'profile': profile_data
                }, 
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f"Error updating profile for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to update profile'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def patch(self, request):
        """
        Partial update - same as PUT but more semantically correct for partial updates
        """
        return self.put(request)


class ChangePasswordView(APIView):
    """
    API view to change user password (requires current password)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            current_password = request.data.get('current_password')
            new_password = request.data.get('new_password')
            confirm_password = request.data.get('confirm_password')

            # Validate required fields
            if not all([current_password, new_password, confirm_password]):
                return Response(
                    {'error': 'All fields are required (current_password, new_password, confirm_password)'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check current password
            if not user.check_password(current_password):
                return Response(
                    {'error': 'Current password is incorrect'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if new passwords match
            if new_password != confirm_password:
                return Response(
                    {'error': 'New passwords do not match'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate new password strength
            try:
                validate_password(new_password, user)
            except ValidationError as e:
                return Response(
                    {'error': list(e.messages)}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Update password
            user.set_password(new_password)
            user.save()

            logger.info(f"Password changed successfully for user {user.email}")

            return Response(
                {'message': 'Password changed successfully'}, 
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error changing password for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to change password'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )