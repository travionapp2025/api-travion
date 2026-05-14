from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import models
from django.db.models import Q
from users.models import User, Conversation, Message, ReportedUser, BlockedUser, Itinerary
from django.conf import settings
import json


class ChatConnectionView(APIView):
    """
    Backend endpoint to get WebSocket connection information for Flutter
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Get or create chat connection info with another user
        POST /api/users/chat/connect/
        Body: {"other_user_id": 123}
        """
        try:
            other_user_id = request.data.get('other_user_id')
            itinerary_id = request.data.get('itinerary_id') or request.query_params.get('itinerary_id')
            
            if not other_user_id:
                return Response(
                    {'error': 'other_user_id is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            if str(other_user_id) == str(request.user.id):
                return Response(
                    {'error': 'Cannot chat with yourself'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                other_user = User.objects.get(id=other_user_id)
            except User.DoesNotExist:
                return Response(
                    {'error': 'User not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )

            itinerary = None
            if itinerary_id:
                try:
                    itinerary = Itinerary.objects.get(id=itinerary_id, user=request.user)
                except (Itinerary.DoesNotExist, ValueError):
                    return Response(
                        {'error': 'Itinerary not found or does not belong to you'},
                        status=status.HTTP_404_NOT_FOUND
                    )

            # Check if there's an active reporting restriction
            if ReportedUser.has_active_restriction(request.user, other_user):
                return Response(
                    {'error': 'Messaging temporarily restricted due to recent report'}, 
                    status=status.HTTP_403_FORBIDDEN
                )

            # Find existing conversation first (to avoid creating before limit check)
            uid1, uid2 = sorted([request.user.id, other_user.id])
            conversation_filters = dict(
                user1_id=uid1,
                user2_id=uid2,
            )
            if itinerary:
                conversation_filters['itinerary_id'] = itinerary.id
            else:
                conversation_filters['itinerary__isnull'] = True

            conversation = Conversation.objects.filter(**conversation_filters).first()

            created = False
            if not conversation:
                existing_used_conversation = Conversation.objects.filter(
                    Q(user1_id=request.user.id) | Q(user2_id=request.user.id),
                    is_first_time=False,
                    **({'itinerary_id': itinerary.id} if itinerary else {})
                ).exists()

                if existing_used_conversation:
                    has_paid_itinerary = itinerary.is_paid if itinerary else Itinerary.objects.filter(user=request.user, is_paid=True).exists()
                    if not has_paid_itinerary:
                        return Response(
                            {
                                'error': 'payment_required',
                                'message': 'First chat is free. Additional chats require a paid itinerary.'
                            },
                            status=status.HTTP_402_PAYMENT_REQUIRED
                        )

                conversation = Conversation.objects.create(
                    user1_id=uid1,
                    user2_id=uid2,
                    itinerary=itinerary
                )
                created = True

            # Get recent messages (last 50)
            recent_messages = Message.objects.filter(
                conversation=conversation
            ).select_related('sender').order_by('-created_at')[:50]

            messages_data = []
            for msg in reversed(recent_messages):  # Reverse for chronological order
                messages_data.append({
                    'id': msg.id,
                    'content': msg.content,
                    'created_at': msg.created_at.isoformat(),
                    'is_read': msg.is_read,
                    'sender': {
                        'id': msg.sender.id,
                        'email': msg.sender.email,
                        'full_name': msg.sender.full_name,
                        'role': msg.sender.role,
                        'profile_picture': msg.sender.profile_picture.url if msg.sender.profile_picture else None,
                    }
                })

            # Get unread count
            unread_count = Message.objects.filter(
                conversation=conversation,
                is_read=False
            ).exclude(sender=request.user).count()

            ws_url = f"ws://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS != ['*'] else 'localhost:8000'}/ws/chat/{other_user_id}/"
            if itinerary:
                ws_url = f"ws://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS != ['*'] else 'localhost:8000'}/ws/chat/{other_user_id}/itinerary/{itinerary.id}/"

            # Prepare other user data
            other_user_data = {
                'id': other_user.id,
                'email': other_user.email,
                'full_name': other_user.full_name,
                'role': other_user.role,
                'profile_picture': other_user.profile_picture.url if other_user.profile_picture else None,
                'bio': other_user.bio
            }

            return Response({
                'connection_info': {
                    'websocket_url': ws_url,
                    'conversation_id': conversation.id,
                    'other_user_id': other_user_id,
                    'itinerary_id': itinerary.id if itinerary else None,
                    'requires_token': True,
                    'token_param': 'token'
                },
                'other_user': other_user_data,
                'conversation': {
                    'id': conversation.id,
                    'created_at': conversation.created_at.isoformat(),
                    'updated_at': conversation.updated_at.isoformat(),
                    'is_new': created,
                    'unread_count': unread_count,
                    'recent_messages': messages_data
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': 'Failed to establish chat connection', 'detail': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChatConversationsView(APIView):
    """
    Get all conversations for the current user
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        GET /api/users/chat/conversations/
        Returns all conversations with connection info
        """
        try:
            # Get all conversations for the user
            conversations = Conversation.objects.filter(
                Q(user1=request.user) | Q(user2=request.user)
            ).select_related('user1', 'user2', 'itinerary').order_by('-updated_at')

            conversations_data = []
            for conv in conversations:
                # Determine the other user
                other_user = conv.user2 if conv.user1 == request.user else conv.user1
                
                # Check if there's a block relationship between the users
                # If either user has blocked the other, exclude this conversation
                is_blocked = BlockedUser.objects.filter(
                    models.Q(blocker=request.user, blocked=other_user) |
                    models.Q(blocker=other_user, blocked=request.user)
                ).exists()
                
                if is_blocked:
                    continue  # Skip this conversation
                
                # Get last message
                last_message = conv.messages.order_by('-created_at').first()
                
                # Get unread count
                unread_count = conv.messages.filter(
                    is_read=False
                ).exclude(sender=request.user).count()

                # Build WebSocket URL
                ws_url = f"ws://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS != ['*'] else 'localhost:8000'}/ws/chat/{other_user.id}/"
                if conv.itinerary_id:
                    ws_url = f"ws://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS != ['*'] else 'localhost:8000'}/ws/chat/{other_user.id}/itinerary/{conv.itinerary_id}/"

                # Prepare other user data
                other_user_data = {
                    'id': other_user.id,
                    'email': other_user.email,
                    'full_name': other_user.full_name,
                    'role': other_user.role,
                    'profile_picture': other_user.profile_picture.url if other_user.profile_picture else None
                }

                conversations_data.append({
                    'conversation_id': conv.id,
                    'other_user': other_user_data,
                    'connection_info': {
                        'websocket_url': ws_url,
                        'other_user_id': other_user.id,
                        'itinerary_id': conv.itinerary_id,
                        'requires_token': True
                    },
                    'last_message': {
                        'id': last_message.id,
                        'content': last_message.content,
                        'created_at': last_message.created_at.isoformat(),
                        'sender_id': last_message.sender.id,
                        'sender_name': last_message.sender.full_name
                    } if last_message else None,
                    'unread_count': unread_count,
                    'itinerary_id': conv.itinerary_id,
                    'is_first_time': conv.is_first_time,
                    'updated_at': conv.updated_at.isoformat()
                })

            return Response({
                'conversations': conversations_data,
                'count': len(conversations_data),
                'real_time_updates': {
                    'websocket_url': f"ws://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS != ['*'] else 'localhost:8000'}/ws/chat-updates/",
                    'requires_token': True,
                    'token_param': 'token'
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': 'Failed to get conversations', 'detail': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChatMessageHistoryView(APIView):
    """
    Get message history for a specific conversation
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        """
        GET /api/users/chat/conversations/{conversation_id}/messages/
        Optimized with cursor-based pagination and database indexing
        """
        try:
            # Get conversation with optimized query
            try:
                conversation = Conversation.objects.select_related('user1', 'user2').get(id=conversation_id)
            except Conversation.DoesNotExist:
                return Response(
                    {'error': 'Conversation not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check if user is part of this conversation
            if request.user.id not in [conversation.user1_id, conversation.user2_id]:
                return Response(
                    {'error': 'Not authorized for this conversation'}, 
                    status=status.HTTP_403_FORBIDDEN
                )

            # Get pagination parameters with improved defaults
            limit = min(int(request.query_params.get('limit', 30)), 1000)  # Max 1000, default 20
            
            cursor = request.query_params.get('cursor')  
            messages_query = Message.objects.filter(
                conversation=conversation
            ).select_related('sender').order_by('-created_at')
            
            if cursor:
                try:
                    cursor_msg = Message.objects.get(id=cursor)
                    messages_query = messages_query.filter(created_at__lt=cursor_msg.created_at)
                except Message.DoesNotExist:
                    pass 
            
            # Get messages with limit
            messages = messages_query[:limit + 1]  # Get one extra to check if there are more
            
            # Check if there are more messages
            has_more = len(messages) > limit
            if has_more:
                messages = messages[:limit]  # Remove the extra message

            messages_data = []
            for msg in reversed(messages):  # Reverse for chronological order
                messages_data.append({
                    'id': msg.id,
                    'content': msg.content,
                    'created_at': msg.created_at.isoformat(),
                    'is_read': msg.is_read,
                    'sender': {
                        'id': msg.sender.id,
                        'email': msg.sender.email,
                        'full_name': msg.sender.full_name,
                        'role': msg.sender.role,
                        'profile_picture': msg.sender.profile_picture.url if msg.sender.profile_picture else None,
                    }
                })

            # Mark messages as read (from other user) - optimized with bulk update
            if messages_data:
                Message.objects.filter(
                    conversation=conversation,
                    is_read=False
                ).exclude(sender=request.user).update(is_read=True)

            # Calculate next cursor for pagination
            next_cursor = messages_data[-1]['id'] if messages_data and has_more else None

            return Response({
                'messages': messages_data,
                'conversation_id': conversation_id,
                'itinerary_id': conversation.itinerary_id,
                'count': len(messages_data),
                'has_more': has_more,
                'next_cursor': next_cursor,
                'is_first_time': conversation.is_first_time
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': 'Failed to get message history', 'detail': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChatUsersView(APIView):
    """
    Get list of users that can be chatted with (from itinerary matches)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        GET /api/users/chat/users/
        Returns users from recent itinerary matches or all users
        """
        try:
            # Get users from recent itinerary matches
            from users.models import TravelSegment
            
            # Get user's recent itineraries
            user_itineraries = request.user.itineraries.all()[:10]  # Last 10
            
            matching_users = set()
            for itinerary in user_itineraries:
                for segment in itinerary.segments.all():
                    matching_segments = TravelSegment.objects.filter(
                        from_airport=segment.from_airport,
                        to_airport=segment.to_airport
                    ).exclude(itinerary__user=request.user)
                    
                    for seg in matching_segments:
                        matching_users.add(seg.itinerary.user.id)

            # Get user objects
            if matching_users:
                users = User.objects.filter(id__in=list(matching_users))
            else:
                users = User.objects.exclude(id=request.user.id)[:20]

            users_data = []
            for user in users:
                users_data.append({
                    'id': user.id,
                    'email': user.email,
                    'full_name': user.full_name,
                    'role': user.role,
                    'profile_picture': user.profile_picture.url if user.profile_picture else None,
                    'bio': user.bio,
                    'connection_info': {
                        'websocket_url': f"ws://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS != ['*'] else 'localhost:8000'}/ws/chat/{user.id}/",
                        'other_user_id': user.id,
                        'requires_token': True
                    }
                })

            return Response({
                'users': users_data,
                'count': len(users_data),
                'source': 'itinerary_matches' if matching_users else 'all_users'
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': 'Failed to get chat users', 'detail': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
