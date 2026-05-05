import logging
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.models import Notification, NotificationPreference
from users.services.firebase_admin_service import firebase_admin_service
import stripe

logger = logging.getLogger(__name__)
User = get_user_model()


class StripeWebhookService:
    """
    Service to handle Stripe webhook events consistently with the existing user system
    """
    
    def __init__(self):
        self.stripe = stripe
        self.stripe.api_key = settings.STRIPE_TEST_SECRET_KEY
    
    def handle_checkout_session_completed(self, session):
        """
        Handle successful checkout session completion
        """
        logger.info(f"Processing checkout session completed: {session['id']}")
        logger.info(f"Session data: {session}")  # Debug log
        
        client_reference_id = session.get('client_reference_id')
        if not client_reference_id:
            logger.warning("No client_reference_id in session")
            return
        
        logger.info(f"Looking for user with ID: {client_reference_id}")
        
        try:
            user = User.objects.get(id=client_reference_id)
            logger.info(f"Found user: {user.email}")
            
            # Get subscription details
            subscription_id = session.get('subscription')
            customer_id = session.get('customer')
            
            if subscription_id and customer_id:
                subscription = self.stripe.Subscription.retrieve(subscription_id)
                logger.info(f"Retrieved subscription: {subscription_id}")
                
                # Update user's subscription type based on Stripe price
                subscription_type = self._get_subscription_type_from_price(subscription)
                logger.info(f"Determined subscription type: {subscription_type}")
                
                if subscription_type:
                    # Update user with subscription details
                    user.subscription_type = subscription_type
                    user.stripe_customer_id = customer_id
                    user.stripe_subscription_id = subscription_id
                    user.subscription_status = subscription.get('status', 'active')
                    
                    # Set current period end if available
                    if subscription.get('current_period_end'):
                        from django.utils import timezone
                        import datetime
                        user.subscription_current_period_end = timezone.make_aware(
                            datetime.datetime.fromtimestamp(subscription['current_period_end'])
                        )
                    
                    user.save(update_fields=[
                        'subscription_type', 'stripe_customer_id', 'stripe_subscription_id', 
                        'subscription_status', 'subscription_current_period_end'
                    ])
                    
                    logger.info(f"User {user.email} upgraded to {subscription_type} subscription")
                    
                    # Send notification to user
                    self._send_subscription_notification(
                        user=user,
                        title="Subscription Activated! 🎉",
                        message=f"Your {subscription_type.title()} subscription has been activated successfully.",
                        notification_type='system'
                    )
                    
                    # Send email notification (if you have email service set up)
                    self._send_subscription_email(user, subscription_type, 'activated')
                    
        except User.DoesNotExist:
            logger.warning(f"User with ID {client_reference_id} not found")
            # Log all available users for debugging
            logger.warning(f"Available users: {list(User.objects.values_list('id', 'email'))}")
        except Exception as e:
            logger.error(f"Error processing checkout session: {str(e)}")
            logger.error(f"Exception details: {type(e).__name__}: {str(e)}")
    
    def handle_subscription_created(self, subscription):
        """
        Handle subscription creation
        """
        logger.info(f"Processing subscription created: {subscription['id']}")
        
        customer_id = subscription.get('customer')
        if not customer_id:
            logger.warning("No customer ID in subscription")
            return
        
        try:
            # Try to find user by Stripe customer ID
            user = User.objects.get(stripe_customer_id=customer_id)
            
            subscription_type = self._get_subscription_type_from_price(subscription)
            if subscription_type:
                # Update user with subscription details
                user.subscription_type = subscription_type
                user.stripe_subscription_id = subscription['id']
                user.subscription_status = subscription.get('status', 'active')
                
                # Set current period end if available
                if subscription.get('current_period_end'):
                    from django.utils import timezone
                    import datetime
                    user.subscription_current_period_end = timezone.make_aware(
                        datetime.datetime.fromtimestamp(subscription['current_period_end'])
                    )
                
                user.save(update_fields=[
                    'subscription_type', 'stripe_subscription_id', 'subscription_status', 
                    'subscription_current_period_end'
                ])
                
                logger.info(f"User {user.email} subscription created: {subscription_type}")
                
                # Send notification
                self._send_subscription_notification(
                    user=user,
                    title="Subscription Created! 🎉",
                    message=f"Your {subscription_type.title()} subscription has been created successfully.",
                    notification_type='system'
                )
                
        except User.DoesNotExist:
            logger.warning(f"User with Stripe customer ID {customer_id} not found")
        except Exception as e:
            logger.error(f"Error processing subscription created: {str(e)}")
    
    def handle_subscription_updated(self, subscription):
        """
        Handle subscription updates (plan changes, status changes, etc.)
        """
        logger.info(f"Processing subscription updated: {subscription['id']}")
        
        customer_id = subscription.get('customer')
        if not customer_id:
            logger.warning("No customer ID in subscription")
            return
        
        try:
            # Try to find user by Stripe customer ID
            user = User.objects.get(stripe_customer_id=customer_id)
            
            # Handle different subscription statuses
            status = subscription.get('status')
            subscription_type = self._get_subscription_type_from_price(subscription)
            
            if status == 'active':
                if subscription_type:
                    # Update user with subscription details
                    user.subscription_type = subscription_type
                    user.stripe_subscription_id = subscription['id']
                    user.subscription_status = subscription.get('status', 'active')
                    
                    # Set current period end if available
                    if subscription.get('current_period_end'):
                        from django.utils import timezone
                        import datetime
                        user.subscription_current_period_end = timezone.make_aware(
                            datetime.datetime.fromtimestamp(subscription['current_period_end'])
                        )
                    
                    user.save(update_fields=[
                        'subscription_type', 'stripe_subscription_id', 'subscription_status', 
                        'subscription_current_period_end'
                    ])
                    
                    self._send_subscription_notification(
                        user=user,
                        title="Subscription Updated",
                        message=f"Your subscription has been updated to {subscription_type.title()} plan.",
                        notification_type='system'
                    )
                    
            elif status == 'past_due':
                self._send_subscription_notification(
                    user=user,
                    title="Payment Issue ⚠️",
                    message="There's an issue with your subscription payment. Please update your payment method.",
                    notification_type='system'
                )
                
            elif status == 'canceled':
                user.subscription_type = 'none'
                user.save(update_fields=['subscription_type'])
                
                self._send_subscription_notification(
                    user=user,
                    title="Subscription Canceled",
                    message="Your subscription has been canceled.",
                    notification_type='system'
                )
                    
        except User.DoesNotExist:
            logger.warning(f"User with Stripe customer ID {customer_id} not found")
        except Exception as e:
            logger.error(f"Error processing subscription update: {str(e)}")
    
    def handle_subscription_deleted(self, subscription):
        """
        Handle subscription deletion/cancellation
        """
        logger.info(f"Processing subscription deleted: {subscription['id']}")
        
        customer_id = subscription.get('customer')
        if not customer_id:
            logger.warning("No customer ID in subscription")
            return
        
        try:
            user = User.objects.get(stripe_customer_id=customer_id)
            
            user.subscription_type = 'none'
            user.stripe_subscription_id = None
            user.subscription_status = 'cancelled'
            user.subscription_current_period_end = None
            user.save(update_fields=[
                'subscription_type', 'stripe_subscription_id', 'subscription_status', 
                'subscription_current_period_end'
            ])
            
            logger.info(f"User {user.email} subscription cancelled")
            
            # Send notification
            self._send_subscription_notification(
                user=user,
                title="Subscription Cancelled",
                message="Your subscription has been cancelled. You have been moved to the free tier.",
                notification_type='system'
            )
            
            # Send cancellation email
            self._send_subscription_email(user, 'free', 'cancelled')
            
        except User.DoesNotExist:
            logger.warning(f"User with Stripe customer ID {customer_id} not found")
        except Exception as e:
            logger.error(f"Error processing subscription deletion: {str(e)}")
    
    def _get_subscription_type_from_price(self, stripe_object):
        """
        Get subscription type from a Stripe object (session or subscription)
        """
        try:
            price_id = stripe_object['plan']['id'] if 'plan' in stripe_object else stripe_object['items']['data'][0]['price']['id']
            
            if price_id == settings.STRIPE_STANDARD_PRICE_ID:
                return 'standard'
            elif price_id == settings.STRIPE_PRO_PRICE_ID:
                return 'pro'
        except (KeyError, IndexError) as e:
            logger.error(f"Could not determine subscription type from Stripe object: {stripe_object.get('id')}, error: {e}")
            
        return None

    def handle_invoice_payment_succeeded(self, invoice):
        """
        Handle successful invoice payment
        """
        logger.info(f"Processing invoice payment succeeded: {invoice['id']}")
        
        customer_id = invoice.get('customer')
        if not customer_id:
            logger.warning("No customer ID in invoice")
            return
        
        try:
            user = User.objects.get(djstripe_customers__id=customer_id)
            
            subscription_id = invoice.get('subscription')
            if subscription_id:
                subscription = self.stripe.Subscription.retrieve(subscription_id)
                subscription_type = self._get_subscription_type_from_price(subscription)
                
                if subscription_type:
                    amount = invoice.get('amount_paid', 0) / 100  
                    currency = invoice.get('currency', 'usd').upper()
                    
                    self._send_subscription_notification(
                        user=user,
                        title="Payment Successful! ✅",
                        message=f"Your {subscription_type.title()} subscription payment of {amount} {currency} has been processed successfully.",
                        notification_type='system'
                    )
                    
        except User.DoesNotExist:
            logger.warning(f"User with Stripe customer ID {customer_id} not found")
        except Exception as e:
            logger.error(f"Error processing successful payment: {str(e)}")
    
    def handle_invoice_payment_failed(self, invoice):
        """
        Handle failed invoice payment
        """
        logger.info(f"Processing invoice payment failed: {invoice['id']}")
        
        customer_id = invoice.get('customer')
        if not customer_id:
            logger.warning("No customer ID in invoice")
            return
        
        try:
            user = User.objects.get(djstripe_customers__id=customer_id)
            
            # Get subscription details
            subscription_id = invoice.get('subscription')
            if subscription_id:
                subscription = self.stripe.Subscription.retrieve(subscription_id)
                subscription_type = self._get_subscription_type_from_price(subscription)
                
                if subscription_type:
                    self._send_subscription_notification(
                        user=user,
                        title="Payment Failed ❌",
                        message=f"Your {subscription_type.title()} subscription payment failed. Please update your payment method to avoid service interruption.",
                        notification_type='system'
                    )
                    
        except User.DoesNotExist:
            logger.warning(f"User with Stripe customer ID {customer_id} not found")
        except Exception as e:
            logger.error(f"Error processing failed payment: {str(e)}")
    
    def _get_subscription_type_from_price(self, obj):
        """
        Extract subscription type from Stripe price/plan data
        """
        try:
            # Handle different object types
            if obj.get('object') == 'subscription':
                items = obj.get('items', {}).get('data', [])
                if items:
                    price_id = items[0].get('price', {}).get('id', '')
                else:
                    return None
            elif obj.get('object') == 'checkout.session':
                line_items = obj.get('line_items', {}).get('data', [])
                if line_items:
                    price_id = line_items[0].get('price', {}).get('id', '')
                else:
                    return None
            else:
                return None
            
            # Map price IDs to subscription types
            # You should update these with your actual Stripe price IDs
            price_mapping = {
                'price_1SQPmtDLm8L6uIjRDShQnxnQ': 'standard',  # Standard plan
                'price_1SQPnCDLm8L6uIjRxwgVngzv': 'pro',       # Pro plan
                # Add more price mappings as needed
            }
            
            return price_mapping.get(price_id, 'standard')  # Default to standard
            
        except Exception as e:
            logger.error(f"Error determining subscription type: {str(e)}")
            return 'standard'  # Default fallback
    
    def _send_subscription_notification(self, user, title, message, notification_type='system', data=None):
        """
        Send notification to user using the existing notification system
        """
        try:
            # Check if user wants to receive system notifications
            try:
                preferences = NotificationPreference.objects.get(user=user)
                if not preferences.system_notifications_enabled:
                    logger.info(f"User {user.email} has disabled system notifications")
                    return
            except NotificationPreference.DoesNotExist:
                # If no preferences exist, send anyway (default behavior)
                pass
            
            # Create notification record
            notification = Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                data=data or {},
                priority='high'  # Payment-related notifications are high priority
            )
            
            # Send push notification using Firebase
            firebase_admin_service.send_notification_to_user(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                data=data,
                notification_id=notification.id
            )
            
            logger.info(f"Subscription notification sent to user {user.email}")
            
        except Exception as e:
            logger.error(f"Error sending subscription notification: {str(e)}")
    
    def _send_subscription_email(self, user, subscription_type, action):
        """
        Send email notification for subscription events
        This is a placeholder - implement based on your email system
        """
        try:
            # You can implement email sending here using Django's email system
            # For now, just log it
            logger.info(f"Email notification: User {user.email} - {subscription_type} subscription {action}")
            
            # Example implementation (uncomment and customize):
            # from django.core.mail import send_mail
            # from django.conf import settings
            # 
            # subject = f"Subscription {action.title()} - Travion"
            # message = f"Dear {user.firstname},\n\nYour subscription has been {action}."
            # send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
            
        except Exception as e:
            logger.error(f"Error sending subscription email: {str(e)}")


# Create a singleton instance
stripe_webhook_service = StripeWebhookService()