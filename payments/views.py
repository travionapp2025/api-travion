import logging
import stripe
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from stripe import StripeError
from .models import SubscriptionDetails
from datetime import datetime, timedelta, timezone
from datetime import timezone as dt_timezone
from django.utils import timezone

import requests
from payments.utils.apple_verify import verify_storekit2_receipt
from payments.utils.google_verify import verify_google_subscription,cancel_google_subscription
import base64
import json
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .webhook_service import stripe_webhook_service

logger = logging.getLogger(__name__)
User = get_user_model()

# Initialize Stripe
stripe.api_key = settings.STRIPE_TEST_SECRET_KEY


def send_apple_subscription_notification(user, event_type, subscription_details):
    """
    Send in-app and FCM notification for Apple subscription events
    """
    from users.services.firebase_admin_service import FirebaseService
    from users.models import Notification

    firebase_service = FirebaseService()

    # Map event types to notification content
    notification_mapping = {
        'SUBSCRIBED': {
            'title': 'Subscription Activated',
            'message': 'Your Apple subscription has been successfully activated!',
            'type': 'system'
        },
        'DID_RENEW': {
            'title': 'Subscription Renewed',
            'message': 'Your Apple subscription has been automatically renewed.',
            'type': 'system'
        },
        'EXPIRED': {
            'title': 'Subscription Expired',
            'message': 'Your Apple subscription has expired.',
            'type': 'system'
        },
        'CANCELLED': {
            'title': 'Subscription Cancelled',
            'message': 'Your Apple subscription has been cancelled.',
            'type': 'system'
        },
        'REFUND': {
            'title': 'Subscription Refunded',
            'message': 'Your Apple subscription has been refunded.',
            'type': 'system'
        },
        'DID_FAIL_TO_RENEW': {
            'title': 'Subscription Renewal Failed',
            'message': 'Your Apple subscription renewal failed. Please update your payment method.',
            'type': 'system'
        }
    }

    notification_config = notification_mapping.get(event_type, {
        'title': 'Subscription Update',
        'message': f'Your Apple subscription status has changed: {event_type}',
        'type': 'system'
    })

    # Create in-app notification and send FCM
    try:
        firebase_service.send_notification_to_user(
            user=user,
            title=notification_config['title'],
            body=notification_config['message'],
            notification_type=notification_config['type'],
            data={
                'event_type': event_type,
                'platform': 'apple',
                'subscription_details': subscription_details
            }
        )
        logger.info(f"Apple subscription notification sent to user {user.id}: {event_type}")
    except Exception as e:
        logger.error(f"Failed to send Apple subscription notification to user {user.id}: {str(e)}")


def send_google_subscription_notification(user, event_type, subscription_details):
    """
    Send in-app and FCM notification for Google subscription events
    """
    from users.services.firebase_admin_service import FirebaseService
    from users.models import Notification

    firebase_service = FirebaseService()

    # Map event types to notification content
    notification_mapping = {
        'SUBSCRIPTION_PURCHASED': {
            'title': 'Subscription Activated',
            'message': 'Your Google Play subscription has been successfully activated!',
            'type': 'system'
        },
        'SUBSCRIPTION_RENEWED': {
            'title': 'Subscription Renewed',
            'message': 'Your Google Play subscription has been automatically renewed.',
            'type': 'system'
        },
        'SUBSCRIPTION_EXPIRED': {
            'title': 'Subscription Expired',
            'message': 'Your Google Play subscription has expired.',
            'type': 'system'
        },
        'SUBSCRIPTION_CANCELED': {
            'title': 'Subscription Cancelled',
            'message': 'Your Google Play subscription has been cancelled.',
            'type': 'system'
        },
        'SUBSCRIPTION_ON_HOLD': {
            'title': 'Subscription On Hold',
            'message': 'Your Google Play subscription is on hold. Please update your payment method.',
            'type': 'system'
        },
        'SUBSCRIPTION_IN_GRACE_PERIOD': {
            'title': 'Subscription Grace Period',
            'message': 'Your Google Play subscription is in grace period. Please update your payment method.',
            'type': 'system'
        },
        'SUBSCRIPTION_RESTARTED': {
            'title': 'Subscription Restarted',
            'message': 'Your Google Play subscription has been restarted.',
            'type': 'system'
        }
    }

    notification_config = notification_mapping.get(event_type, {
        'title': 'Subscription Update',
        'message': f'Your Google Play subscription status has changed: {event_type}',
        'type': 'system'
    })

    # Create in-app notification and send FCM
    try:
        firebase_service.send_notification_to_user(
            user=user,
            title=notification_config['title'],
            body=notification_config['message'],
            notification_type=notification_config['type'],
            data={
                'event_type': event_type,
                'platform': 'google',
                'subscription_details': subscription_details
            }
        )
        logger.info(f"Google subscription notification sent to user {user.id}: {event_type}")
    except Exception as e:
        logger.error(f"Failed to send Google subscription notification to user {user.id}: {str(e)}")


def send_stripe_subscription_notification(user, event_type, subscription_details):
    """
    Send in-app and FCM notification for Stripe subscription events
    """
    from users.services.firebase_admin_service import FirebaseService
    from users.models import Notification

    firebase_service = FirebaseService()

    notification_mapping = {
        'PURCHASED': {
            'title': 'Subscription Activated',
            'message': 'Your subscription has been successfully activated!',
            'type': 'system'
        },
        'RENEWED': {
            'title': 'Subscription Renewed',
            'message': 'Your subscription has been renewed.',
            'type': 'system'
        },
        'CANCELLED': {
            'title': 'Subscription Cancelled',
            'message': 'Your subscription has been cancelled.',
            'type': 'system'
        },
        'REFUNDED': {
            'title': 'Subscription Refunded',
            'message': 'Your subscription has been refunded.',
            'type': 'system'
        }
    }

    notification_config = notification_mapping.get(event_type, {
        'title': 'Subscription Update',
        'message': f'Your subscription status has changed: {event_type}',
        'type': 'system'
    })

    try:
        firebase_service.send_notification_to_user(
            user=user,
            title=notification_config['title'],
            body=notification_config['message'],
            notification_type=notification_config['type'],
            data={
                'event_type': event_type,
                'platform': 'stripe',
                'subscription_details': subscription_details
            }
        )
        logger.info(f"Stripe subscription notification sent to user {user.id}: {event_type}")
    except Exception as e:
        logger.error(f"Failed to send Stripe subscription notification to user {user.id}: {str(e)}")


class CreateCheckoutSessionView(APIView):
    """
    Create Stripe checkout session for subscription
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Create checkout session with proper error handling
        """
        try:
            subscription_type = request.data.get('subscription_type', 'standard').lower()
            price_mapping = {
                'standard': settings.STRIPE_STANDARD_PRICE_ID,
                'pro': settings.STRIPE_PRO_PRICE_ID,
            }
            
            price_id = price_mapping.get(subscription_type)
            if not price_id:
                return Response(
                    {'error': 'Invalid subscription type'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create checkout session
            checkout_session = stripe.checkout.Session.create(
                client_reference_id=str(request.user.id),
                customer_email=request.user.email,
                line_items=[
                    {
                        'price': price_id,
                        'quantity': 1,
                    },
                ],
                mode='subscription',
                success_url=f"{settings.SITE_URL}/api/payments/success/?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{settings.SITE_URL}/api/payments/cancel/",
                metadata={
                    'user_id': str(request.user.id),
                    'subscription_type': subscription_type,
                }
            )
            
            logger.info(f"Checkout session created for user {request.user.email}: {checkout_session.id}")
            
            return Response({
                'session_id': checkout_session.id,
                'session_url': checkout_session.url,
            })
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {str(e)}")
            return Response(
                {'error': 'Payment service error. Please try again.'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(f"Error creating checkout session: {str(e)}")
            return Response(
                {'error': 'An error occurred. Please try again.'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PaymentSuccessView(View):
    """
    Handle successful payment redirect
    """

    def get(self, request):
        """
        Display success page after successful payment
        """
        session_id = request.GET.get('session_id')
        
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            context = {
                'session_id': session_id,
                'subscription_status': session.get('subscription_status', 'active'),
            }
            
            return render(request, 'payments/success.html', context)
            
        except stripe.error.StripeError as e:
            logger.error(f"Error retrieving checkout session: {str(e)}")
            return render(request, 'payments/success.html', {
                'error': 'Unable to verify payment details'
            })
        except Exception as e:
            logger.error(f"Error processing success page: {str(e)}")
            return render(request, 'payments/success.html', {
                'error': 'An error occurred processing your payment'
            })


class PaymentCancelView(View):
    """
    Handle canceled payment redirect
    """
    
    def get(self, request):
        """
        Display cancel page when user cancels payment
        """
        return render(request, 'payments/cancel.html')


class SubscriptionStatusView(APIView):
    """
    Get current user's subscription status
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Return user's current subscription details
        """
        user = request.user
        
        try:
            stripe_customer_id = user.stripe_customer_id
            
            subscription_data = {
                'subscription_type': user.subscription_type,
                'is_subscribed': user.subscription_type != 'none',
                'subscription_label': self._get_subscription_label(user.subscription_type),
                'stripe_customer_id': user.stripe_customer_id,
                'stripe_subscription_id': user.stripe_subscription_id,
                'subscription_status': user.subscription_status,
                'subscription_current_period_end': user.subscription_current_period_end,
            }
            
            if stripe_customer_id:
                try:
                    subscriptions = stripe.Subscription.list(
                        customer=stripe_customer_id,
                        status='active',
                        limit=1
                    )
                    
                    if subscriptions.data:
                        subscription = subscriptions.data[0]
                        subscription_data.update({
                            'subscription_id': subscription.id,
                            'status': subscription.status,
                            'current_period_end': subscription.current_period_end,
                            'cancel_at_period_end': subscription.cancel_at_period_end,
                        })
                        
                except stripe.error.StripeError as e:
                    logger.error(f"Error fetching Stripe subscription: {str(e)}")
            
            return Response(subscription_data)
            
        except Exception as e:
            logger.error(f"Error getting subscription status: {str(e)}")
            return Response(
                {'error': 'Unable to retrieve subscription status'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _get_subscription_label(self, subscription_type):
        """
        Get human-readable subscription label
        """
        labels = {
            'none': 'No Subscription',
            'standard': 'Standard Plan',
            'pro': 'Pro Plan',
        }
        return labels.get(subscription_type, 'Unknown')


class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        logger.info(
            "CancelSubscription request received",
            extra={"user_id": user.id, "email": user.email},
        )

        try:
            # -------------------------------
            # STRIPE
            # -------------------------------
            if user.stripe_subscription_id:
                import stripe

                stripe.Subscription.modify(
                    user.stripe_subscription_id,
                    cancel_at_period_end=True,
                )

                user.subscription_status = "cancelled"
                user.subscription_type = "none"
                user.subscription_current_period_end = None
                user.save(update_fields=[
                    "subscription_status",
                    "subscription_type",
                    "subscription_current_period_end",
                ])

                # Notify user about Stripe cancellation
                try:
                    send_stripe_subscription_notification(
                        user=user,
                        event_type="CANCELLED",
                        subscription_details={
                            "stripe_subscription_id": user.stripe_subscription_id,
                        },
                    )
                except Exception:
                    logger.exception("Failed to send Stripe cancellation notification")

                return Response(
                    {"message": "Stripe subscription will cancel at period end"},
                    status=200,
                )

            # -------------------------------
            # GOOGLE
            # -------------------------------
            subscription = SubscriptionDetails.objects.filter(
                user=user,
                purchase_status="active",
            ).order_by("-expires_at").first()

            if subscription and subscription.receipt_data:
                cancel_google_subscription(
                    package_name="com.travion.app",
                    subscription_id=subscription.product_id,
                    purchase_token=subscription.receipt_data,
                )

                subscription.purchase_status = "cancelled"
                subscription.pending_complete = True
                subscription.updated_at = timezone.now()
                subscription.save(update_fields=[
                    "purchase_status",
                    "pending_complete",
                    "updated_at",
                ])

                user.subscription_status = "cancelled"
                user.save(update_fields=["subscription_status"])

                send_google_subscription_notification(
                    user=user,
                    event_type="SUBSCRIPTION_CANCELED",
                    subscription_details={
                        "subscription_id": subscription.product_id,
                        "status": "cancelled",
                    },
                )

                return Response(
                    {"message": "Google subscription cancelled"},
                    status=200,
                )

            # -------------------------------
            # APPLE (Manual)
            # -------------------------------
            send_apple_subscription_notification(
                user=user,
                event_type="CANCELLED",
                subscription_details={
                    "message": "Cancel via App Store",
                },
            )

            return Response(
                {"message": "Apple subscriptions must be cancelled from App Store"},
                status=400,
            )

        except Exception:
            logger.exception("CancelSubscription failed")
            return Response(
                {"message": "Failed to cancel subscription"},
                status=500,
            )

class VerifySubscription(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        logger.info(
            "VerifySubscription request received",
            extra={
                "user_id": user.id,
                "email": user.email,
                "payload": request.data,
            },
        )

        try:
            platform = request.data.get("platform")
            product_id = request.data.get("productId")
            purchase_id = request.data.get("purchaseId")
            receipt = request.data.get("receipt")

            if not all([platform, product_id, purchase_id, receipt]):
                logger.warning(
                    "Missing required fields",
                    extra={"user_id": user.id, "payload": request.data},
                )
                return Response(
                    {"message": "Missing required fields"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not isinstance(platform, str):
                logger.warning(
                    "Invalid platform type",
                    extra={"user_id": user.id, "platform": platform},
                )
                return Response(
                    {"message": "Invalid platform value"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            platform_lower = platform.lower()

            # ==========================================================
            # 🍎 APPLE STOREKIT 2 (ACTIVE ON VERIFY)
            # ==========================================================
            if platform_lower in ["ios", "apple"]:
                logger.info(
                    "Starting Apple subscription verification",
                    extra={
                        "user_id": user.id,
                        "product_id": product_id,
                    },
                )

                # 1️⃣ Decode Apple JWS (signedTransactionInfo)
                try:
                    data = verify_storekit2_receipt(receipt)
                except Exception:
                    logger.exception("Apple receipt verification failed")
                    return Response(
                        {"message": "Failed to verify Apple receipt"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                original_txn_id = data.get("originalTransactionId")
                transaction_id = data.get("transactionId")
                expires_ms = data.get("expiresDate")

                if not original_txn_id:
                    logger.warning(
                        "Missing originalTransactionId in Apple receipt",
                        extra={"data": data},
                    )
                    return Response(
                        {"message": "Invalid Apple transaction"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # 2️⃣ Parse expiry (UTC safe)
                expires_at = None
                if expires_ms:
                    expires_at = datetime.fromtimestamp(
                        int(expires_ms) / 1000,
                        tz=dt_timezone.utc,
                    )

                logger.info(
                    "Apple transaction verified",
                    extra={
                        "user_id": user.id,
                        "original_txn_id": original_txn_id,
                        "transaction_id": transaction_id,
                        "expires_at": expires_at.isoformat() if expires_at else None,
                    },
                )

                # 3️⃣ Create / update subscription (ACTIVE)
                subscription, created = SubscriptionDetails.objects.update_or_create(
                    purchase_id=original_txn_id,
                    defaults={
                        "user": user,
                        "product_id": product_id,
                        "purchase_status": "active",      # 🔥 ACTIVE
                        "pending_complete": True,
                        "receipt_data": receipt,
                        "expires_at": expires_at,
                        "raw_response": data,
                        "updated_at": timezone.now(),
                    }
                )

                logger.info(
                    "Apple subscription stored via verify API",
                    extra={
                        "subscription_id": subscription.id,
                        "crearow_created": created,
                        "purchase_status": "active",
                    },
                )

                # 4️⃣ Update USER immediately
                user.subscription_status = "active"
                user.subscription_current_period_end = expires_at

                pid = product_id.lower()
                if "premiums" in pid:
                    user.subscription_type = "pro"
                elif "standard" in pid:
                    user.subscription_type = "standard"
                else:
                    user.subscription_type = "none"

                user.save(update_fields=[
                    "subscription_type",
                    "subscription_status",
                    "subscription_current_period_end",
                ])

                logger.info(
                    "Apple user subscription activated via verify API",
                    extra={
                        "user_id": user.id,
                        "subscription_type": user.subscription_type,
                        "expires_at": expires_at.isoformat() if expires_at else None,
                    },
                )

                # Notify user on first purchase
                try:
                    if created and subscription.purchase_status == "active":
                        send_apple_subscription_notification(
                            user=user,
                            event_type="SUBSCRIBED",
                            subscription_details={
                                "subscription_id": subscription.id,
                                "product_id": product_id,
                                "expires_at": expires_at.isoformat() if expires_at else None,

                            },
                        )
                except Exception:
                    logger.exception("Failed to send Apple notification on verify API")

                return Response(
                    {
                        "message": "Apple purchase verified & activated",
                        "platform": "ios",
                        "purchase_status": "active",
                        "expires_at": expires_at,
                    },
                    status=status.HTTP_200_OK,
                )

            # ==========================================================
            # 🤖 ANDROID / GOOGLE IAP
            # ==========================================================
            elif platform_lower in ["android", "google"]:
                package_name = "com.travion.app"
                subscription_id = product_id
                purchase_token = receipt

                logger.info(
                    "Starting Google subscription verification",
                    extra={
                        "user_id": user.id,
                        "product_id": product_id,
                    },
                )

                try:
                    google_response, expires_at, purchase_status = verify_google_subscription(
                        package_name,
                        subscription_id,
                        purchase_token,
                    )
                except Exception:
                    logger.exception("Google subscription verification failed")
                    return Response(
                        {"message": "Failed to verify Google subscription"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if not expires_at:
                    return Response(
                        {"message": "Invalid Google subscription"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # ✅ ACCEPT GOOGLE STATUS DIRECTLY
                if purchase_status not in ["active", "expired", "cancelled"]:
                    logger.warning(
                        "Unhandled Google purchase status",
                        extra={
                            "user_id": user.id,
                            "purchase_status": purchase_status,
                        },
                    )

                subscription, created = SubscriptionDetails.objects.update_or_create(
                    purchase_id=purchase_token,   # 🔥 identity
                    defaults={
                        "user": user,
                        "product_id": product_id,
                        "purchase_status": purchase_status,   # 🔥 NO PENDING
                        "pending_complete": True,
                        "receipt_data": purchase_token,
                        "expires_at": expires_at,
                        "raw_response": google_response,
                    }
                )

                logger.info(
                    "Google subscription saved via verify API",
                    extra={
                        "subscription_id": subscription.id,
                        "row_created": created,   # ✅ SAFE
                        "purchase_status": purchase_status,
                    },
                )
                # 🔥 GOOGLE UPGRADE HANDLING (ONLY WHEN GOOGLE CONFIRMS)
                linked_token = google_response.get("linkedPurchaseToken")

                if purchase_status == "active" and linked_token:
                    logger.info(
                        "Google upgrade detected",
                        extra={
                            "user_id": user.id,
                            "old_purchase_token": linked_token,
                            "new_purchase_token": purchase_token,
                        },
                    )

                    expired_count = SubscriptionDetails.objects.filter(
                        purchase_id=linked_token
                    ).update(
                        purchase_status="expired",
                        updated_at=timezone.now(),
                    )

                    logger.info(
                        "Old Google subscription expired due to upgrade",
                        extra={
                            "user_id": user.id,
                            "expired_count": expired_count,
                        },
                    )


                # -----------------------------------
                # Update USER immediately
                # -----------------------------------
                user.subscription_status = purchase_status
                user.subscription_current_period_end = expires_at

                pid = product_id.lower()
                if purchase_status == "active":
                    if "premium" in pid:
                        user.subscription_type = "pro"
                    elif "standard" in pid:
                        user.subscription_type = "standard"
                else:
                    user.subscription_type = "none"

                user.save(update_fields=[
                    "subscription_type",
                    "subscription_status",
                    "subscription_current_period_end",
                ])

                # Notify user on first purchase
                try:
                    if created and subscription.purchase_status == "active":
                        send_google_subscription_notification(
                            user=user,
                            event_type="SUBSCRIPTION_PURCHASED",
                            subscription_details={
                                "subscription_id": subscription.id,
                                "product_id": product_id,
                                "expires_at": expires_at.isoformat() if expires_at else None,
                            },
                        )
                except Exception:
                    logger.exception("Failed to send Google notification on verify API")

                return Response(
                    {
                        "message": "Google subscription verified",
                        "platform": "android",
                        "purchase_status": purchase_status,
                        "expires_at": expires_at,
                    },
                    status=status.HTTP_200_OK,
                )


            logger.warning(
                "Unsupported platform received",
                extra={"user_id": user.id, "platform": platform},
            )

            return Response(
                {"message": "Unsupported platform"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception:
            logger.exception(
                "Unhandled error during subscription verification",
                extra={"user_id": user.id, "payload": request.data},
            )
            return Response(
                {"message": "Internal error while verifying subscription"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VerifyItineraryPayment(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from users.models import ItineraryPayment
        from payments.utils.google_product_verify import verify_google_one_time_product
        from django.utils import timezone as tz

        user = request.user
        itinerary_id = request.data.get("itinerary_id")
        purchase_id = request.data.get("purchase_id")
        product_id = request.data.get("product_id")
        role = request.data.get("role", "seeker")

        if not all([itinerary_id, purchase_id, product_id]):
            return Response(
                {"message": "itinerary_id, purchase_id and product_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        package_name = getattr(settings, "GOOGLE_PACKAGE_NAME", "")
        raw_response, google_status = verify_google_one_time_product(
            package_name, product_id, purchase_id
        )

        if google_status != "paid":
            logger.warning(
                "Itinerary Google payment verification failed",
                extra={"user_id": user.id, "itinerary_id": itinerary_id},
            )
            return Response(
                {"message": "Payment could not be verified with Google"},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        payment, _ = ItineraryPayment.objects.update_or_create(
            itinerary_id=itinerary_id,
            user=user,
            defaults={
                "status": "paid",
                "platform": "google",
                "purchase_id": purchase_id,
                "paid_at": tz.now(),
                "role": role,
            },
        )

        logger.info(
            "Itinerary payment verified",
            extra={"user_id": user.id, "itinerary_id": itinerary_id, "payment_id": payment.id},
        )

        return Response({
            "status": "paid",
            "payment_id": payment.id,
            "itinerary_id": itinerary_id,
        })


class AppleSubscriptionWebhook(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        logger.info("🍎 Apple webhook hit")
        # -----------------------------------
        # 0️⃣ Read signedPayload safely
        # -----------------------------------
        signed_payload = request.data.get("signedPayload")

        if not signed_payload:
            logger.warning(
                "Apple webhook missing signedPayload",
                extra={"payload": request.data},
            )
            return Response({"status": "invalid"}, status=200)

        logger.debug(
            "Apple signedPayload received",
            extra={"payload_length": len(signed_payload)},
        )

        # -----------------------------------
        # 1️⃣ Decode outer notification (JWT)
        # -----------------------------------
        try:
            notification = verify_storekit2_receipt(signed_payload)
        except Exception as e:
            logger.exception("Failed to decode Apple signedPayload")
            return Response({"status": "invalid signature"}, status=200)

        notification_type = notification.get("notificationType")
        signed_tx = notification.get("data", {}).get("signedTransactionInfo")

        logger.info(
            "Apple notification decoded",
            extra={
                "notification_type": notification_type,
                "has_signed_tx": bool(signed_tx),
            },
        )

        if not notification_type or not signed_tx:
            logger.warning(
                "Apple webhook missing notificationType or signedTransactionInfo",
                extra={"notification": notification},
            )
            return Response({"status": "invalid"}, status=200)

        # -----------------------------------
        # 2️⃣ Decode transaction info (JWT)
        # -----------------------------------
        try:
            transaction = verify_storekit2_receipt(signed_tx)
        except Exception:
            logger.exception("Failed to decode signedTransactionInfo")
            return Response({"status": "invalid transaction"}, status=200)

        original_txn_id = transaction.get("originalTransactionId")
        expires_ms = transaction.get("expiresDate")

        if not original_txn_id:
            logger.warning(
                "Apple transaction missing originalTransactionId",
                extra={"transaction": transaction},
            )
            return Response({"status": "missing transaction id"}, status=200)

        # -----------------------------------
        # 3️⃣ UTC-safe expiry parsing
        # -----------------------------------
        expires_at = None
        if expires_ms:
            try:
                expires_at = datetime.fromtimestamp(
                    int(expires_ms) / 1000,
                    tz=dt_timezone.utc,   # 🔥 Explicit UTC
                )
            except Exception:
                logger.exception(
                    "Failed to parse expiresDate",
                    extra={"expires_ms": expires_ms},
                )

        logger.info(
            "Apple transaction extracted",
            extra={
                "original_txn_id": original_txn_id,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )

        # -----------------------------------
        # 4️⃣ Map Apple → internal status
        # -----------------------------------
        STATUS_MAP = {
            "SUBSCRIBED": "active",
            "DID_RENEW": "active",
            "DID_CHANGE_RENEWAL_STATUS": "active",
            "DID_CHANGE_RENEWAL_PREF": "active",
            "DID_FAIL_TO_RENEW": "past_due",
            "EXPIRED": "expired",
            "REFUND": "refunded",
            "REVOKE": "refunded",
        }

        status = STATUS_MAP.get(notification_type, "unknown")

        logger.info(
            "Apple notification mapped",
            extra={
                "notification_type": notification_type,
                "mapped_status": status,
            },
        )

        # -----------------------------------
        # 5️⃣ Fetch & update subscription
        # -----------------------------------
        sub = SubscriptionDetails.objects.filter(
            purchase_id=original_txn_id
        ).first()

        if not sub:
            logger.warning(
                "Subscription not found for Apple webhook",
                extra={"original_txn_id": original_txn_id},
            )
            return Response({"status": "not found"}, status=200)

        old_status = sub.purchase_status

        sub.purchase_status = status
        sub.expires_at = expires_at
        sub.raw_response = notification
        sub.updated_at = datetime.now(dt_timezone.utc)
        sub.save(
            update_fields=[
                "purchase_status",
                "expires_at",
                "raw_response",
                "updated_at",
            ]
        )

        logger.info(
            "Subscription updated",
            extra={
                "subscription_id": sub.id,
                "old_status": old_status,
                "new_status": status,
            },
        )

        # -----------------------------------
        # 6️⃣ Update user entitlements
        # -----------------------------------
        user = sub.user

        user.subscription_status = status
        user.subscription_current_period_end = (
            expires_at if status == "active" else None
        )

        if status in ["expired", "refunded"]:
            user.subscription_type = "none"

        user.save(
            update_fields=[
                "subscription_type",
                "subscription_status",
                "subscription_current_period_end",
            ]
        )

        logger.info(
            "User subscription updated",
            extra={
                "user_id": user.id,
                "status": status,
                "expires_at": (
                    expires_at.isoformat() if expires_at else None
                ),
            },
        )

        # Notify user when status changes
        try:
            if old_status != sub.purchase_status:
                send_apple_subscription_notification(
                    user=user,
                    event_type=notification_type,
                    subscription_details={
                        "subscription_id": sub.id,
                        "status": status,
                        "expires_at": expires_at,
                    },
                )
        except Exception:
            logger.exception("Failed to send Apple webhook notification")

        return Response({"status": "ok"}, status=200)

@method_decorator(csrf_exempt, name="dispatch")
class GoogleSubscriptionWebhook(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        logger.info("🤖 Google RTDN webhook hit")

        try:
            data = request.data
            message = data.get("message")

            if not message or "data" not in message:
                logger.warning("Invalid Google webhook payload")
                return Response({"status": "invalid"}, status=200)

            # -------------------------------------------------
            # Decode Pub/Sub message
            # -------------------------------------------------
            try:
                decoded = json.loads(
                    base64.b64decode(message["data"]).decode("utf-8")
                )
            except Exception:
                logger.exception("Failed to decode Google RTDN payload")
                return Response({"status": "invalid"}, status=200)

            logger.info(
                "Google RTDN payload decoded",
                extra={"payload": decoded},
            )

            # Test ping
            if "testNotification" in decoded:
                logger.info("Google RTDN testNotification received")
                return Response({"status": "ok"}, status=200)

            sub = decoded.get("subscriptionNotification", {})
            notification_type = sub.get("notificationType")
            purchase_token = sub.get("purchaseToken")
            subscription_id = sub.get("subscriptionId")
            linked_token = sub.get("linkedPurchaseToken")

            if not all([notification_type, purchase_token, subscription_id]):
                logger.warning(
                    "Missing required fields in Google RTDN",
                    extra={"subscriptionNotification": sub},
                )
                return Response({"status": "invalid"}, status=200)

            logger.info(
                "Google RTDN event received",
                extra={
                    "notification_type": notification_type,
                    "subscription_id": subscription_id,
                    "purchase_token": purchase_token,
                    "has_linked_token": bool(linked_token),
                },
            )

            # -------------------------------------------------
            # Map Google notificationType → internal status
            # -------------------------------------------------
            STATUS_MAP = {
                1: "active",       # PURCHASED
                2: "active",       # RENEWED
                3: "cancelled",
                4: "active",
                5: "past_due",
                6: "active",
                7: "active",
                8: "active",
                9: "active",
                12: "refunded",
                13: "expired",
            }

            purchase_status = STATUS_MAP.get(notification_type, "unknown")

            logger.info(
                "Google RTDN mapped status",
                extra={
                    "notification_type": notification_type,
                    "mapped_status": purchase_status,
                },
            )

            # -------------------------------------------------
            # Find subscription row
            # -------------------------------------------------
            subscription = SubscriptionDetails.objects.filter(
                purchase_id=purchase_token
            ).first()

            if not subscription:
                logger.warning(
                    "Subscription not found for Google RTDN",
                    extra={"purchase_token": purchase_token},
                )
                return Response({"status": "not_found"}, status=200)

            old_status = subscription.purchase_status

            # -------------------------------------------------
            # Ignore stale events (safety guard)
            # -------------------------------------------------
            if old_status == "expired" and purchase_status == "active":
                logger.warning(
                    "Ignoring stale Google RTDN event",
                    extra={
                        "subscription_id": subscription.id,
                        "old_status": old_status,
                        "incoming_status": purchase_status,
                    },
                )
                return Response({"status": "ignored"}, status=200)

            # -------------------------------------------------
            # Update subscription row ONLY
            # -------------------------------------------------
            subscription.product_id = subscription_id
            subscription.purchase_status = purchase_status
            subscription.pending_complete = purchase_status != "pending"
            subscription.updated_at = timezone.now()
            subscription.save(
                update_fields=[
                    "product_id",
                    "purchase_status",
                    "pending_complete",
                    "updated_at",
                ]
            )

            logger.info(
                "Google subscription updated from RTDN",
                extra={
                    "subscription_id": subscription.id,
                    "old_status": old_status,
                    "new_status": purchase_status,
                },
            )

            # -------------------------------------------------
            # 🔥 UPGRADE HANDLING (expire old token)
            # -------------------------------------------------
            if linked_token:
                expired_count = SubscriptionDetails.objects.filter(
                    purchase_id=linked_token
                ).exclude(
                    id=subscription.id
                ).update(
                    purchase_status="expired",
                    updated_at=timezone.now(),
                )

                logger.info(
                    "Google upgrade handled",
                    extra={
                        "user_id": subscription.user_id,
                        "linked_purchase_token": linked_token,
                        "expired_count": expired_count,
                    },
                )
            # -------------------------------------------------
            # 🔄 FINAL USER ENTITLEMENT SYNC (INLINE FIX)
            # -------------------------------------------------
            active_sub = (
                SubscriptionDetails.objects
                .filter(
                    user=subscription.user,
                    purchase_status="active"
                )
                .order_by("-expires_at")
                .first()
            )

            user = subscription.user

            if not active_sub:
                # ❌ No active plans left
                user.subscription_type = "none"
                user.subscription_status = "expired"
                user.subscription_current_period_end = None

                logger.info(
                    "User has no active Google subscriptions",
                    extra={"user_id": user.id},
                )

            else:
                # ✅ Pick highest / latest active plan
                pid = active_sub.product_id.lower()

                if "premium" in pid:
                    user.subscription_type = "pro"
                elif "standard" in pid:
                    user.subscription_type = "standard"
                else:
                    user.subscription_type = "none"

                user.subscription_status = "active"
                user.subscription_current_period_end = active_sub.expires_at

                logger.info(
                    "User subscription recalculated from DB",
                    extra={
                        "user_id": user.id,
                        "final_plan": user.subscription_type,
                        "expires_at": (
                            active_sub.expires_at.isoformat()
                            if active_sub.expires_at else None
                        ),
                    },
                )

            user.save(
                update_fields=[
                    "subscription_type",
                    "subscription_status",
                    "subscription_current_period_end",
                ]
            )

            # -------------------------------------------------
            # Send notification ONLY if status changed
            # -------------------------------------------------
            STATUS_NAME_MAP = {
                1: "SUBSCRIPTION_PURCHASED",
                2: "SUBSCRIPTION_RENEWED",
                3: "SUBSCRIPTION_CANCELED",
                4: "SUBSCRIPTION_RENEWED",
                5: "SUBSCRIPTION_ON_HOLD",
                6: "SUBSCRIPTION_RESTARTED",
                7: "SUBSCRIPTION_RESTARTED",
                8: "SUBSCRIPTION_RESTARTED",
                9: "SUBSCRIPTION_RENEWED",
                12: "REFUND",
                13: "EXPIRED",
            }

            event_name = STATUS_NAME_MAP.get(
                notification_type,
                f"NOTIF_{notification_type}",
            )

            if old_status != purchase_status:
                try:
                    send_google_subscription_notification(
                        user=subscription.user,
                        event_type=event_name,
                        subscription_details={
                            "subscription_id": subscription.id,
                            "product_id": subscription.product_id,
                            "status": purchase_status,
                            "expires_at": (
                                subscription.expires_at.isoformat()
                                if subscription.expires_at else None
                            ),
                        },
                    )

                    logger.info(
                        "Google webhook notification sent",
                        extra={
                            "user_id": subscription.user_id,
                            "event_type": event_name,
                        },
                    )
                except Exception:
                    logger.exception(
                        "Failed to send Google webhook notification",
                        extra={"subscription_id": subscription.id},
                    )

            return Response({"status": "ok"}, status=200)

        except Exception:
            logger.exception("Unhandled Google RTDN webhook error")
            return Response({"status": "error"}, status=200)
