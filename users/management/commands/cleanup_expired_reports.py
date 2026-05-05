from django.core.management.base import BaseCommand
from django.utils import timezone
from users.models import ReportedUser
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up expired reported user restrictions (24-hour expiry)'

    def handle(self, *args, **options):
        """
        Remove expired report restrictions that are older than 24 hours
        """
        try:
            now = timezone.now()
            expired_reports = ReportedUser.objects.filter(expires_at__lt=now)

            count = expired_reports.count()
            if count > 0:
                expired_reports.delete()
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully cleaned up {count} expired report restrictions')
                )
                logger.info(f'Cleaned up {count} expired report restrictions')
            else:
                self.stdout.write('No expired report restrictions to clean up')
                logger.info('No expired report restrictions found')

        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f'Error cleaning up expired reports: {str(e)}')
            )
            logger.error(f'Error cleaning up expired reports: {str(e)}')