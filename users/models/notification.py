from django.db import models
from django.utils import timezone
from .user import User


class DeviceToken(models.Model):
    """
    Model to store Firebase device tokens for push notifications
    """
    DEVICE_TYPE_CHOICES = [
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('web', 'Web'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='device_tokens')
    token = models.CharField(max_length=255, help_text="Firebase FCM token")
    device_type = models.CharField(max_length=10, choices=DEVICE_TYPE_CHOICES, default='android')
    is_active = models.BooleanField(default=True, help_text="Whether this token is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Device Token'
        verbose_name_plural = 'Device Tokens'
        unique_together = ('user', 'token')  # Same user can't have duplicate tokens, but different users can have same token
    
    def __str__(self):
        return f"{self.user.email} - {self.device_type} ({self.token[:20]}...)"


class Notification(models.Model):
    """
    Model to store notification records
    """
    NOTIFICATION_TYPE_CHOICES = [
        ('chat_message', 'Chat Message'),
        ('chat_request', 'Chat Request'),
        ('itinerary_match', 'Itinerary Match'),
        ('profile_view', 'Profile View'),
        ('system', 'System'),
        ('reminder', 'Reminder'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True, help_text="Additional data for the notification")
    
    # Sender information (for chat messages, etc.)
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    
    # Status tracking
    is_read = models.BooleanField(default=False)
    is_sent = models.BooleanField(default=False, help_text="Whether push notification was sent")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
    
    def __str__(self):
        return f"{self.user.email} - {self.notification_type}: {self.title}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    def mark_as_sent(self):
        """Mark notification as sent"""
        if not self.is_sent:
            self.is_sent = True
            self.sent_at = timezone.now()
            self.save(update_fields=['is_sent', 'sent_at'])


class NotificationPreference(models.Model):
    """
    Model to store user notification preferences
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preferences')
    
    # Push notification settings
    push_notifications_enabled = models.BooleanField(default=True)
    chat_notifications_enabled = models.BooleanField(default=True)
    itinerary_match_notifications_enabled = models.BooleanField(default=True)
    system_notifications_enabled = models.BooleanField(default=True)
    
    # Quiet hours
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    
    # Frequency settings
    digest_frequency = models.CharField(
        max_length=10,
        choices=[
            ('immediate', 'Immediate'),
            ('hourly', 'Hourly'),
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
        ],
        default='immediate'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Notification Preference'
        verbose_name_plural = 'Notification Preferences'
    
    def __str__(self):
        return f"Notification Preferences for {self.user.email}"
