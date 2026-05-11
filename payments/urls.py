from django.urls import path
from .views import (
    CreateCheckoutSessionView,
    PaymentSuccessView,
    PaymentCancelView,
    SubscriptionStatusView,
    CancelSubscriptionView,
    VerifySubscription,
    VerifyItineraryPayment,
    AppleSubscriptionWebhook,
    GoogleSubscriptionWebhook,
)
from .webhooks import stripe_webhook

app_name = 'payments'

urlpatterns = [
    # API endpoints
    path('create-checkout-session/', CreateCheckoutSessionView.as_view(), name='create_checkout_session'),
    path('subscription-status/', SubscriptionStatusView.as_view(), name='subscription_status'),
    path('cancel-subscription/', CancelSubscriptionView.as_view(), name='cancel_subscription'),

    # Itinerary one-time payment verification
    path('itinerary/verify/', VerifyItineraryPayment.as_view(), name='itinerary_payment_verify'),

    # Webhook
    path('webhook/', stripe_webhook, name='stripe_webhook'),

    # Payment pages
    path('success/', PaymentSuccessView.as_view(), name='payment_success'),
    path('cancel/', PaymentCancelView.as_view(), name='payment_cancel'),

    path('subscription-verify/', VerifySubscription.as_view(), name="subscription_verify"),
    path("subscription/apple/webhook/", AppleSubscriptionWebhook.as_view(), name="apple_webhook"),
    path("subscription/google/webhook/", GoogleSubscriptionWebhook.as_view(), name="google_webhook"),
]

