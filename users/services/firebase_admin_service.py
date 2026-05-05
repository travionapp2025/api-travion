import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
import os
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class FirebaseService:
    """
    Simple Firebase service for sending notifications
    """
    
    def __init__(self):
        self.app = None
        self._initialize_firebase()
    
    def _initialize_firebase(self):
        """Initialize Firebase Admin SDK"""
        try:
            if not firebase_admin._apps:
                service_account_path = os.path.join(settings.BASE_DIR, "users", "travion-380dc-firebase-adminsdk-fbsvc-3b43cb8122.json")
                
                if os.path.exists(service_account_path):
                    cred = credentials.Certificate(service_account_path)
                    self.app = firebase_admin.initialize_app(cred)
                    logger.info("Firebase initialized")
                else:
                    logger.error(f"Service account file not found: {service_account_path}")
            else:
                self.app = firebase_admin.get_app()
                
        except Exception as e:
            logger.error(f"Firebase initialization failed: {str(e)}")
            self.app = None
    
    def send_notification_to_token(self, token: str, title: str, body: str, data: dict = None) -> Tuple[bool, str]:
        """Send notification to a specific FCM token
        
        Returns:
            Tuple[bool, str]: (success, error_message)
        """
        if not self.app:
            logger.error("Firebase not initialized")
            return False, "Firebase not initialized"
        
        if not token:
            logger.error("No token provided")
            return False, "No token provided"
        
        # Validate token format (basic validation)
        if not self._is_valid_token_format(token):
            logger.error(f"Invalid token format: {token[:20]}...")
            return False, "Invalid token format"
        
        try:
            # Convert data to strings
            string_data = {}
            if data:
                for key, value in data.items():
                    string_data[str(key)] = str(value)
            
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=string_data,
                token=token,
            )
            
            messaging.send(message)
            logger.info(f"Notification sent to {token[:20]}...")
            return True, ""
            
        except messaging.UnregisteredError:
            logger.warning(f"Token unregistered: {token[:20]}...")
            return False, "unregistered"
        except messaging.InvalidArgumentError:
            logger.warning(f"Invalid token argument: {token[:20]}...")
            return False, "invalid_argument"
        except messaging.SenderIdMismatchError:
            logger.warning(f"Sender ID mismatch: {token[:20]}...")
            return False, "sender_id_mismatch"
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to send notification: {error_msg}")
            return False, error_msg
    
    def _is_valid_token_format(self, token: str) -> bool:
        """Validate FCM token format"""
        if not token or len(token) < 10:
            return False
        
        # Check for test tokens or obviously invalid formats
        invalid_patterns = ['fcm_token', 'test_token', 'dummy_token', 'mock_token', 'fake_token']
        if any(pattern in token.lower() for pattern in invalid_patterns):
            logger.warning(f"Test/dummy token detected: {token[:20]}...")
            return False
        
        # Basic format validation - FCM tokens are typically base64-like strings
        # Be very lenient since FCM token formats can vary
        import re
        # Allow alphanumeric, hyphens, underscores, equal signs, dots, plus signs, and colons
        if not re.match(r'^[A-Za-z0-9\-_=\.\+:]+$', token):
            return False
        
        return True
    
    def send_notification_to_user(self, user, title: str, body: str, notification_type: str = 'system', data: dict = None, sender=None, notification_id=None) -> bool:
        """Send notification to all devices of a user - SIMPLIFIED VERSION"""
        from users.models import DeviceToken, Notification
        
        # If notification_id is provided, use existing notification instead of creating new one
        if notification_id:
            try:
                notification = Notification.objects.get(id=notification_id)
                logger.info(f"Using existing notification with ID: {notification.id}")
            except Notification.DoesNotExist:
                logger.error(f"Notification with ID {notification_id} not found")
                return False
        else:
            # Only create new notification if no existing one is provided
            notification = Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=body,
                data=data or {},
                sender=sender
            )
            logger.info(f"Notification record created with ID: {notification.id}")
        
        # ALWAYS send WebSocket notification (this should work)
        self._send_websocket_notification_update(user, notification)
        logger.info(f"WebSocket notification sent to user {user.id}")
        
        # Get only VALID device tokens (skip test/dummy tokens)
        device_tokens = DeviceToken.objects.filter(user=user, is_active=True)
        valid_tokens = [token for token in device_tokens if self._is_valid_token_format(token.token)]
        
        logger.info(f"Found {len(valid_tokens)} valid tokens out of {device_tokens.count()} total tokens")
        
        if not valid_tokens:
            logger.info(f"No valid device tokens for user {user.id}, WebSocket notification sent")
            notification.mark_as_sent()
            return True
        
        success_count = 0
        for device_token in valid_tokens:
            # Determine the "other user" relative to the recipient for chat notifications
            other_user_id = str(sender.id) if notification_type == 'chat_message' and sender else None
            other_user_email = sender.email if notification_type == 'chat_message' and sender else None
            other_user_name = sender.full_name if notification_type == 'chat_message' and sender else None

            firebase_data = {
                'notification_id': str(notification.id),
                'type': notification_type,
                'user_id': str(user.id),
                'user_email': user.email,
                'user_name': user.full_name,
                'user_firstname': user.firstname,
                'user_role': user.role,
                # Recipient (explicit)
                'recipient_user_id': str(user.id),
                'recipient_user_email': user.email,
                'recipient_user_name': user.full_name,
                'sender_id': str(sender.id) if sender else None,
                'sender_email': sender.email if sender else None,
                'sender_name': sender.full_name if sender else None,
                # Other participant for opening chat (for the recipient, this equals sender)
                'other_user_id': other_user_id,
                'other_user_email': other_user_email,
                'other_user_name': other_user_name,
                'chat_websocket_url': f'/ws/chat-updates/?token={{user_token}}',
                'chat_api_base_url': '/api/users/',
                'action': 'open_chat' if notification_type == 'chat_message' else 'view_match',
                **(data or {})
            }
            
            success, error_msg = self.send_notification_to_token(
                device_token.token, 
                title, 
                body, 
                firebase_data
            )
            
            if success:
                success_count += 1
            else:
                logger.warning(f"Failed to send to token {device_token.token[:20]}...: {error_msg}")
        
        # Mark as sent if WebSocket was sent (which always happens)
        notification.mark_as_sent()
        logger.info(f"Notification sent via WebSocket + {success_count}/{len(valid_tokens)} Firebase devices")
        
        return True
    
    def send_chat_message_notification(self, message, conversation):
        """Send notification for new chat message"""
        recipient = conversation.user1 if conversation.user2 == message.sender else conversation.user2
        
        title = f"New message from {message.sender.full_name}"
        body = message.content[:100] + "..." if len(message.content) > 100 else message.content
        
        data = {
            'conversation_id': str(conversation.id),
            'message_id': str(message.id),
            'message_content': message.content,
            'message_created_at': message.created_at.isoformat(),
            'conversation_is_first_time': conversation.is_first_time,
            'conversation_created_at': conversation.created_at.isoformat(),
            'action': 'open_chat',
            'message_preview': message.content[:100] + "..." if len(message.content) > 100 else message.content,
            # Add recipient context for frontend routing
            'recipient_user_id': str(recipient.id),
            'recipient_user_email': recipient.email,
            'recipient_user_name': recipient.full_name,
            # Add other participant (sender) info so client can open chat with them directly
            'other_user_id': str(message.sender.id),
            'other_user_email': message.sender.email,
            'other_user_name': message.sender.full_name
        }
        
        logger.info(f"Sending chat notification: {title} to {recipient.email}")
        
        result = self.send_notification_to_user(
            user=recipient,
            title=title,
            body=body,
            notification_type='chat_message',
            data=data,
            sender=message.sender
        )
        
        logger.info(f"Chat notification result: {result}")
        return result

    def _send_websocket_notification_update(self, user, notification):
        """Send WebSocket update for new notification - SIMPLIFIED"""
        try:
            
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            
            channel_layer = get_channel_layer()
            if not channel_layer:
                logger.warning("Channel layer not available")
                return
            
            # Get notification counts
            from users.models import Notification
            unread_count = Notification.objects.filter(user=user, is_read=False).count()
            
            # Enhanced notification data with user info and chat details
            notification_data = {
                'id': notification.id,
                'type': notification.notification_type,
                'title': notification.title,
                'message': notification.message,
                'created_at': notification.created_at.isoformat(),
                'data': notification.data,
                
                # User information for frontend routing
                'user_id': str(user.id),
                'user_email': user.email,
                'user_name': user.full_name,
                'user_firstname': user.firstname,
                'user_role': user.role,
                'user_profile_picture': user.profile_picture.url if user.profile_picture else None,
                # Recipient explicit fields
                'recipient_user_id': str(user.id),
                'recipient_user_email': user.email,
                'recipient_user_name': user.full_name,
                
                # Sender information (if available)
                'sender_id': str(notification.sender.id) if notification.sender else None,
                'sender_email': notification.sender.email if notification.sender else None,
                'sender_name': notification.sender.full_name if notification.sender else None,
                'sender_firstname': notification.sender.firstname if notification.sender else None,
                'sender_role': notification.sender.role if notification.sender else None,
                'sender_profile_picture': notification.sender.profile_picture.url if notification.sender and notification.sender.profile_picture else None,
                # Other participant for opening chat (for recipient, this equals sender)
                'other_user_id': str(notification.sender.id) if notification.sender else None,
                'other_user_email': notification.sender.email if notification.sender else None,
                'other_user_name': notification.sender.full_name if notification.sender else None,
                
                # Chat connection details
                'chat_websocket_url': f'/ws/chat-updates/?token={{user_token}}',
                'chat_api_base_url': '/api/users/',
                'conversation_id': notification.data.get('conversation_id') if notification.data else None,
                'action': 'open_chat' if notification.notification_type == 'chat_message' else 'view_match'
            }
            
            # Send to user's WebSocket group
            group_name = f"chat_updates_{user.id}"
            
            async_to_sync(channel_layer.group_send)(group_name, {
                'type': 'new_notification',
                'notification': notification_data,
                'unread_count': unread_count
            })
            
            logger.info(f"WebSocket notification sent to user {user.id} (unread: {unread_count})")
            
        except Exception as e:
            logger.error(f"WebSocket notification failed: {str(e)}")
    
    def _cleanup_invalid_tokens(self, invalid_tokens: List) -> None:
        """Clean up invalid device tokens"""
        try:
            from users.models import DeviceToken
            
            token_ids = [token.id for token in invalid_tokens]
            
            # Mark tokens as inactive instead of deleting them for debugging purposes
            updated_count = DeviceToken.objects.filter(id__in=token_ids).update(is_active=False)
            
            logger.info(f"Cleaned up {updated_count} invalid device tokens")
            
        except Exception as e:
            logger.error(f"Failed to cleanup invalid tokens: {str(e)}")
    
    def cleanup_all_invalid_tokens(self) -> int:
        """Clean up all invalid tokens in the system"""
        try:
            from users.models import DeviceToken
            
            # Get all active tokens
            active_tokens = DeviceToken.objects.filter(is_active=True)
            invalid_count = 0
            
            for device_token in active_tokens:
                # Test each token by sending a silent notification
                success, error_msg = self.send_notification_to_token(
                    device_token.token, 
                    "Token Validation", 
                    "Silent validation", 
                    {"silent": "true"}
                )
                
                if not success and error_msg in ['unregistered', 'invalid_argument', 'sender_id_mismatch']:
                    device_token.is_active = False
                    device_token.save()
                    invalid_count += 1
                    logger.info(f"Marked invalid token as inactive: {device_token.token[:20]}...")
            
            logger.info(f"Cleanup completed: {invalid_count} tokens marked as inactive")
            return invalid_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup all invalid tokens: {str(e)}")
            return 0


firebase_admin_service = FirebaseService()