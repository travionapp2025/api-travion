from django.db import models
from django.utils import timezone
from .user import User
from .itinerary import Itinerary, SeekerRequest, TravelSegment


class Match(models.Model):
    """
    Model to store matches between providers and seekers
    Supports: provider-seeker, provider-provider, seeker-seeker matches
    """
    MATCH_TYPE_CHOICES = [
        ('provider_seeker', 'Provider-Seeker'),
        ('provider_provider', 'Provider-Provider'),
        ('seeker_seeker', 'Seeker-Seeker'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]
    
    # Match type
    match_type = models.CharField(max_length=20, choices=MATCH_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    match_quality = models.CharField(
        max_length=10, 
        choices=[('exact', 'Exact Match'), ('partial', 'Partial Match')],
        default='exact',
        help_text="Whether this is an exact match (routes, dates, times all match) or partial match (only routes match)"
    )
    
    provider_itinerary = models.ForeignKey(
        Itinerary, 
        on_delete=models.CASCADE, 
        related_name='provider_matches',
        null=True, 
        blank=True,
        help_text="Provider's itinerary for provider-seeker or provider-provider matches"
    )
    provider_segment = models.ForeignKey(
        TravelSegment,
        on_delete=models.CASCADE,
        related_name='provider_segment_matches',
        null=True,
        blank=True,
        help_text="Provider's travel segment that matched"
    )
    
    seeker_request = models.ForeignKey(
        SeekerRequest,
        on_delete=models.CASCADE,
        related_name='seeker_request_matches',
        null=True,
        blank=True,
        help_text="Seeker request for seeker-seeker or provider-seeker matches"
    )
    
    matched_provider_itinerary = models.ForeignKey(
        Itinerary,
        on_delete=models.CASCADE,
        related_name='matched_provider_matches',
        null=True,
        blank=True,
        help_text="Other provider's itinerary for provider-provider matches"
    )
    matched_provider_segment = models.ForeignKey(
        TravelSegment,
        on_delete=models.CASCADE,
        related_name='matched_provider_segment_matches',
        null=True,
        blank=True,
        help_text="Other provider's travel segment for provider-provider matches"
    )
    
    # For seeker-seeker matches
    matched_seeker_request = models.ForeignKey(
        SeekerRequest,
        on_delete=models.CASCADE,
        related_name='matched_seeker_request_matches',
        null=True,
        blank=True,
        help_text="Other seeker's request for seeker-seeker matches"
    )
    
    # Users involved in the match
    user1 = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='matches_as_user1',
        help_text="First user in the match"
    )
    user2 = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='matches_as_user2',
        help_text="Second user in the match"
    )
    
    # Route information (cached for quick access)
    route = models.CharField(max_length=50, help_text="Route string like 'NYC → LAX'")
    departure_date_from = models.DateField(help_text="Earliest departure date")
    departure_date_to = models.DateField(help_text="Latest departure date")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(help_text="When this match expires")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user1', 'status', 'match_type']),
            models.Index(fields=['user2', 'status', 'match_type']),
            models.Index(fields=['provider_itinerary', 'status']),
            models.Index(fields=['seeker_request', 'status']),
            models.Index(fields=['status', 'expires_at']),
        ]
        verbose_name = 'Match'
        verbose_name_plural = 'Matches'
    
    def __str__(self):
        return f"Match({self.match_type}) - {self.user1.email} & {self.user2.email} - {self.route}"
    
    @property
    def is_expired(self):
        """Check if the match has expired"""
        return timezone.now() > self.expires_at
    
    def mark_expired(self):
        """Mark match as expired"""
        self.status = 'expired'
        self.save(update_fields=['status'])
    
    def save(self, *args, **kwargs):
        if self.user1_id and self.user2_id and self.user1_id > self.user2_id:
            self.user1, self.user2 = self.user2, self.user1
        
        if not self.expires_at or self.expires_at <= timezone.now():
            from datetime import timedelta
            self.expires_at = timezone.now() + timedelta(days=30)
        
        if self.is_expired and self.status == 'active' and self.pk:
            self.status = 'expired'
        
        super().save(*args, **kwargs)

