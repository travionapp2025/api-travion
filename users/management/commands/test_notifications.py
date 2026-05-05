from django.core.management.base import BaseCommand
from users.models import User
from users.services.firebase_admin_service import firebase_admin_service


class Command(BaseCommand):
    help = 'Test notification system'

    def add_arguments(self, parser):
        parser.add_argument('--user-email', type=str, help='User email to send test notification to')
        parser.add_argument('--title', type=str, default='Test Notification', help='Notification title')
        parser.add_argument('--body', type=str, default='This is a test notification', help='Notification body')

    def handle(self, *args, **options):
        user_email = options.get('user_email')
        title = options.get('title')
        body = options.get('body')
        
        if not user_email:
            self.stdout.write(self.style.ERROR('Please provide --user-email'))
            return
        
        try:
            user = User.objects.get(email=user_email)
            self.stdout.write(f"Testing notification for user: {user.email} (ID: {user.id})")
            
            # Send test notification
            result = firebase_admin_service.send_notification_to_user(
                user=user,
                title=title,
                body=body,
                notification_type='test',
                data={'test': 'true', 'timestamp': 'now'}
            )
            
            if result:
                self.stdout.write(self.style.SUCCESS('✅ Test notification sent successfully!'))
                self.stdout.write('Check your WebSocket connection and Firebase notifications.')
            else:
                self.stdout.write(self.style.ERROR('❌ Failed to send test notification'))
                
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User with email {user_email} not found'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
