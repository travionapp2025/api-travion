import json
import jwt
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db.models import Q
from users.models.chat import Conversation, Message
from users.models.itinerary import Itinerary
from users.models.user import User
import asyncio
from users.services.firebase_admin_service import firebase_admin_service


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print(f"\n🔗 [CHAT_CONNECT] WebSocket connection attempt started")
        print(f"   Scope route: {self.scope.get('url_route', {})}")
        
        route_kwargs = self.scope['url_route']['kwargs']
        self.other_user_id = route_kwargs.get('other_user_id')
        self.itinerary_id = route_kwargs.get('itinerary_id')
        print(f"   Extracted other_user_id: {self.other_user_id}")
        
        if not self.other_user_id:
            print(f"   ❌ Missing other_user_id - closing connection (4400)")
            await self.close(code=4400)  
            return

        token = None
        try:
            query_string = self.scope.get('query_string', b'').decode()
            print(f"   Query string: {query_string}")
            if query_string:
                for part in query_string.split('&'):
                    if part.startswith('token='):
                        token = part.split('=', 1)[1]
                        print(f"   ✓ Token extracted (length: {len(token)})")
                    elif part.startswith('itinerary_id='):
                        self.itinerary_id = part.split('=', 1)[1]
                        print(f"   Itinerary ID extracted: {self.itinerary_id}")
        except Exception as e:
            print(f"   ⚠️ Error parsing query string: {str(e)}")
            token = None

        if not token:
            print(f"   ❌ No token found in query string")

        print(f"   Authenticating token...")
        self.current_user = await self._authenticate_token(token)
        if not self.current_user:
            print(f"   ❌ Authentication failed - closing connection (4401)")
            await self.close(code=4401)  
            return
        print(f"   ✓ User authenticated: {self.current_user.id} ({self.current_user.email})")

        self.itinerary = None
        if self.itinerary_id:
            try:
                print(f"   Fetching itinerary {self.itinerary_id} for current user...")
                self.itinerary = await self._get_user_itinerary(self.itinerary_id, self.current_user)
                print(f"   Itinerary found: {self.itinerary.id} (paid={self.itinerary.is_paid})")
            except Exception as e:
                print(f"   Itinerary not found for current user: {str(e)} - closing connection (4404)")
                await self.close(code=4404)
                return

        try:
            print(f"   Fetching other user {self.other_user_id}...")
            self.other_user = await self._get_user(self.other_user_id)
            print(f"   ✓ Other user found: {self.other_user.id} ({self.other_user.email})")
        except Exception as e:
            print(f"   ❌ Other user not found: {str(e)} - closing connection (4404)")
            await self.close(code=4404)  
            return

        # Prevent self-chat (disabled for testing)
        # if self.current_user.id == int(self.other_user_id):
        #     await self.close(code=4400)  # Bad Request
        #     return

        # Check if conversation exists; enforce subscription limits before creating
        from asgiref.sync import sync_to_async

        print(f"   Checking for existing conversation...")
        existing_filters = {
            'user1_id': min(self.current_user.id, self.other_user.id),
            'user2_id': max(self.current_user.id, self.other_user.id),
        }
        if self.itinerary:
            existing_filters['itinerary_id'] = self.itinerary.id
        else:
            existing_filters['itinerary__isnull'] = True

        async_get_existing = sync_to_async(
            lambda: Conversation.objects.filter(**existing_filters).first()
        )
        existing_conversation = await async_get_existing()

        if existing_conversation:
            print(f"   ✓ Existing conversation found: {existing_conversation.id}")
            self.conversation = existing_conversation
        else:
            print(f"   No existing conversation. Checking payment rules...")
            async_has_used_chat = sync_to_async(
                lambda: Conversation.objects.filter(
                    Q(user1_id=self.current_user.id) | Q(user2_id=self.current_user.id),
                    is_first_time=False,
                    **({'itinerary_id': self.itinerary.id} if self.itinerary else {})
                ).exists()
            )
            has_used_free_chat = await async_has_used_chat()
            print(f"   Has used a first chat already: {has_used_free_chat}")

            if has_used_free_chat:
                print(f"   Checking for paid itinerary (first chat is free, next requires payment)...")
                if self.itinerary:
                    has_paid_itinerary = self.itinerary.is_paid
                else:
                    async_paid = sync_to_async(
                        lambda: Itinerary.objects.filter(user=self.current_user, is_paid=True).exists()
                    )
                    has_paid_itinerary = await async_paid()
                print(f"   Has paid itinerary: {has_paid_itinerary}")
                if not has_paid_itinerary:
                    print(f"   ❌ No paid itinerary - closing connection (4403 Payment Required)")
                    await self.close(code=4403)
                    return

            print(f"   ✓ Creating new conversation...")
            self.conversation = await self._get_or_create_conversation(self.current_user, self.other_user, self.itinerary)
            print(f"   ✓ Conversation created/retrieved: {self.conversation.id}")
        
        self.group_name = f"chat_{self.conversation.id}"
        print(f"   Adding to group: {self.group_name}")
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        
        print(f"   ✓ Accepting WebSocket connection...")
        await self.accept()

        print(f"   Sending initial connected message...")
        await self.send(text_data=json.dumps({
            'event': 'connected',
            'conversation_id': self.conversation.id,
            'other_user': {
                'id': self.other_user.id,
                'email': self.other_user.email,
                'full_name': self.other_user.full_name,
                'role': self.other_user.role,
                'profile_picture': self.other_user.profile_picture.url if self.other_user.profile_picture else None
            },
            'itinerary_id': self.itinerary.id if self.itinerary else None
        }))
        print(f"\n✅ [CHAT_CONNECT] Connection successful for user {self.current_user.id} <-> {self.other_user.id}\n")

    async def disconnect(self, close_code):
        print(f"\n🔌 [CHAT_DISCONNECT] Disconnected with code {close_code}")
        if hasattr(self, 'group_name'):
            print(f"   Discarding group: {self.group_name}")
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        print(f"✅ [CHAT_DISCONNECT] Complete\n")

    async def receive(self, text_data=None, bytes_data=None):
        print(f"📨 [CHAT_RECEIVE] Message received from user {self.current_user.id}")
        try:
            payload = json.loads(text_data or '{}')
            print(f"   Payload: {payload}")
        except json.JSONDecodeError as e:
            print(f"   ❌ JSON decode error: {str(e)}")
            return

        action = payload.get('action', 'message')
        print(f"   Action: {action}")

        if action == 'message':
            print(f"   Processing message action...")
            content = (payload.get('content') or '').strip()
            if not content:
                print(f"   ❌ Empty content")
                return

            print(f"   Creating message (content length: {len(content)})...")
            msg = await self._create_message(self.conversation, self.current_user, content)
            print(f"   ✓ Message created: {msg.id}")

            print(f"   Handling first message logic...")
            await self._handle_first_message(self.conversation)

            print(f"   Sending push notification...")
            await self._send_message_notification(msg, self.conversation)

            print(f"   Broadcasting message to group {self.group_name}...")
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'chat_message',
                    'message': {
                        'id': msg.id,
                        'content': msg.content,
                        'created_at': msg.created_at.isoformat(),
                        'is_read': msg.is_read,
                        'sender': {
                            'id': msg.sender.id,
                            'email': msg.sender.email,
                            'full_name': msg.sender.full_name,
                            'role': msg.sender.role,
                            'profile_picture': self._get_profile_picture_url(msg.sender),
                        }
                    }
                }
            )


            from asgiref.sync import sync_to_async
            async_get_user1 = sync_to_async(lambda: self.conversation.user1)
            async_get_user2 = sync_to_async(lambda: self.conversation.user2)
            
            user1 = await async_get_user1()
            user2 = await async_get_user2()
            
            recipient = user1 if user2.id == self.current_user.id else user2
            print(f"   Sending conversation update...")
            await self._send_conversation_update(recipient, msg, self.conversation)
            print(f"   ✓ Message action complete\n")

        elif action == 'read_all':
            print(f"   Processing read_all action...")
            # Mark all messages from other user as read
            updated_count = await self._mark_messages_read(self.conversation, self.current_user)
            
            # Broadcast read status to other user
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'chat_read',
                    'read': {
                        'updated_count': updated_count,
                        'read_by': {
                            'id': self.current_user.id,
                            'full_name': self.current_user.full_name
                        }
                    }
                }
            )
            
            # Send conversation list update to mark messages as read
            await self._send_conversation_read_update(self.current_user, self.conversation)

        elif action == 'get_messages':
            print(f"   Processing get_messages action...")
            # Send recent messages to the user
            limit = int(payload.get('limit', 50))
            print(f"   Fetching {limit} recent messages...")
            messages = await self._get_recent_messages(self.conversation, limit)
            print(f"   ✓ Retrieved {len(messages)} messages")
            
            await self.send(text_data=json.dumps({
                'event': 'messages_history',
                'messages': messages
            }))

        elif action == 'typing':
            print(f"   Processing typing action...")
            # Broadcast typing indicator
            is_typing = payload.get('is_typing', False)
            print(f"   is_typing: {is_typing}")
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'chat_typing',
                    'typing': {
                        'user_id': self.current_user.id,
                        'user_name': self.current_user.full_name,
                        'is_typing': is_typing
                    }
                }
            )

    async def chat_message(self, event):
        print(f"      [BROADCAST] Sending message event to user {self.current_user.id}")
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'event': 'message',
            **event['message']
        }))

    async def chat_read(self, event):
        print(f"      [BROADCAST] Sending read event to user {self.current_user.id}")
        # Send read status to WebSocket
        await self.send(text_data=json.dumps({
            'event': 'read',
            **event['read']
        }))

    async def chat_typing(self, event):
        print(f"      [BROADCAST] Sending typing event to user {self.current_user.id}")
        # Send typing indicator to WebSocket (but not to the user who is typing)
        if event['typing']['user_id'] != self.current_user.id:
            await self.send(text_data=json.dumps({
                'event': 'typing',
                **event['typing']
            }))

    async def _authenticate_token(self, token: str):
        """Authenticate user via JWT token"""
        if not token:
            print(f"      [AUTH] No token provided")
            return None
        try:
            print(f"      [AUTH] Decoding JWT token...")
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.SIMPLE_JWT.get('ALGORITHM', 'HS256')],
                options={'verify_aud': False}
            )
            print(f"      [AUTH] ✓ Token decoded successfully")
            user_id = payload.get(settings.SIMPLE_JWT.get('USER_ID_CLAIM', 'user_id'))
            if not user_id:
                print(f"      [AUTH] ❌ No user_id in token")
                return None
            print(f"      [AUTH] Fetching user {user_id}...")
            return await self._get_user(user_id)
        except Exception as e:
            print(f"      [AUTH] ❌ JWT decode failed: {str(e)}")
            return None

    async def _get_user(self, user_id):
        """Get user by ID"""
        from asgiref.sync import sync_to_async
        print(f"      [GETUSER] Fetching user {user_id}...")
        try:
            user = await sync_to_async(User.objects.get)(id=user_id)
            print(f"      [GETUSER] ✓ Found: {user.email}")
            return user
        except Exception as e:
            print(f"      [GETUSER] ❌ Not found: {str(e)}")
            raise

    async def _get_user_itinerary(self, itinerary_id, user):
        """Get an itinerary owned by the current user."""
        from asgiref.sync import sync_to_async
        return await sync_to_async(Itinerary.objects.get)(id=itinerary_id, user=user)

    async def _get_or_create_conversation(self, user1, user2, itinerary=None):
        """Get or create conversation between two users"""
        from asgiref.sync import sync_to_async
        
        print(f"      [CONV] Getting or creating conversation...")
        # Normalize order by IDs to avoid duplicates
        uid1, uid2 = sorted([user1.id, user2.id])
        print(f"      [CONV] Normalized IDs: {uid1} <-> {uid2}")
        lookup = {
            'user1_id': uid1,
            'user2_id': uid2,
        }
        if itinerary:
            lookup['itinerary_id'] = itinerary.id
        else:
            lookup['itinerary__isnull'] = True
        defaults = {'itinerary': itinerary} if itinerary else {}
        
        async_get_or_create = sync_to_async(
            lambda: Conversation.objects.get_or_create(
                **lookup,
                defaults=defaults
            )
        )
        
        conversation, created = await async_get_or_create()
        status = "✓ Created" if created else "✓ Found"
        print(f"      [CONV] {status} conversation: {conversation.id}")
        return conversation

    async def _create_message(self, conversation, sender, content):
        """Create a new message"""
        from asgiref.sync import sync_to_async
        
        async_create = sync_to_async(Message.objects.create)
        msg = await async_create(
            conversation=conversation, 
            sender=sender, 
            content=content
        )
        
        # Update conversation's updated_at timestamp
        async_update = sync_to_async(
            Conversation.objects.filter(id=conversation.id).update
        )
        await async_update(updated_at=msg.created_at)
        
        return msg

    async def _mark_messages_read(self, conversation, current_user):
        """Mark messages from other user as read"""
        from asgiref.sync import sync_to_async
        
        async_update = sync_to_async(
            lambda: Message.objects.filter(
                conversation=conversation, 
                is_read=False
            ).exclude(sender=current_user).update(is_read=True)
        )
        
        return await async_update()

    async def _get_recent_messages(self, conversation, limit=50):
        """Get recent messages from conversation"""
        from asgiref.sync import sync_to_async
        
        async_get_messages = sync_to_async(
            lambda: list(
                conversation.messages.all()
                .select_related('sender')
                .order_by('-created_at')[:limit]
            )
        )
        
        messages = await async_get_messages()
        
        # Serialize messages
        return [
            {
                'id': msg.id,
                'content': msg.content,
                'created_at': msg.created_at.isoformat(),
                'is_read': msg.is_read,
                'sender': {
                    'id': msg.sender.id,
                    'email': msg.sender.email,
                    'full_name': msg.sender.full_name,
                    'role': msg.sender.role,
                    'profile_picture': self._get_profile_picture_url(msg.sender),
                }
            }
            for msg in reversed(messages)  # Reverse to get chronological order
        ]
    
    async def _send_message_notification(self, message, conversation):
        """Send push notification for new message"""
        from asgiref.sync import sync_to_async
        
        try:
            # Get recipient asynchronously
            async_get_user1 = sync_to_async(lambda: conversation.user1)
            async_get_user2 = sync_to_async(lambda: conversation.user2)
            
            user1 = await async_get_user1()
            user2 = await async_get_user2()
            
            # Determine recipient
            recipient = user1 if user2.id == message.sender.id else user2
            
            print(f"🔔 Sending chat notification to user {recipient.id} ({recipient.email})")
            
            async_send_notification = sync_to_async(
                firebase_admin_service.send_chat_message_notification
            )
            
            result = await async_send_notification(message, conversation)
            print(f"🔔 Chat notification result: {result}")
            
        except Exception as e:
            # Log error but don't fail the message sending
            print(f"❌ Failed to send push notification: {str(e)}")
            import traceback
            traceback.print_exc()
    
    async def _send_conversation_update(self, recipient, message, conversation):
        """Send real-time update to conversation list for recipient"""
        try:
            # Get unread count for this conversation
            unread_count = await self._get_conversation_unread_count(conversation, recipient)
            
            await self.channel_layer.group_send(
                f"chat_updates_{recipient.id}",
                {
                    'type': 'new_message_update',
                    'conversation_id': conversation.id,
                    'message': {
                        'id': message.id,
                        'content': message.content,
                        'created_at': message.created_at.isoformat(),
                        'sender': {
                            'id': message.sender.id,
                            'full_name': message.sender.full_name,
                            'role': message.sender.role,
                            'profile_picture': self._get_profile_picture_url(message.sender),
                        }
                    },
                    'unread_count': unread_count,
                    'is_first_time': conversation.is_first_time
                }
            )
        except Exception as e:
            print(f"Failed to send conversation update: {str(e)}")
    
    async def _get_conversation_unread_count(self, conversation, user):
        """Get unread message count for a conversation"""
        from asgiref.sync import sync_to_async
        
        async_count = sync_to_async(
            lambda: conversation.messages.filter(
                is_read=False
            ).exclude(sender=user).count()
        )
        
        return await async_count()
    
    async def _send_conversation_read_update(self, user, conversation):
        """Send conversation read update to user's conversation list"""
        try:
            unread_count = await self._get_conversation_unread_count(conversation, user)
            
            await self.channel_layer.group_send(
                f"chat_updates_{user.id}",
                {
                    'type': 'conversation_read_update',
                    'conversation_id': conversation.id,
                    'unread_count': unread_count,
                    'read_by': {
                        'id': user.id,
                        'full_name': user.full_name
                    }
                }
            )
        except Exception as e:
            print(f"Failed to send conversation read update: {str(e)}")
    
    def _get_profile_picture_url(self, user):
        """Get profile picture URL for user"""
        if user.profile_picture and hasattr(user.profile_picture, 'url'):
            # Return full URL if profile picture exists
            return user.profile_picture.url
        return None
    
    async def _handle_first_message(self, conversation):
        """Handle first message logic - set is_first_time to False"""
        if conversation.is_first_time:
            from asgiref.sync import sync_to_async
            
            async_update = sync_to_async(
                lambda: Conversation.objects.filter(id=conversation.id).update(is_first_time=False)
            )
            await async_update()
            
            conversation.is_first_time = False
