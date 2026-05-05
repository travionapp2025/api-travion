from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from users.models import User
import logging

logger = logging.getLogger(__name__)


class ForgotPasswordView(APIView):
    """
    API view to handle password reset requests.
    Sends a password reset email to the user if the email exists.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            email = request.data.get('email')
            
            if not email:
                return Response(
                    {'error': 'Email is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if user exists
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                # For security reasons, don't reveal if email exists or not
                return Response(
                    {'message': 'If the email exists, a password reset link has been sent.'}, 
                    status=status.HTTP_200_OK
                )

            # Generate password reset token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))

            # Create reset link
            reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}/"

            # Email content
            subject = 'Password Reset Request'
            message = f"""
            Hi {user.firstname},

            You requested a password reset for your account. Click the link below to reset your password:

            {reset_link}

            If you didn't request this, please ignore this email.

            Best regards,
            The Signature Team
            """

            # Send email
            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                logger.info(f"Password reset email sent to {user.email}")
            except Exception as e:
                logger.error(f"Failed to send password reset email to {user.email}: {str(e)}")
                return Response(
                    {'error': 'Failed to send password reset email'}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            return Response(
                {'message': 'If the email exists, a password reset link has been sent.'}, 
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error in forgot password: {str(e)}")
            return Response(
                {'error': 'An error occurred while processing your request'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )