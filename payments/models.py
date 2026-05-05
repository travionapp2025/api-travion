from django.db import models
from django.conf import settings
from users.models import User

class Subscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    stripe_subscription_id = models.CharField(max_length=255)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.user.email
    

class SubscriptionDetails(models.Model):
    PURCHASE_STATUS_CHOICES = (
        ('active', 'Active'),
        ('pending', 'Pending'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
        ('refunded', 'Refunded'),
        ('failed', 'Failed'),
    )

    user = models.ForeignKey( User, on_delete=models.CASCADE, related_name="apple_subscriptions")
    product_id = models.CharField(max_length=255)
    purchase_id = models.CharField(max_length=255, unique=True)
    receipt_data = models.TextField()
    purchase_status = models.CharField(max_length=20, choices=PURCHASE_STATUS_CHOICES)
    pending_complete = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    raw_response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} - {self.product_id} - {self.purchase_status}"
