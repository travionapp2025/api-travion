from django.core.management.base import BaseCommand
from django.utils import timezone
from users.services.matching_service import MatchingService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up expired seeker requests'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without actually doing it',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN: No changes will be made')
            )
        
        try:
            if dry_run:
                # Count expired requests without updating them
                from users.models import SeekerRequest
                expired_count = SeekerRequest.objects.filter(
                    is_active=True,
                    expires_at__lte=timezone.now()
                ).count()
                
                self.stdout.write(
                    self.style.SUCCESS(f'Would clean up {expired_count} expired seeker requests')
                )
            else:
                # Actually clean up expired requests
                cleaned_count = MatchingService.cleanup_expired_requests()
                
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully cleaned up {cleaned_count} expired seeker requests')
                )
                
        except Exception as e:
            logger.error(f"Error in cleanup command: {str(e)}")
            self.stdout.write(
                self.style.ERROR(f'Error cleaning up expired requests: {str(e)}')
            )
