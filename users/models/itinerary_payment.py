from django.db import models
from .user import User
from .itinerary import Itinerary


class ItineraryPayment(models.Model):
    """
    Tracks payment status for every user (creator or seeker) on a given itinerary.

    Creator  – one record per itinerary; conversation is null because the creator's
               obligation is to the itinerary itself, not to any single seeker chat.

    Seeker   – one record per itinerary; conversation is set to the specific chat
               that was opened so we can trace back the exact connection.
    """

    ROLE_CHOICES = [
        ('creator', 'Creator'),
        ('seeker', 'Seeker'),
    ]

    STATUS_CHOICES = [
        ('free', 'Free'),        # no payment required (first trip / first seek)
        ('paid', 'Paid'),        # payment confirmed
        ('pending', 'Pending'),  # initiated but not yet confirmed
        ('unpaid', 'Unpaid'),    # payment required but not yet made
    ]

    PLATFORM_CHOICES = [
        ('apple', 'Apple'),
        ('google', 'Google'),
    ]

    itinerary = models.ForeignKey(
        Itinerary,
        on_delete=models.CASCADE,
        related_name='itinerary_payments',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='itinerary_payments',
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    # Null for creator records; set for seeker records
    conversation = models.ForeignKey(
        'users.Conversation',
        on_delete=models.SET_NULL,
        related_name='payments',
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='unpaid')
    platform = models.CharField(max_length=10, choices=PLATFORM_CHOICES, null=True, blank=True)
    purchase_id = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="IAP transactionId (Apple) or purchaseToken (Google)",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One payment record per user per itinerary (creator once, each seeker once)
        unique_together = [['itinerary', 'user']]
        ordering = ['-created_at']
        verbose_name = 'Itinerary Payment'
        verbose_name_plural = 'Itinerary Payments'
        indexes = [
            models.Index(fields=['itinerary', 'role', 'status'], name='itpay_itin_role_status_idx'),
            models.Index(fields=['user', 'status'], name='itpay_user_status_idx'),
            models.Index(fields=['itinerary', 'status'], name='itpay_itin_status_idx'),
        ]

    def __str__(self):
        return f"{self.role.title()} [{self.status}] — user {self.user_id} on itinerary {self.itinerary_id}"

    @property
    def is_settled(self):
        return self.status in ('free', 'paid')
