import json
import jwt
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from users.models.user import User


class ChatUpdatesConsumer(AsyncWebsocketConsumer):
    """
    Consumer for real-time chat conversation updates and notifications
    This handles live updates to the chat conversations list and notification system
    """
    
    async def connect(self):
        print(f"\n🔗 [UPDATES_CONNECT] WebSocket connection attempt started")
        print(f"   Scope: {self.scope.get('url_route', {})}")
        
        token = None
        try:
            query_string = self.scope.get('query_string', b'').decode()
            print(f"   Query string: {query_string}")
            if query_string:
                for part in query_string.split('&'):
                    if part.startswith('token='):
                        token = part.split('=', 1)[1]
                        print(f"   ✓ Token extracted (length: {len(token)})")
                        break
        except Exception as e:
            print(f"   ⚠️ Error parsing query string: {str(e)}")
            token = None

        # Authenticate current user via JWT token
        print(f"   Authenticating token...")
        self.current_user = await self._authenticate_token(token)
        if not self.current_user:
            print(f"   ❌ Authentication failed - closing connection (4401)")
            await self.close(code=4401)  # Unauthorized
            return
        print(f"   ✓ User authenticated: {self.current_user.id} ({self.current_user.email})")

        # Set up group name for this user's chat updates
        self.group_name = f"chat_updates_{self.current_user.id}"
        print(f"   Adding to group: {self.group_name}")
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        
        print(f"   ✓ Accepting WebSocket connection...")
        await self.accept()

        # Send initial connection data including notification counts
        print(f"   Fetching initial data...")
        initial_data = await self._get_initial_data()
        
        print(f"   Sending initial connected message...")
        await self.send(text_data=json.dumps({
            'event': 'connected',
            'user_id': self.current_user.id,
            'message': 'Connected to chat updates and notifications',
            'data': initial_data
        }))
        
        print(f"✅ [UPDATES_CONNECT] Connection successful for user {self.current_user.id}\n")

    async def disconnect(self, close_code):
        print(f"\n🔌 [UPDATES_DISCONNECT] Disconnected with code {close_code}")
        if hasattr(self, 'group_name'):
            print(f"   Discarding group: {self.group_name}")
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        print(f"✅ [UPDATES_DISCONNECT] Complete\n")

    async def receive(self, text_data=None, bytes_data=None):
        print(f"📨 [UPDATES_RECEIVE] Message from user {self.current_user.id}")
        try:
            payload = json.loads(text_data or '{}')
            print(f"   Payload: {payload}")
        except json.JSONDecodeError as e:
            print(f"   ❌ JSON decode error: {str(e)}")
            return

        action = payload.get('action', 'ping')
        print(f"   Action: {action}")

        if action == 'ping':
            print(f"   Responding to ping...")
            await self.send(text_data=json.dumps({
                'event': 'pong',
                'timestamp': payload.get('timestamp')
            }))

    # Handle different types of chat updates
    async def new_message_update(self, event):
        """Handle new message notifications"""
        print(f"      [BROADCAST] Sending new_message_update to user {self.current_user.id}")
        await self.send(text_data=json.dumps({
            'event': 'new_message',
            'conversation_id': event['conversation_id'],
            'message': event['message'],
            'unread_count': event.get('unread_count', 0),
            'is_first_time': event.get('is_first_time', False)
        }))

    async def message_read_update(self, event):
        """Handle message read notifications"""
        print(f"      [BROADCAST] Sending message_read_update to user {self.current_user.id}")
        await self.send(text_data=json.dumps({
            'event': 'message_read',
            'conversation_id': event['conversation_id'],
            'read_count': event.get('read_count', 0)
        }))

    async def conversation_update(self, event):
        """Handle general conversation updates"""
        print(f"      [BROADCAST] Sending conversation_update to user {self.current_user.id}")
        await self.send(text_data=json.dumps({
            'event': 'conversation_update',
            'conversation_id': event['conversation_id'],
            'data': event['data']
        }))

    async def conversation_read_update(self, event):
        """Handle conversation read updates"""
        print(f"      [BROADCAST] Sending conversation_read_update to user {self.current_user.id}")
        await self.send(text_data=json.dumps({
            'event': 'conversation_read',
            'conversation_id': event['conversation_id'],
            'unread_count': event['unread_count'],
            'read_by': event['read_by']
        }))

    # === NOTIFICATION-RELATED EVENTS ===
    
    async def new_notification(self, event):
        """Handle new notification events with enhanced user details"""
        try:
            from asgiref.sync import sync_to_async
            from users.models import DeviceToken
            
            device_count = await sync_to_async(
                DeviceToken.objects.filter(user=self.current_user, is_active=True).count
            )()
            
            enhanced_notification = event['notification'].copy()
            enhanced_notification.update({
                'current_user_id': str(self.current_user.id),
                'current_user_email': self.current_user.email,
                'current_user_name': self.current_user.full_name,
                'current_user_firstname': self.current_user.firstname,
                'current_user_role': self.current_user.role,
                'current_user_profile_picture': self.current_user.profile_picture.url if self.current_user.profile_picture else None,
                
                # Device and connection info
                'active_devices': device_count,
                'websocket_connected': True,
                'connection_timestamp': event.get('timestamp', ''),
                
                # Chat connection details
                'chat_websocket_url': f'/ws/chat-updates/?token={{user_token}}',
                'chat_api_base_url': '/api/users/',
                'conversation_endpoint': '/api/users/conversations/',
                'messages_endpoint': '/api/users/messages/',
                
                # Action routing
                'action': enhanced_notification.get('action', 'view_match'),
                'routing_info': {
                    'should_open_chat': enhanced_notification.get('type') == 'chat_message',
                    'should_show_match': enhanced_notification.get('type') == 'itinerary_match',
                    'conversation_id': enhanced_notification.get('data', {}).get('conversation_id'),
                    'match_id': enhanced_notification.get('data', {}).get('seeker_request_id') or enhanced_notification.get('data', {}).get('provider_itinerary_id')
                }
            })
            
            await self.send(text_data=json.dumps({
                'event': 'new_notification',
                'notification': enhanced_notification,
                'unread_count': event.get('unread_count', 0),
                'user_context': {
                    'user_id': str(self.current_user.id),
                    'user_email': self.current_user.email,
                    'active_devices': device_count,
                    'websocket_connected': True
                }
            }))
            print(f"Enhanced WebSocket notification sent to user {self.current_user.id}: {event['notification']['title']}")
        except Exception as e:
            print(f"Failed to send enhanced WebSocket notification: {str(e)}")

    async def notification_read(self, event):
        """Handle notification read events"""
        await self.send(text_data=json.dumps({
            'event': 'notification_read',
            'notification_id': event['notification_id'],
            'unread_count': event.get('unread_count', 0),
            'total_notifications': event.get('total_notifications', 0)
        }))

    async def notification_count_update(self, event):
        """Handle notification count updates"""
        await self.send(text_data=json.dumps({
            'event': 'notification_count_update',
            'unread_count': event['unread_count'],
            'total_notifications': event.get('total_notifications', 0),
            'notification_type': event.get('notification_type')
        }))

    async def notification_preferences_update(self, event):
        """Handle notification preferences updates"""
        await self.send(text_data=json.dumps({
            'event': 'notification_preferences_update',
            'preferences': event['preferences']
        }))

    async def device_token_update(self, event):
        """Handle device token updates (login/logout)"""
        await self.send(text_data=json.dumps({
            'event': 'device_token_update',
            'action': event['action'],  # 'added', 'removed', 'updated'
            'device_type': event.get('device_type'),
            'total_devices': event.get('total_devices', 0)
        }))

    # === MATCH-RELATED EVENTS ===
    
    async def new_match_found(self, event):
        """Handle new match found events"""
        await self.send(text_data=json.dumps({
            'event': 'new_match_found',
            'match_type': event['match_type'],  # 'seeker_match' or 'provider_match'
            'match_data': event['match_data'],
            'message': event.get('message', 'New travel match found!')
        }))
    
    async def seeker_request_matched(self, event):
        """Handle when a seeker request finds a match"""
        await self.send(text_data=json.dumps({
            'event': 'seeker_request_matched',
            'seeker_request_id': event['seeker_request_id'],
            'provider_info': event['provider_info'],
            'match_details': event['match_details'],
            'message': f"Found a match for your travel request: {event['match_details']['route']}"
        }))
    
    async def provider_itinerary_matched(self, event):
        """Handle when a provider itinerary finds a match"""
        await self.send(text_data=json.dumps({
            'event': 'provider_itinerary_matched',
            'provider_itinerary_id': event['provider_itinerary_id'],
            'seeker_info': event['seeker_info'],
            'match_details': event['match_details'],
            'message': f"Someone is looking for your route: {event['match_details']['route']}"
        }))

    async def _authenticate_token(self, token: str):
        """Authenticate user via JWT token"""
        if not token:
            return None
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.SIMPLE_JWT.get('ALGORITHM', 'HS256')],
                options={'verify_aud': False}
            )
            user_id = payload.get(settings.SIMPLE_JWT.get('USER_ID_CLAIM', 'user_id'))
            if not user_id:
                return None
            return await self._get_user(user_id)
        except Exception:
            return None

    async def _get_user(self, user_id):
        """Get user by ID"""
        from asgiref.sync import sync_to_async
        return await sync_to_async(User.objects.get)(id=user_id)

    async def provider_provider_matched(self, event):
        # No-op handler to prevent Channels crash
        pass
    async def _get_initial_data(self):
        """Get initial data for the user including notification counts"""
        from asgiref.sync import sync_to_async
        from users.models import Notification, DeviceToken
        
        unread_count = await sync_to_async(
            Notification.objects.filter(user=self.current_user, is_read=False).count
        )()
        
        total_count = await sync_to_async(
            Notification.objects.filter(user=self.current_user).count
        )()
        
        # Get device count
        device_count = await sync_to_async(
            DeviceToken.objects.filter(user=self.current_user, is_active=True).count
        )()
        
        return {
            'unread_notifications': unread_count,
            'total_notifications': total_count,
            'active_devices': device_count,
            'user_info': {
                'user_id': str(self.current_user.id),
                'user_email': self.current_user.email,
                'user_name': self.current_user.full_name,
                'user_firstname': self.current_user.firstname,
                'user_role': self.current_user.role,
                'user_profile_picture': self.current_user.profile_picture.url if self.current_user.profile_picture else None
            },
            'connection_info': {
                'websocket_url': '/ws/chat-updates/',
                'api_base_url': '/api/users/',
                'conversation_endpoint': '/api/users/conversations/',
                'messages_endpoint': '/api/users/messages/',
                'notifications_endpoint': '/api/users/notifications/'
            }
        }
