from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.core.mail import send_mail
from django.conf import settings
from users.models import User, EmailOTP
import logging

logger = logging.getLogger(__name__)


class ForgotPasswordView(APIView):
    """
    API view to send OTP to user's email for password reset
    Step 1: User enters email, receives OTP via email
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

            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                # Don't reveal if email exists or not for security
                return Response(
                    {'message': 'If the email exists, an OTP has been sent to your email.'}, 
                    status=status.HTTP_200_OK
                )

            otp_instance = EmailOTP.create_otp(email)

            subject = 'Password Reset OTP - Signature'
            message = f"""
                Hi {user.firstname},

                You requested to reset your password. Your OTP is: {otp_instance.otp_code}

                This OTP is valid for 10 minutes only.

                If you didn't request this, please ignore this email.

                Best regards,
                The Signature Team
            """

            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                logger.info(f"OTP sent to {user.email}")
            except Exception as e:
                logger.error(f"Failed to send OTP to {user.email}: {str(e)}")
                return Response(
                    {'error': 'Failed to send OTP'}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            return Response(
                {'message': 'If the email exists, an OTP has been sent to your email.'}, 
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error in send OTP: {str(e)}")
            return Response(
                {'error': 'An error occurred while processing your request'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VerifyOTPView(APIView):
    """
    API view to verify OTP code
    Step 2: User enters OTP to verify it's correct
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            email = request.data.get('email')
            otp_code = request.data.get('otp')
            
            if not email or not otp_code:
                return Response(
                    {'error': 'Email and OTP are required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response(
                    {'error': 'Invalid email or OTP'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            if EmailOTP.verify_otp(email, otp_code):
                return Response(
                    {
                        'message': 'OTP verified successfully. You can now reset your password.',
                        'email': email,
                        'verified': True
                    }, 
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {'error': 'Invalid or expired OTP'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Error in verify OTP: {str(e)}")
            return Response(
                {'error': 'An error occurred while verifying OTP'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ResetPasswordView(APIView):
    """
    API view to reset password using previously verified OTP
    Step 3: User enters new password + confirm password + email (OTP already verified in step 2)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            email = request.data.get('email')
            new_password = request.data.get('new_password')
            confirm_password = request.data.get('confirm_password')

            # Validate required fields
            if not all([email, new_password, confirm_password]):
                return Response(
                    {'error': 'All fields are required (email, new_password, confirm_password)'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if passwords match
            if new_password != confirm_password:
                return Response(
                    {'error': 'Passwords do not match'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate password strength
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError
            
            try:
                validate_password(new_password)
            except ValidationError as e:
                return Response(
                    {'error': list(e.messages)}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if user exists
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response(
                    {'error': 'Invalid email'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if there's a verified OTP for this email
            if EmailOTP.has_verified_otp(email):
                # Update password
                user.set_password(new_password)
                user.save()

                # Mark the verified OTP as used
                EmailOTP.mark_verified_otp_as_used(email)

                logger.info(f"Password reset successful for user {user.email}")

                return Response(
                    {'message': 'Password has been reset successfully. You can now login with your new password.'}, 
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {'error': 'No verified OTP found. Please verify your OTP first.'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Error in reset password with OTP: {str(e)}")
            return Response(
                {'error': 'An error occurred while resetting your password'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )