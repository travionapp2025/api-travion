from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from users.models import User
import logging

logger = logging.getLogger(__name__)


class ResetPasswordView(APIView):
    """
    API view to handle password reset confirmation.
    Validates the token and updates the user's password.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            uid = request.data.get('uid')
            token = request.data.get('token')
            new_password = request.data.get('new_password')
            confirm_password = request.data.get('confirm_password')

            # Validate required fields
            if not all([uid, token, new_password, confirm_password]):
                return Response(
                    {'error': 'All fields are required (uid, token, new_password, confirm_password)'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if passwords match
            if new_password != confirm_password:
                return Response(
                    {'error': 'Passwords do not match'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate password strength
            try:
                validate_password(new_password)
            except ValidationError as e:
                return Response(
                    {'error': list(e.messages)}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Decode user ID
            try:
                user_id = force_str(urlsafe_base64_decode(uid))
                user = User.objects.get(pk=user_id)
            except (TypeError, ValueError, OverflowError, User.DoesNotExist):
                return Response(
                    {'error': 'Invalid reset link'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate token
            if not default_token_generator.check_token(user, token):
                return Response(
                    {'error': 'Invalid or expired reset link'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Update password
            user.set_password(new_password)
            user.save()

            logger.info(f"Password reset successful for user {user.email}")

            return Response(
                {'message': 'Password has been reset successfully'}, 
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error in reset password: {str(e)}")
            return Response(
                {'error': 'An error occurred while resetting your password'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ValidateResetTokenView(APIView):
    """
    API view to validate password reset token without resetting password.
    Useful for frontend to check if reset link is valid before showing reset form.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            uid = request.data.get('uid')
            token = request.data.get('token')

            if not uid or not token:
                return Response(
                    {'error': 'UID and token are required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Decode user ID
            try:
                user_id = force_str(urlsafe_base64_decode(uid))
                user = User.objects.get(pk=user_id)
            except (TypeError, ValueError, OverflowError, User.DoesNotExist):
                return Response(
                    {'valid': False, 'error': 'Invalid reset link'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate token
            if not default_token_generator.check_token(user, token):
                return Response(
                    {'valid': False, 'error': 'Invalid or expired reset link'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {'valid': True, 'message': 'Reset token is valid'}, 
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error in validate reset token: {str(e)}")
            return Response(
                {'valid': False, 'error': 'An error occurred while validating the token'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )