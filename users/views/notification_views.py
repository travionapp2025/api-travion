from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from users.models import DeviceToken, Notification, NotificationPreference
from users.services.firebase_admin_service import firebase_admin_service
import logging

logger = logging.getLogger(__name__)


class DeviceTokenView(APIView):
    """Manage device tokens for push notifications"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Register device token"""
        try:
            token = request.data.get('token')
            device_type = request.data.get('device_type', 'android')
            
            if not token:
                return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Create or update device token
            device_token, created = DeviceToken.objects.update_or_create(
                user=request.user,
                token=token,
                defaults={'device_type': device_type, 'is_active': True}
            )
            
            return Response({
                'message': 'Device token registered successfully',
                'created': created
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error registering device token: {str(e)}")
            return Response({'error': 'Failed to register device token'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request):
        """Remove device token"""
        try:
            token = request.data.get('token')
            
            if token:
                DeviceToken.objects.filter(user=request.user, token=token).delete()
            else:
                DeviceToken.objects.filter(user=request.user).delete()
            
            return Response({'message': 'Device token removed successfully'}, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error removing device token: {str(e)}")
            return Response({'error': 'Failed to remove device token'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NotificationListView(APIView):
    """Get user notifications"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get notifications"""
        try:
            unread_only = request.query_params.get('unread_only', 'false').lower() == 'true'
            limit = int(request.query_params.get('limit', 50))
            offset = int(request.query_params.get('offset', 0))
            
            notifications = Notification.objects.filter(user=request.user)
            
            if unread_only:
                notifications = notifications.filter(is_read=False)
            
            notifications = notifications.order_by('-created_at')[offset:offset+limit]
            
            notifications_data = []
            for notification in notifications:
                notifications_data.append({
                    'id': notification.id,
                    'type': notification.notification_type,
                    'title': notification.title,
                    'message': notification.message,
                    'data': notification.data,
                    'is_read': notification.is_read,
                    'created_at': notification.created_at.isoformat(),
                })
            
            unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
            
            return Response({
                'notifications': notifications_data,
                'unread_count': unread_count
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting notifications: {str(e)}")
            return Response({'error': 'Failed to get notifications'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NotificationDetailView(APIView):
    """Mark notification as read"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, notification_id):
        """Mark notification as read"""
        try:
            notification = Notification.objects.get(id=notification_id, user=request.user)
            notification.mark_as_read()
            
            _send_notification_read_update(request.user, notification)
            
            return Response({'message': 'Notification marked as read'}, status=status.HTTP_200_OK)
            
        except Notification.DoesNotExist:
            return Response({'error': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error marking notification as read: {str(e)}")
            return Response({'error': 'Failed to mark notification as read'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, notification_id):
        """Delete notification"""
        try:
            notification = Notification.objects.get(id=notification_id, user=request.user)
            notification.delete()
            
            return Response({'message': 'Notification deleted successfully'}, status=status.HTTP_200_OK)
            
        except Notification.DoesNotExist:
            return Response({'error': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting notification: {str(e)}")
            return Response({'error': 'Failed to delete notification'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MarkAllNotificationsReadView(APIView):
    """Mark all notifications as read"""
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        """Mark all notifications as read"""
        try:
            updated_count = Notification.objects.filter(
                user=request.user,
                is_read=False
            ).update(is_read=True, read_at=timezone.now())
            
            return Response({
                'message': f'{updated_count} notifications marked as read',
                'updated_count': updated_count
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error marking all notifications as read: {str(e)}")
            return Response({'error': 'Failed to mark all notifications as read'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NotificationPreferencesView(APIView):
    """Manage notification preferences"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get notification preferences"""
        try:
            preferences, created = NotificationPreference.objects.get_or_create(user=request.user)
            
            return Response({
                'push_notifications_enabled': preferences.push_notifications_enabled,
                'chat_notifications_enabled': preferences.chat_notifications_enabled,
                'itinerary_match_notifications_enabled': preferences.itinerary_match_notifications_enabled,
                'system_notifications_enabled': preferences.system_notifications_enabled,
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting notification preferences: {str(e)}")
            return Response({'error': 'Failed to get notification preferences'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def patch(self, request):
        """Update notification preferences"""
        try:
            preferences, created = NotificationPreference.objects.get_or_create(user=request.user)
            
            allowed_fields = [
                'push_notifications_enabled',
                'chat_notifications_enabled',
                'itinerary_match_notifications_enabled',
                'system_notifications_enabled',
            ]
            
            for field in allowed_fields:
                if field in request.data:
                    setattr(preferences, field, request.data[field])
            
            preferences.save()
            
            return Response({'message': 'Notification preferences updated successfully'}, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error updating notification preferences: {str(e)}")
            return Response({'error': 'Failed to update notification preferences'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TestNotificationView(APIView):
    """Send test notification"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Send test notification"""
        try:
            title = request.data.get('title', 'Test Notification')
            body = request.data.get('body', 'This is a test message')
            notification_type = request.data.get('notification_type', 'system')
            test_token = request.data.get('test_token')
            
            if test_token:
                # Test specific token
                success, error_msg = firebase_admin_service.send_notification_to_token(
                    token=test_token,
                    title=title,
                    body=body,
                    data={'test': 'true'}
                )
                
                if not success:
                    return Response({
                        'error': 'Failed to send test notification', 
                        'details': error_msg
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                # Test user devices
                success = firebase_admin_service.send_notification_to_user(
                    user=request.user,
                    title=title,
                    body=body,
                    notification_type=notification_type,
                    data={'test': 'true'}
                )
            
            if success:
                return Response({'message': 'Test notification sent successfully'}, status=status.HTTP_200_OK)
            else:
                return Response({'error': 'Failed to send test notification'}, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f"Error sending test notification: {str(e)}")
            return Response({'error': 'Failed to send test notification'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CleanupTokensView(APIView):
    """Clean up invalid device tokens"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Clean up invalid tokens for the current user"""
        try:
            # Only clean up tokens for the current user
            user_tokens = DeviceToken.objects.filter(user=request.user, is_active=True)
            
            if not user_tokens.exists():
                return Response({
                    'message': 'No active tokens found for user',
                    'cleaned_count': 0
                }, status=status.HTTP_200_OK)
            
            cleaned_count = 0
            for device_token in user_tokens:
                # Test each token
                success, error_msg = firebase_admin_service.send_notification_to_token(
                    device_token.token,
                    "Token Validation",
                    "Silent validation",
                    {"silent": "true"}
                )
                
                if not success and error_msg in ['unregistered', 'invalid_argument', 'sender_id_mismatch']:
                    device_token.is_active = False
                    device_token.save()
                    cleaned_count += 1
            
            return Response({
                'message': f'Token cleanup completed',
                'cleaned_count': cleaned_count,
                'remaining_tokens': user_tokens.count() - cleaned_count
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error cleaning up tokens: {str(e)}")
            return Response({'error': 'Failed to clean up tokens'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _send_notification_read_update(user, notification):
    """Send WebSocket update when notification is marked as read"""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        
        unread_count = Notification.objects.filter(user=user, is_read=False).count()
        total_count = Notification.objects.filter(user=user).count()
        
        group_name = f"chat_updates_{user.id}"
        async_to_sync(channel_layer.group_send)(group_name, {
            'type': 'notification_read',
            'notification_id': notification.id,
            'unread_count': unread_count,
            'total_notifications': total_count,
            'target_user_id': str(user.id),
            'target_user_email': user.email
        })
        
        logger.info(f"🔔 WebSocket notification read update sent to user {user.id}")
        
    except Exception as e:
        logger.error(f"❌ Failed to send WebSocket notification read update: {str(e)}")