from django.core.management.base import BaseCommand
from django.utils import timezone
from users.models import DeviceToken
from users.services.firebase_admin_service import firebase_admin_service
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up invalid FCM device tokens'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without making changes',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force cleanup even if there are many tokens',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        self.stdout.write(
            self.style.SUCCESS('Starting FCM token cleanup...')
        )
        
        # Get all active tokens
        active_tokens = DeviceToken.objects.filter(is_active=True)
        total_tokens = active_tokens.count()
        
        self.stdout.write(f"Found {total_tokens} active device tokens")
        
        if total_tokens == 0:
            self.stdout.write(
                self.style.WARNING('No active tokens found to clean up')
            )
            return
        
        # Check for obviously invalid tokens first
        invalid_tokens = []
        test_tokens = []
        
        for token in active_tokens:
            if not firebase_admin_service._is_valid_token_format(token.token):
                if 'fcm_token' in token.token.lower() or 'test_token' in token.token.lower():
                    test_tokens.append(token)
                else:
                    invalid_tokens.append(token)
        
        self.stdout.write(f"Found {len(test_tokens)} test tokens")
        self.stdout.write(f"Found {len(invalid_tokens)} invalid format tokens")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN - No changes will be made')
            )
            
            for token in test_tokens:
                self.stdout.write(f"  Test token: {token.user.email} - {token.token[:20]}...")
            
            for token in invalid_tokens:
                self.stdout.write(f"  Invalid token: {token.user.email} - {token.token[:20]}...")
            
            return
        
        # Clean up test tokens
        if test_tokens:
            self.stdout.write(f"Cleaning up {len(test_tokens)} test tokens...")
            for token in test_tokens:
                token.is_active = False
                token.save()
                self.stdout.write(f"  [OK] Deactivated test token: {token.user.email}")
        
        # Clean up invalid format tokens
        if invalid_tokens:
            self.stdout.write(f"Cleaning up {len(invalid_tokens)} invalid format tokens...")
            for token in invalid_tokens:
                token.is_active = False
                token.save()
                self.stdout.write(f"  [OK] Deactivated invalid token: {token.user.email}")
        
        # For remaining tokens, test them with Firebase (if not too many)
        remaining_tokens = DeviceToken.objects.filter(is_active=True)
        remaining_count = remaining_tokens.count()
        
        if remaining_count > 100 and not force:
            self.stdout.write(
                self.style.WARNING(
                    f'Too many tokens ({remaining_count}) to test individually. '
                    'Use --force to test all tokens or run cleanup in smaller batches.'
                )
            )
            return
        
        if remaining_count > 0:
            self.stdout.write(f"Testing {remaining_count} remaining tokens with Firebase...")
            
            cleaned_count = firebase_admin_service.cleanup_all_invalid_tokens()
            
            if cleaned_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(f"[OK] Cleaned up {cleaned_count} additional invalid tokens")
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS("[OK] No additional invalid tokens found")
                )
        
        # Summary
        final_active_count = DeviceToken.objects.filter(is_active=True).count()
        cleaned_total = total_tokens - final_active_count
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Cleanup completed!\n'
                f'  Original active tokens: {total_tokens}\n'
                f'  Tokens cleaned up: {cleaned_total}\n'
                f'  Remaining active tokens: {final_active_count}'
            )
        )
