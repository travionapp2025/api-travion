from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Max, Min, Q
from users.models import Itinerary, Match
import logging

logger = logging.getLogger(__name__)


class MyTripsView(APIView):
    """
    Get user's trips (itineraries) with matches and chat connection URLs
    Delete user's trips with associated matches
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get all user's itineraries with their matches, or a specific itinerary if itinerary_id is provided"""
        try:
            # Check if specific itinerary is requested
            itinerary_id = request.query_params.get('itinerary_id')
            
            if itinerary_id:
                try:
                    itineraries = Itinerary.objects.filter(
                        id=itinerary_id,
                        user=request.user
                    ).select_related('user').prefetch_related('segments').annotate(
                        earliest_departure_date_from=Min('segments__departure_date_from'),
                        latest_departure_date_to=Max('segments__departure_date_to')
                    )
                    
                    if not itineraries.exists():
                        return Response(
                            {'error': 'Itinerary not found or does not belong to you'}, 
                            status=status.HTTP_404_NOT_FOUND
                        )
                except ValueError:
                    return Response(
                        {'error': 'Invalid itinerary_id format'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                itineraries = Itinerary.objects.filter(
                    user=request.user
                ).select_related('user').prefetch_related('segments').annotate(
                    earliest_departure_date_from=Min('segments__departure_date_from'),
                    latest_departure_date_to=Max('segments__departure_date_to')
                ).order_by('-earliest_departure_date_from', '-created_at')
            
            trips_data = []
            today = timezone.localdate()
            
            for itinerary in itineraries:
                latest_departure_date_to = itinerary.latest_departure_date_to
                is_departure_date_to_crossed = (
                    latest_departure_date_to is not None and latest_departure_date_to < today
                )

                matches = Match.objects.filter(
                    status='active',
                    expires_at__gt=timezone.now()
                ).filter(
                    (Q(user1=request.user) | Q(user2=request.user)) &
                    (
                        Q(provider_itinerary=itinerary) | 
                        Q(matched_provider_itinerary=itinerary)
                    )
                ).select_related(
                    'user1', 'user2', 'provider_itinerary', 'seeker_request',
                    'matched_provider_itinerary', 'provider_segment', 'matched_provider_segment'
                ).order_by('-created_at')
                
                matched_users = []
                for match in matches:
                    # Get the other user (not the current user)
                    other_user = match.user2 if match.user1 == request.user else match.user1
                    
                    # Get match details based on match type
                    match_info = {
                        'match_id': match.id,
                        'match_type': match.match_type,
                        'match_quality': match.match_quality,
                        'route': match.route,
                        'departure_date_from': match.departure_date_from.isoformat(),
                        'departure_date_to': match.departure_date_to.isoformat(),
                        'created_at': match.created_at.isoformat(),
                    }
                    
                    # Add match type specific info
                    if match.match_type == 'provider_seeker':
                        if match.provider_itinerary == itinerary:
                            # Current user is provider
                            match_info['matched_user_type'] = 'seeker'
                            match_info['matched_seeker_request_id'] = match.seeker_request.id if match.seeker_request else None
                        else:
                            # Current user is seeker
                            match_info['matched_user_type'] = 'provider'
                            match_info['matched_provider_itinerary_id'] = match.provider_itinerary.id if match.provider_itinerary else None
                    
                    elif match.match_type == 'provider_provider':
                        if match.provider_itinerary == itinerary:
                            # Current user's itinerary
                            match_info['matched_user_type'] = 'provider'
                            match_info['matched_provider_itinerary_id'] = match.matched_provider_itinerary.id if match.matched_provider_itinerary else None
                        else:
                            # Other provider's itinerary
                            match_info['matched_user_type'] = 'provider'
                            match_info['matched_provider_itinerary_id'] = match.provider_itinerary.id if match.provider_itinerary else None
                    
                    elif match.match_type == 'seeker_seeker':
                        match_info['matched_user_type'] = 'seeker'
                        if match.seeker_request and match.seeker_request.user == request.user:
                            match_info['matched_seeker_request_id'] = match.matched_seeker_request.id if match.matched_seeker_request else None
                        else:
                            match_info['matched_seeker_request_id'] = match.seeker_request.id if match.seeker_request else None
                    
                    # Avoid duplicates
                    if not any(u['id'] == other_user.id for u in matched_users):
                        matched_users.append({
                            'id': other_user.id,
                            'full_name': other_user.full_name,
                            'email': other_user.email,
                            'phonenumber': other_user.phonenumber,
                            'role': other_user.role,
                            'profile_picture': (other_user.profile_picture.url if other_user.profile_picture else None),
                            'bio': other_user.bio,
                            'languages': [lang.name for lang in other_user.languages.all()],
                            'match_info': match_info,
                            'chat_connection': {
                                'websocket_url': f"ws://localhost:8000/ws/chat/{other_user.id}/itinerary/{itinerary.id}/",
                                'other_user_id': other_user.id,
                                'itinerary_id': itinerary.id,
                                'requires_token': True,
                                'token_param': 'token'
                            }
                        })
                
                # Build itinerary data
                def format_layovers(layovers):
                    if not layovers:
                        return []
                    formatted = []
                    for layover in layovers:
                        if isinstance(layover, dict):
                            code = layover.get('airport')
                        else:
                            code = layover
                        if not code:
                            continue
                        formatted.append(str(code).strip().upper())
                    return formatted

                segments_data = []
                for segment in itinerary.segments.all():
                    segments_data.append({
                        'id': segment.id,
                        'from_airport': segment.from_airport,
                        'to_airport': segment.to_airport,
                        'route': segment.route,
                        'departure_date_from': segment.departure_date_from.isoformat(),
                        'departure_date_to': segment.departure_date_to.isoformat(),
                        'departure_time_from': segment.departure_time_from.isoformat() if segment.departure_time_from else None,
                        'departure_time_to': segment.departure_time_to.isoformat() if segment.departure_time_to else None,
                        'airline': segment.airline,
                        'flight_number': segment.flight_number,
                        'segment_order': segment.segment_order,
                        'layovers': format_layovers(segment.layovers),
                    })
                
                trips_data.append({
                    'id': itinerary.id,
                    'title': itinerary.title,
                    'travel_type': itinerary.travel_type,
                    'is_available': itinerary.is_available,
                    'is_departure_date_to_crossed': is_departure_date_to_crossed,
                    'created_at': itinerary.created_at.isoformat(),
                    'updated_at': itinerary.updated_at.isoformat(),
                    'segments': segments_data,
                    'total_segments': len(segments_data),
                    'matched_users': matched_users,
                    'total_matches': len(matched_users),
                })
            
            # If specific itinerary was requested, return just that trip
            if itinerary_id:
                return Response({
                    'trip': trips_data[0] if trips_data else None,
                }, status=status.HTTP_200_OK)
            
            # Otherwise return all trips
            return Response({
                'trips': trips_data,
                'total_trips': len(trips_data),
                'total_matches': sum(trip['total_matches'] for trip in trips_data)
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting my trips: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return Response({'error': 'Failed to get trips'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request):
        """Delete a trip (itinerary) and all associated matches"""
        try:
            itinerary_id = request.data.get('itinerary_id') or request.query_params.get('itinerary_id')
            
            if not itinerary_id:
                return Response(
                    {'error': 'itinerary_id is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get the itinerary (ensure it belongs to the user)
            try:
                itinerary = Itinerary.objects.get(id=itinerary_id, user=request.user)
            except Itinerary.DoesNotExist:
                return Response(
                    {'error': 'Itinerary not found or does not belong to you'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Delete all matches associated with this itinerary
            deleted_matches = Match.objects.filter(
                Q(provider_itinerary=itinerary) | Q(matched_provider_itinerary=itinerary)
            ).delete()
            
            # Delete the itinerary (segments will cascade delete)
            itinerary_title = itinerary.title
            itinerary.delete()
            
            logger.info(f"🗑️ Trip '{itinerary_title}' (ID: {itinerary_id}) deleted by user {request.user.id}, along with {deleted_matches[0]} matches")
            
            return Response({
                'message': 'Trip and associated matches deleted successfully',
                'deleted_itinerary_id': int(itinerary_id),
                'deleted_matches': deleted_matches[0]
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error deleting trip: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return Response({'error': 'Failed to delete trip'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

