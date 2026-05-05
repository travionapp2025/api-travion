from django.db import models
from django.utils import timezone
from datetime import timedelta
import random
import string


class EmailOTP(models.Model):
    """
    Model to store email OTP codes for password reset
    """
    email = models.EmailField()
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)  
    
    class Meta:
        db_table = 'email_otps'
        verbose_name = 'Email OTP'
        verbose_name_plural = 'Email OTPs'
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.otp_code:
            self.otp_code = self.generate_otp()
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_otp():
        """Generate a 6-digit OTP code"""
        return ''.join(random.choices(string.digits, k=6))
    
    def is_expired(self):
        """Check if OTP is expired"""
        return timezone.now() > self.expires_at
    
    def is_valid(self):
        """Check if OTP is valid (not expired and not used)"""
        return not self.is_expired() and not self.is_used
    
    def mark_as_used(self):
        """Mark OTP as used"""
        self.is_used = True
        self.save()
    
    @classmethod
    def create_otp(cls, email):
        """Create a new OTP for the given email"""
        cls.objects.filter(email=email, is_used=False).update(is_used=True)
        return cls.objects.create(email=email)
    
    @classmethod
    def verify_otp(cls, email, otp_code):
        """Verify OTP code for the given email"""
        try:
            otp = cls.objects.get(
                email=email,
                otp_code=otp_code,
                is_used=False
            )
            if otp.is_valid():
                otp.is_verified = True
                otp.save()
                return True
            return False
        except cls.DoesNotExist:
            return False
    
    @classmethod
    def has_verified_otp(cls, email):
        """Check if email has a verified OTP that hasn't been used for password reset"""
        try:
            otp = cls.objects.get(
                email=email,
                is_verified=True,
                is_used=False
            )
            return otp.is_valid()
        except cls.DoesNotExist:
            return False
    
    @classmethod
    def mark_verified_otp_as_used(cls, email):
        """Mark the verified OTP as used after password reset"""
        try:
            otp = cls.objects.get(
                email=email,
                is_verified=True,
                is_used=False
            )
            if otp.is_valid():
                otp.mark_as_used()
                return True
            return False
        except cls.DoesNotExist:
            return False
    
    def __str__(self):
        return f"OTP for {self.email} - {self.otp_code}"