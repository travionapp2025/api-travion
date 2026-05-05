import logging
import stripe
from django.conf import settings
from django.http import JsonResponse
from django.views import View
from .webhook_service import stripe_webhook_service

logger = logging.getLogger(__name__)


class StripeWebhookView(View):
    """
    Handle Stripe webhook events using consistent API view pattern
    """
    def post(self, request):
        """
        Process Stripe webhook events
        """
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        
        if not sig_header:
            logger.error("Missing Stripe signature")
            return JsonResponse({'error': 'Missing signature'}, status=400)
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
            
            logger.info(f"Received Stripe webhook event: {event['type']}")
            
            self._process_webhook_event(event)
            
            return JsonResponse({'status': 'success'})
            
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Stripe signature verification failed: {str(e)}")
            return JsonResponse({'error': 'Invalid signature'}, status=400)
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error: {str(e)}")
            return JsonResponse({'error': 'Stripe API error'}, status=400)
        except Exception as e:
            logger.error(f"Webhook processing error: {str(e)}")
            return JsonResponse({'error': 'Internal server error'}, status=500)
    
    def _process_webhook_event(self, event):
        """
        Route webhook events to appropriate handlers
        """
        event_type = event['type']
        event_data = event['data']['object']
        
        event_handlers = {
            'checkout.session.completed': stripe_webhook_service.handle_checkout_session_completed,
            'customer.subscription.created': stripe_webhook_service.handle_subscription_created,
            'customer.subscription.updated': stripe_webhook_service.handle_subscription_updated,
            'customer.subscription.deleted': stripe_webhook_service.handle_subscription_deleted,
            'invoice.payment_succeeded': stripe_webhook_service.handle_invoice_payment_succeeded,
            'invoice.payment_failed': stripe_webhook_service.handle_invoice_payment_failed,
        }
        
        handler = event_handlers.get(event_type)
        
        if handler:
            try:
                handler(event_data)
                logger.info(f"Successfully processed event: {event_type}")
            except Exception as e:
                logger.error(f"Error processing {event_type}: {str(e)}")
        else:
            logger.info(f"Unhandled event type: {event_type}")


def stripe_webhook(request):
    """
    Function-based view for Stripe webhook
    """
    view = StripeWebhookView()
    return view.post(request)