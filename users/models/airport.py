from django.db import models


class Airport(models.Model):
    """
    Airport model to store airport information from the CSV data
    """
    TYPE_CHOICES = [
        ('small_airport', 'Small Airport'),
        ('medium_airport', 'Medium Airport'),
        ('large_airport', 'Large Airport'),
        ('heliport', 'Heliport'),
        ('seaplane_base', 'Seaplane Base'),
        ('balloonport', 'Balloonport'),
        ('closed', 'Closed'),
    ]
    
    CONTINENT_CHOICES = [
        ('AF', 'Africa'),
        ('AN', 'Antarctica'),
        ('AS', 'Asia'),
        ('EU', 'Europe'),
        ('NA', 'North America'),
        ('OC', 'Oceania'),
        ('SA', 'South America'),
    ]
    
    # Primary fields
    ident = models.CharField(max_length=10, unique=True, db_index=True)  # Airport identifier
    iata_code = models.CharField(max_length=3, unique=True, db_index=True, blank=True, null=True)
    icao_code = models.CharField(max_length=4, blank=True, null=True, db_index=True)
    name = models.CharField(max_length=255)
    
    latitude_deg = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude_deg = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    elevation_ft = models.IntegerField(null=True, blank=True)
    
    # Geographic information
    continent = models.CharField(max_length=2, choices=CONTINENT_CHOICES, blank=True)
    iso_country = models.CharField(max_length=2, blank=True)  
    iso_region = models.CharField(max_length=10, blank=True)  
    municipality = models.CharField(max_length=255, blank=True)  
    
    # Airport details
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, blank=True)
    scheduled_service = models.CharField(max_length=3, blank=True) 
    gps_code = models.CharField(max_length=4, blank=True)
    local_code = models.CharField(max_length=10, blank=True)
    
    # Links
    home_link = models.URLField(blank=True, null=True)
    wikipedia_link = models.URLField(blank=True, null=True)
    keywords = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'airports'
        verbose_name = 'Airport'
        verbose_name_plural = 'Airports'
        indexes = [
            models.Index(fields=['iata_code']),
            models.Index(fields=['icao_code']),
            models.Index(fields=['ident']),
            models.Index(fields=['iso_country']),
            models.Index(fields=['continent']),
            models.Index(fields=['type']),
        ]
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.iata_code})"
    
    @property
    def full_location(self):
        """Return formatted location string"""
        parts = []
        if self.municipality:
            parts.append(self.municipality)
        if self.iso_country:
            parts.append(self.iso_country)
        return ', '.join(parts) if parts else ''
    
    @property
    def coordinates(self):
        """Return coordinates as a tuple"""
        if self.latitude_deg and self.longitude_deg:
            return (float(self.latitude_deg), float(self.longitude_deg))
        return None
