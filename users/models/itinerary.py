from django.db import models
from django.utils import timezone
from datetime import datetime
from .user import User


class Itinerary(models.Model):
    """
    Model to store user travel itineraries
    """
    TRAVEL_TYPE_CHOICES = [
        ('one_way', 'One Way'),
        ('round_trip', 'Round Trip'),
        ('multi_city', 'Multi City'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='itineraries')
    title = models.CharField(max_length=200, help_text="Trip title or description")
    travel_type = models.CharField(max_length=20, choices=TRAVEL_TYPE_CHOICES, default='one_way')
    is_available = models.BooleanField(default=True, help_text="Available to provide services")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Itinerary'
        verbose_name_plural = 'Itineraries'
    
    def __str__(self):
        return f"{self.user.full_name} - {self.title}"
    
    @property
    def total_segments(self):
        return self.segments.count()
    
    @property
    def departure_date(self):
        """Get the earliest departure date from all segments"""
        first_segment = self.segments.order_by('departure_date_from').first()
        return first_segment.departure_date_from if first_segment else None
    
    @property
    def arrival_date(self):
        """Get the latest departure date to from all segments"""
        last_segment = self.segments.order_by('-departure_date_to').first()
        return last_segment.departure_date_to if last_segment else None


class TravelSegment(models.Model):
    """
    Model to store individual travel segments within an itinerary
    """
    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='segments')
    
    # Airport codes (IATA format)
    from_airport = models.CharField(max_length=3, help_text="IATA airport code (e.g., SFO)")
    to_airport = models.CharField(max_length=3, help_text="IATA airport code (e.g., LAX)")
    
    departure_date_from = models.DateField(default='2025-01-01', help_text="Earliest departure date")
    departure_date_to = models.DateField(default='2025-01-01', help_text="Latest departure date")
    departure_time_from = models.TimeField(null=True, blank=True, help_text="Earliest departure time")
    departure_time_to = models.TimeField(null=True, blank=True, help_text="Latest departure time")
    
    # Optional flight information
    airline = models.CharField(max_length=100, blank=True, null=True)
    flight_number = models.CharField(max_length=20, blank=True, null=True)
    
    # Segment order within the itinerary
    segment_order = models.PositiveIntegerField(default=1)
    
    layovers = models.JSONField(
        default=list,
        blank=True,
        help_text="List of layover airport codes"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['segment_order', 'departure_date_from', 'departure_time_from']
        unique_together = ['itinerary', 'segment_order']
    
    def __str__(self):
        return f"{self.from_airport} → {self.to_airport} ({self.departure_date_from} to {self.departure_date_to})"
    
    @property
    def route(self):
        return f"{self.from_airport} → {self.to_airport}"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Validate airport codes (should be 3 uppercase letters)
        if self.from_airport and len(self.from_airport) != 3:
            raise ValidationError({'from_airport': 'Airport code must be 3 characters'})
        if self.to_airport and len(self.to_airport) != 3:
            raise ValidationError({'to_airport': 'Airport code must be 3 characters'})
        
        # Validate date ranges
        if self.departure_date_from and self.departure_date_to:
            if self.departure_date_from > self.departure_date_to:
                raise ValidationError('Departure date from cannot be after departure date to')
        
        # Validate time ranges
        if self.departure_time_from and self.departure_time_to:
            if self.departure_time_from > self.departure_time_to:
                raise ValidationError('Departure time from cannot be after departure time to')

        # Validate layovers structure (list of airport codes)
        if self.layovers is None:
            self.layovers = []
        elif not isinstance(self.layovers, list):
            raise ValidationError({'layovers': 'Layovers must be a list'})
        else:
            cleaned_layovers = []
            for idx, layover in enumerate(self.layovers):
                if isinstance(layover, dict):
                    airport = layover.get('airport')
                else:
                    airport = layover

                if not airport:
                    raise ValidationError({'layovers': f'Layover #{idx + 1} requires an airport code'})

                airport_code = str(airport).strip().upper()
                if len(airport_code) != 3 or not airport_code.isalpha():
                    raise ValidationError({'layovers': f'Layover #{idx + 1} airport must be a 3-letter code'})

                cleaned_layovers.append(airport_code)

            self.layovers = cleaned_layovers
    
    def save(self, *args, **kwargs):
        # Convert airport codes to uppercase
        if self.from_airport:
            self.from_airport = self.from_airport.upper()
        if self.to_airport:
            self.to_airport = self.to_airport.upper()
        
        self.clean()
        super().save(*args, **kwargs)


class SeekerRequest(models.Model):
    """
    Model to store seeker travel requests/preferences
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='seeker_requests')
    title = models.CharField(max_length=200, help_text="Request title or description")
    is_active = models.BooleanField(default=True, help_text="Request is active and looking for matches")
    
    from_airport = models.CharField(max_length=3, default='NYC', help_text="IATA airport code (e.g., NYC)")
    to_airport = models.CharField(max_length=3, default='LAX', help_text="IATA airport code (e.g., LAX)")
    departure_date_from = models.DateField(default='2025-01-01', help_text="Earliest departure date")
    departure_date_to = models.DateField(default='2025-01-01', help_text="Latest departure date")
    departure_time_from = models.TimeField(null=True, blank=True, help_text="Earliest departure time")
    departure_time_to = models.TimeField(null=True, blank=True, help_text="Latest departure time")
    
    expires_at = models.DateTimeField(help_text="When this request expires")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Seeker Request'
        verbose_name_plural = 'Seeker Requests'
    
    def __str__(self):
        return f"{self.user.full_name} - {self.title}"
    
    @property
    def is_expired(self):
        """Check if the request has expired"""
        return timezone.now() > self.expires_at
    
    def set_automatic_expiration(self):
        """Set expiration date automatically based on travel date"""
        from datetime import datetime, timedelta
        # Expire 1 day after the latest departure date
        self.expires_at = timezone.make_aware(
            datetime.combine(self.departure_date_to, datetime.min.time())
        ) + timedelta(days=1)
    
    @property
    def total_segments(self):
        return self.segments.count()
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Validate airport codes (should be 3 uppercase letters)
        if self.from_airport and len(self.from_airport) != 3:
            raise ValidationError({'from_airport': 'Airport code must be 3 characters'})
        if self.to_airport and len(self.to_airport) != 3:
            raise ValidationError({'to_airport': 'Airport code must be 3 characters'})
        
        # Validate date ranges
        if self.departure_date_from and self.departure_date_to:
            if self.departure_date_from > self.departure_date_to:
                raise ValidationError('Departure date from cannot be after departure date to')
        
        # Validate time ranges
        if self.departure_time_from and self.departure_time_to:
            if self.departure_time_from > self.departure_time_to:
                raise ValidationError('Departure time from cannot be after departure time to')
    
    def save(self, *args, **kwargs):
        # Convert airport codes to uppercase
        if self.from_airport:
            self.from_airport = self.from_airport.upper()
        if self.to_airport:
            self.to_airport = self.to_airport.upper()
        
        self.clean()
        super().save(*args, **kwargs)

