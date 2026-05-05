import logging
from django.core.mail import send_mail
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

logger = logging.getLogger(__name__)


class ContactFeedbackView(APIView):
    """
    Handle contact/feedback form submissions and send emails to travionapp2025@gmail.com
    """
    permission_classes = [AllowAny]  # Allow both authenticated and unauthenticated users
    
    def post(self, request):
        """
        Send contact/feedback email
        
        Expected payload:
        {
            "name": "John Doe" (optional),
            "email": "user@example.com" (optional),
            "message": "Your feedback message" (required)
        }
        """
        try:
            # Extract data from request
            name = request.data.get('name', 'Anonymous')
            user_email = request.data.get('email', 'No email provided')
            message = request.data.get('message', '').strip()
            
            # Validate required fields
            if not message:
                return Response(
                    {'error': 'Message is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Prepare email content
            subject = f'Contact/Feedback from {name}'
            email_body = f"""
New Contact/Feedback Submission

From: {name}
Email: {user_email}

Message:
{message}

---
This message was sent from the Travion app contact form.
            """
            
            # Send email
            try:
                send_mail(
                    subject=subject,
                    message=email_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=['travionapp2025@gmail.com'],
                    fail_silently=False,
                )
                
                logger.info(f"Contact email sent successfully from {name} ({user_email})")
                
                return Response(
                    {
                        'success': True,
                        'message': 'Your message has been sent successfully. We will get back to you soon!'
                    },
                    status=status.HTTP_200_OK
                )
                
            except Exception as email_error:
                logger.error(f"Error sending contact email: {str(email_error)}")
                return Response(
                    {'error': 'Failed to send email. Please try again later.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            logger.error(f"Error processing contact form: {str(e)}")
            return Response(
                {'error': 'An error occurred processing your request'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
