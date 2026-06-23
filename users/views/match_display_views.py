from collections import Counter
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from users.models import SeekerRequest, Itinerary, TravelSegment, Match
import logging

logger = logging.getLogger(__name__)


class MatchesView(APIView):
    """
    Unified endpoint to get all matches for the current user
    Returns all matches regardless of type (provider-seeker, provider-provider, seeker-seeker)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get all matches where user is involved - fetched from database"""
        try:
            # Optional filter by match_type
            match_type_filter = request.query_params.get('match_type')

            # Get all active matches where user is involved
            matches_query = Match.objects.filter(
                Q(user1=request.user) | Q(user2=request.user),
                status='active',
                expires_at__gt=timezone.now()
            )

            # Filter by match type if provided
            if match_type_filter:
                matches_query = matches_query.filter(match_type=match_type_filter)

            matches = matches_query.select_related(
                'user1',
                'user2',
                'provider_itinerary',
                'provider_itinerary__user',
                'provider_segment',
                'seeker_request',
                'seeker_request__user',
                'matched_provider_itinerary',
                'matched_provider_itinerary__user',
                'matched_provider_segment',
                'matched_seeker_request',
                'matched_seeker_request__user'
            ).prefetch_related(
                'provider_itinerary__segments',
                'matched_provider_itinerary__segments'
            ).order_by('-created_at')

            # Filter out matches where itineraries have crossed departure dates
            today = timezone.localdate()
            valid_matches = []
            for match in matches:
                skip_match = False
                
                # Check provider_itinerary
                if match.provider_itinerary:
                    latest_departure_to = match.provider_itinerary.segments.values_list(
                        'departure_date_to', flat=True
                    ).order_by('-departure_date_to').first()
                    if latest_departure_to and latest_departure_to < today:
                        skip_match = True
                
                # Check matched_provider_itinerary
                if match.matched_provider_itinerary:
                    latest_departure_to = match.matched_provider_itinerary.segments.values_list(
                        'departure_date_to', flat=True
                    ).order_by('-departure_date_to').first()
                    if latest_departure_to and latest_departure_to < today:
                        skip_match = True

                if not skip_match:
                    valid_matches.append(match)

            # Deduplicate: keep only the most recent match per unique pair
            seen_pairs = set()
            deduped_matches = []
            for match in valid_matches:
                if match.match_type == 'provider_provider':
                    pair_key = (
                        'provider_provider',
                        frozenset([
                            match.provider_itinerary_id,
                            match.matched_provider_itinerary_id
                        ])
                    )
                elif match.match_type == 'provider_seeker':
                    pair_key = (
                        'provider_seeker',
                        match.provider_itinerary_id,
                        match.seeker_request_id
                    )
                else:
                    pair_key = (
                        'seeker_seeker',
                        frozenset([
                            match.seeker_request_id,
                            match.matched_seeker_request_id
                        ])
                    )
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    deduped_matches.append(match)

            matches = deduped_matches

            matches_data = []
            type_counter = Counter()
            quality_counter = Counter()
            available_types = ['provider_seeker', 'provider_provider', 'seeker_seeker']
            available_qualities = ['exact', 'partial']

            for match in matches:
                type_counter[match.match_type] += 1
                quality_counter[match.match_quality] += 1

                other_user = match.user2 if match.user1 == request.user else match.user1
                other_languages = list(other_user.languages.values_list('name', flat=True))

                provider_segment = match.provider_segment
                matched_provider_segment = match.matched_provider_segment

                # Base route & dates
                route = match.route
                departure_date_from = match.departure_date_from.isoformat() if match.departure_date_from else None
                departure_date_to = match.departure_date_to.isoformat() if match.departure_date_to else None

                # Time windows preference
                departure_time_from = None
                departure_time_to = None
                if provider_segment:
                    departure_time_from = provider_segment.departure_time_from.isoformat() if provider_segment.departure_time_from else None
                    departure_time_to = provider_segment.departure_time_to.isoformat() if provider_segment.departure_time_to else None
                elif matched_provider_segment:
                    departure_time_from = matched_provider_segment.departure_time_from.isoformat() if matched_provider_segment.departure_time_from else None
                    departure_time_to = matched_provider_segment.departure_time_to.isoformat() if matched_provider_segment.departure_time_to else None

                # Helper builders
                def build_itinerary_payload(itinerary):
                    if not itinerary:
                        return None
                    return {
                        'id': itinerary.id,
                        'title': itinerary.title,
                        'owner_id': itinerary.user_id,
                        'owner_full_name': itinerary.user.full_name,
                        'owner_email': itinerary.user.email,
                        'owner_is_current_user': itinerary.user_id == request.user.id
                    }

                def build_request_payload(request_obj):
                    if not request_obj:
                        return None
                    return {
                        'id': request_obj.id,
                        'title': request_obj.title,
                        'owner_id': request_obj.user_id,
                        'owner_full_name': request_obj.user.full_name,
                        'owner_email': request_obj.user.email,
                        'owner_is_current_user': request_obj.user_id == request.user.id
                    }

                entities = {
                    'provider_itinerary': build_itinerary_payload(match.provider_itinerary),
                    'matched_provider_itinerary': build_itinerary_payload(match.matched_provider_itinerary),
                    'seeker_request': build_request_payload(match.seeker_request),
                    'matched_seeker_request': build_request_payload(match.matched_seeker_request),
                    'provider_segment_id': provider_segment.id if provider_segment else None,
                    'matched_provider_segment_id': matched_provider_segment.id if matched_provider_segment else None
                }

                # Determine contextual roles for clarity
                current_user_roles = []
                matched_user_roles = []

                if entities['provider_itinerary'] and entities['provider_itinerary']['owner_is_current_user']:
                    current_user_roles.append('provider_itinerary_owner')
                if entities['matched_provider_itinerary'] and entities['matched_provider_itinerary']['owner_is_current_user']:
                    current_user_roles.append('matched_provider_itinerary_owner')
                if entities['seeker_request'] and entities['seeker_request']['owner_is_current_user']:
                    current_user_roles.append('seeker_request_owner')
                if entities['matched_seeker_request'] and entities['matched_seeker_request']['owner_is_current_user']:
                    current_user_roles.append('matched_seeker_request_owner')

                if entities['provider_itinerary'] and entities['provider_itinerary']['owner_id'] == other_user.id:
                    matched_user_roles.append('provider_itinerary_owner')
                if entities['matched_provider_itinerary'] and entities['matched_provider_itinerary']['owner_id'] == other_user.id:
                    matched_user_roles.append('matched_provider_itinerary_owner')
                if entities['seeker_request'] and entities['seeker_request']['owner_id'] == other_user.id:
                    matched_user_roles.append('seeker_request_owner')
                if entities['matched_seeker_request'] and entities['matched_seeker_request']['owner_id'] == other_user.id:
                    matched_user_roles.append('matched_seeker_request_owner')

                if not current_user_roles:
                    current_user_roles.append('observer')
                if not matched_user_roles:
                    matched_user_roles.append('participant')

                layovers = []
                if provider_segment and provider_segment.layovers:
                    layovers = provider_segment.layovers
                elif matched_provider_segment and matched_provider_segment.layovers:
                    layovers = matched_provider_segment.layovers

                match_details = {
                    'route': route,
                    'layovers': layovers,
                    'dates': {
                        'from': departure_date_from,
                        'to': departure_date_to
                    },
                    'times': {
                        'from': departure_time_from,
                        'to': departure_time_to
                    },
                    'entities': entities,
                    'roles': {
                        'current_user': current_user_roles,
                        'matched_user': matched_user_roles
                    }
                }

                current_itinerary_id = None
                if match.provider_itinerary and match.provider_itinerary.user_id == request.user.id:
                    current_itinerary_id = match.provider_itinerary.id
                elif match.matched_provider_itinerary and match.matched_provider_itinerary.user_id == request.user.id:
                    current_itinerary_id = match.matched_provider_itinerary.id

                chat_connection = {
                    'websocket_url': (
                        f"ws://localhost:8000/ws/chat/{other_user.id}/itinerary/{current_itinerary_id}/"
                        if current_itinerary_id
                        else f"ws://localhost:8000/ws/chat/{other_user.id}/"
                    ),
                    'group_name': f"chat_updates_{other_user.id}",
                    'other_user_id': other_user.id,
                    'itinerary_id': current_itinerary_id,
                    'requires_token': True,
                    'token_param': 'token'
                }

                matches_data.append({
                    'match_id': match.id,
                    'match_type': match.match_type,
                    'match_quality': match.match_quality,
                    'status': match.status,
                    'created_at': match.created_at.isoformat() if match.created_at else None,
                    'expires_at': match.expires_at.isoformat() if match.expires_at else None,
                    'matched_user': {
                        'id': other_user.id,
                        'full_name': other_user.full_name,
                        'email': other_user.email,
                        'phonenumber': other_user.phonenumber,
                        'role': other_user.role,
                        'profile_picture': (other_user.profile_picture.url if other_user.profile_picture else None),
                        'bio': other_user.bio,
                        'languages': other_languages,
                    },
                    'match_details': match_details,
                    'chat_connection': chat_connection
                })

            # Ensure all possible types/qualities are represented in summary
            for match_type in available_types:
                if match_type not in type_counter:
                    type_counter[match_type] = 0
            for quality in available_qualities:
                if quality not in quality_counter:
                    quality_counter[quality] = 0

            summary = {
                'total_matches': len(matches_data),
                'by_type': dict(type_counter),
                'by_quality': dict(quality_counter),
                'filters': {
                    'requested_match_type': match_type_filter or 'all'
                }
            }

            return Response({
                'summary': summary,
                'matches': matches_data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting matches: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return Response({'error': 'Failed to get matches'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
