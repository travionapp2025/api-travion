from django.db import models
from django.utils import timezone
from .user import User


class BlockedUser(models.Model):
    """
    Model to track blocked users between two users.
    When User A blocks User B, User B cannot send messages to User A or view their profile.
    """
    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocked_users')
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocked_by_users')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')
        verbose_name = 'Blocked User'
        verbose_name_plural = 'Blocked Users'
        indexes = [
            models.Index(fields=['blocker', 'blocked'], name='blocker_blocked_idx'),
            models.Index(fields=['blocked', 'blocker'], name='blocked_blocker_idx'),
        ]

    def __str__(self):
        return f"{self.blocker.email} blocked {self.blocked.email}"

    @classmethod
    def is_blocked(cls, user_a, user_b):
        """
        Check if user_a has blocked user_b or vice versa
        """
        return cls.objects.filter(
            models.Q(blocker=user_a, blocked=user_b) | models.Q(blocker=user_b, blocked=user_a)
        ).exists()


class ReportedUser(models.Model):
    """
    Model to track user reports.
    When a user is reported, they get a temporary 24-hour messaging restriction.
    """

    REPORT_REASONS = [
        ('abuse', 'Abuse'),
        ('spam', 'Spam'),
        ('harassment', 'Harassment'),
        ('fake_profile', 'Fake Profile'),
        ('other', 'Other'),
    ]

    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports_made')
    reported = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports_received')
    reason = models.CharField(max_length=20, choices=REPORT_REASONS)
    additional_details = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(help_text="When the 24-hour restriction expires")

    class Meta:
        verbose_name = 'Reported User'
        verbose_name_plural = 'Reported Users'
        indexes = [
            models.Index(fields=['reporter', 'reported'], name='reporter_reported_idx'),
            models.Index(fields=['reported', 'created_at'], name='reported_created_idx'),
            models.Index(fields=['expires_at'], name='expires_at_idx'),
        ]

    def __str__(self):
        return f"{self.reporter.email} reported {self.reported.email} for {self.reason}"

    def save(self, *args, **kwargs):
        # Set expiration to 24 hours from creation if not set
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        super().save(*args, **kwargs)

    @classmethod
    def is_recently_reported(cls, reporter, reported):
        """
        Check if reporter has recently reported this user within 24 hours
        """
        cutoff_time = timezone.now() - timezone.timedelta(hours=24)
        return cls.objects.filter(
            reporter=reporter,
            reported=reported,
            created_at__gte=cutoff_time
        ).exists()

    @classmethod
    def has_active_restriction(cls, user_a, user_b):
        """
        Check if there's an active 24-hour messaging restriction between two users
        """
        now = timezone.now()
        return cls.objects.filter(
            models.Q(reporter=user_a, reported=user_b) | models.Q(reporter=user_b, reported=user_a),
            expires_at__gt=now
        ).exists()