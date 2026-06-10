import json
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import ValidationError
from users.models import Itinerary, TravelSegment, Match
from users.services.matching_service import MatchingService
from datetime import datetime
from django.utils import timezone
from django.db.models import Q
import logging

logger = logging.getLogger(__name__)


def _format_layovers(layovers):
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


class ItineraryListView(APIView):
    """
    API view to list user's itineraries and create new ones
    """
    permission_classes = [IsAuthenticated]

    def _parse_bool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ['true', '1', 'yes', 'on']
        if isinstance(value, int):
            return value != 0
        return False

    def get_permissions(self):
        if self.request.method == 'POST':
            return []
        return [permission() for permission in self.permission_classes]

    def _check_duplicate_itinerary(self, user, segments_data):
        """
        Check if an identical itinerary already exists for the user.
        Returns the existing itinerary if found, None otherwise.
        """
        # Get all itineraries for this user
        user_itineraries = Itinerary.objects.filter(user=user).prefetch_related('segments')
        
        # Normalize the new segments data for comparison
        new_segments_normalized = []
        for seg in segments_data:
            try:
                from_airport = seg.get('from_airport', '').upper()
                to_airport = seg.get('to_airport', '').upper()
                departure_date_from = datetime.strptime(seg['departure_date_from'], '%Y-%m-%d').date()
                airline = (seg.get('airline', '') or '').upper()
                flight_number = (seg.get('flight_number', '') or '').upper()
                
                new_segments_normalized.append({
                    'from_airport': from_airport,
                    'to_airport': to_airport,
                    'departure_date_from': departure_date_from,
                    'airline': airline,
                    'flight_number': flight_number,
                    'layovers': sorted(self._sanitize_layovers(seg.get('layovers')))
                })
            except (ValueError, KeyError) as e:
                logger.error(f"Error normalizing segment for duplicate check: {str(e)}")
                continue
        
        if not new_segments_normalized:
            return None
        
        # Check each existing itinerary
        for existing_itinerary in user_itineraries:
            existing_segments = list(existing_itinerary.segments.all().order_by('segment_order'))
            
            # Must have same number of segments
            if len(existing_segments) != len(new_segments_normalized):
                continue
            
            # Check if all segments match
            is_duplicate = True
            for i, new_seg in enumerate(new_segments_normalized):
                if i >= len(existing_segments):
                    is_duplicate = False
                    break
                
                existing_seg = existing_segments[i]
                
                # Check airports
                if (existing_seg.from_airport.upper() != new_seg['from_airport'] or 
                    existing_seg.to_airport.upper() != new_seg['to_airport']):
                    is_duplicate = False
                    break
                
                # Check departure date (within 1 day tolerance)
                date_diff = abs((existing_seg.departure_date_from - new_seg['departure_date_from']).days)
                if date_diff > 1:
                    is_duplicate = False
                    break
                
                # If airline/flight number is provided, check it matches
                if new_seg['airline'] and existing_seg.airline:
                    if existing_seg.airline.upper() != new_seg['airline']:
                        is_duplicate = False
                        break
                
                if new_seg['flight_number'] and existing_seg.flight_number:
                    if existing_seg.flight_number.upper() != new_seg['flight_number']:
                        is_duplicate = False
                        break

                existing_layovers = sorted(self._sanitize_layovers(existing_seg.layovers or []))
                if existing_layovers != new_seg['layovers']:
                    is_duplicate = False
                    break

            if is_duplicate:
                logger.info(f"🔍 Duplicate itinerary found for user {user.id}: existing itinerary {existing_itinerary.id}")
                return existing_itinerary
        
        return None

    def _search_matches_from_segments(self, segments_data, user=None):
        matches = []
        user_id = user.id if user and user.is_authenticated else None
        for segment_data in segments_data:
            from_airport = segment_data['from_airport'].upper()
            to_airport = segment_data['to_airport'].upper()
            departure_date_from = datetime.strptime(segment_data['departure_date_from'], '%Y-%m-%d').date()
            departure_date_to = datetime.strptime(segment_data['departure_date_to'], '%Y-%m-%d').date()

            provider_segments = TravelSegment.objects.filter(
                itinerary__is_available=True,
                from_airport=from_airport,
                to_airport=to_airport,
                departure_date_from__lte=departure_date_to,
                departure_date_to__gte=departure_date_from
            ).select_related('itinerary', 'itinerary__user')

            if user_id:
                provider_segments = provider_segments.exclude(itinerary__user_id=user_id)

            for provider_segment in provider_segments:
                provider_itinerary = provider_segment.itinerary
                provider_user = provider_itinerary.user
                matches.append({
                    'match_type': 'provider',
                    'match_quality': 'exact',
                    'from_airport': provider_segment.from_airport,
                    'to_airport': provider_segment.to_airport,
                    'provider_itinerary_id': provider_itinerary.id,
                    'provider_user_id': provider_user.id,
                    'provider_username': provider_user.full_name,
                    'provider_user': {
                        'id': provider_user.id,
                        'full_name': provider_user.full_name,
                        'email': provider_user.email,
                        'phonenumber': provider_user.phonenumber,
                        'role': provider_user.role,
                        'profile_picture': (provider_user.profile_picture.url if provider_user.profile_picture else None),
                        'bio': provider_user.bio,
                    }
                })
        return matches

    def get(self, request):
        try:
            user = request.user
            itineraries = Itinerary.objects.filter(user=user).prefetch_related('segments')
            
            itinerary_data = []
            for itinerary in itineraries:
                segments_data = []
                for segment in itinerary.segments.all():
                    segments_data.append({
                        'id': segment.id,
                        'from_airport': segment.from_airport,
                        'to_airport': segment.to_airport,
                        'departure_date_from': segment.departure_date_from,
                        'departure_date_to': segment.departure_date_to,
                        'departure_time_from': segment.departure_time_from,
                        'departure_time_to': segment.departure_time_to,
                        'airline': segment.airline,
                        'flight_number': segment.flight_number,
                        'segment_order': segment.segment_order,
                        'route': segment.route,
                        'layovers': _format_layovers(segment.layovers)
                    })
                
                itinerary_data.append({
                    'id': itinerary.id,
                    'title': itinerary.title,
                    'travel_type': itinerary.travel_type,
                    'is_available': itinerary.is_available,
                    'total_segments': itinerary.total_segments,
                    'departure_date': itinerary.departure_date,
                    "is paid": itinerary.is_paid,
                    'arrival_date': itinerary.arrival_date,
                    'created_at': itinerary.created_at,
                    'updated_at': itinerary.updated_at,
                    'segments': segments_data
                })
            
            return Response({
                'itineraries': itinerary_data,
                'count': len(itinerary_data)
            }, status=status.HTTP_200_OK) 
            
            
        except Exception as e:
            logger.error(f"Error retrieving itineraries for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve itineraries'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request):
        """Create a new itinerary with segments or search for matches without saving"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            is_authenticated = request.user and request.user.is_authenticated

            title = data.get('title', '').strip()
            travel_type = data.get('travel_type', 'one_way')
            is_available = data.get('is_available', True)
            segments_data = data.get('segments', [])
            save_itinerary = self._parse_bool(data.get('save_itinerary', True)) and is_authenticated

            errors = {}

            if is_authenticated and not title:
                errors['title'] = 'Title is required'

            if travel_type not in ['one_way', 'round_trip', 'multi_city']:
                errors['travel_type'] = 'Invalid travel type'

            if not segments_data or len(segments_data) == 0:
                errors['segments'] = 'At least one travel segment is required'

            for i, segment in enumerate(segments_data):
                segment_errors = self._validate_segment(segment, i)
                if segment_errors:
                    errors[f'segment_{i}'] = segment_errors

            if errors:
                return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

            # Anonymous users always get search-only behaviour
            if not is_authenticated:
                matches = self._search_matches_from_segments(segments_data)
                logger.info(f"Anonymous search completed, {len(matches)} matches found.")
                return Response({
                    'message': 'Route search completed successfully!',
                    'status': 'searched',
                    'saved': False,
                    'matching_status': 'completed',
                    'matches': matches
                }, status=status.HTTP_200_OK)

            # Check for duplicate itinerary if saving (toggle is on)
            if save_itinerary:
                existing_itinerary = self._check_duplicate_itinerary(request.user, segments_data)
                if existing_itinerary:
                    logger.warning(f"⚠️ Duplicate itinerary detected for user {request.user.id}. Existing itinerary {existing_itinerary.id}")
                    return Response({
                        'error': 'A duplicate itinerary already exists. Please use the existing itinerary or modify the details.',
                        'existing_itinerary_id': existing_itinerary.id
                    }, status=status.HTTP_400_BAD_REQUEST)

            itinerary = None
            if save_itinerary:
                itinerary = Itinerary(
                    user=request.user,
                    title=title,
                    travel_type=travel_type,
                    is_available=is_available
                )
                itinerary.save()

                segment_objects = []
                for i, segment_data in enumerate(segments_data):
                    departure_date_from = datetime.strptime(segment_data['departure_date_from'], '%Y-%m-%d').date()
                    departure_date_to = datetime.strptime(segment_data['departure_date_to'], '%Y-%m-%d').date()
                    departure_time_from = datetime.strptime(segment_data['departure_time_from'], '%H:%M').time() if segment_data.get('departure_time_from') else None
                    departure_time_to = datetime.strptime(segment_data['departure_time_to'], '%H:%M').time() if segment_data.get('departure_time_to') else None
                    layovers = self._sanitize_layovers(segment_data.get('layovers'))

                    segment = TravelSegment.objects.create(
                        itinerary=itinerary,
                        from_airport=segment_data['from_airport'].upper(),
                        to_airport=segment_data['to_airport'].upper(),
                        departure_date_from=departure_date_from,
                        departure_date_to=departure_date_to,
                        departure_time_from=departure_time_from,
                        departure_time_to=departure_time_to,
                        airline=segment_data.get('airline', ''),
                        flight_number=segment_data.get('flight_number', ''),
                        segment_order=i + 1,
                        layovers=layovers
                    )
                    segment_objects.append(segment)
            else:
                # Authenticated user requested search-only (save_itinerary=false)
                matches = self._search_matches_from_segments(segments_data, request.user)

            # Find matches
            if save_itinerary:
                matches = MatchingService.find_matches_for_new_itinerary(itinerary)
            
            def _serialize_user(user):
                if not user:
                    return None
                return {
                    'id': user.id,
                    'full_name': user.full_name,
                    'email': user.email,
                    'phonenumber': user.phonenumber,
                    'role': user.role,
                    'profile_picture': (user.profile_picture.url if user.profile_picture else None),
                    'bio': user.bio,
                }

            current_user_id = request.user.id if is_authenticated else None

            def _is_current_user(user_id):
                return current_user_id is not None and str(user_id) == str(current_user_id)

            serialized_matches = []
            for match in matches:
                match_type = match.get('match_type')
                from_airport = None
                to_airport = None

                if match_type == 'provider_seeker':
                    seeker_request = match['seeker_request']
                    if _is_current_user(seeker_request.user_id):
                        continue
                    provider_segment = match.get('provider_segment')
                    if provider_segment:
                        from_airport = provider_segment.from_airport
                        to_airport = provider_segment.to_airport
                    else:
                        from_airport = seeker_request.from_airport
                        to_airport = seeker_request.to_airport

                    serialized_matches.append({
                        'match_type': 'seeker',
                        'match_quality':match.get('match_quality'),
                        'from_airport': from_airport,
                        'to_airport': to_airport,
                        'seeker_request_id': seeker_request.id,
                        'seeker_user_id': seeker_request.user.id,
                        'seeker_username': seeker_request.user.full_name,
                        'seeker_user': _serialize_user(seeker_request.user),
                    })
                elif match_type == 'provider':
                    provider_user = match.get('provider_user') or {}
                    provider_user_id = match.get('provider_user_id') or provider_user.get('id')
                    if _is_current_user(provider_user_id):
                        continue
                    serialized_matches.append({
                        'match_type': 'provider',
                        'match_quality': match.get('match_quality'),
                        'from_airport': match.get('from_airport'),
                        'to_airport': match.get('to_airport'),
                        'provider_itinerary_id': match.get('provider_itinerary_id'),
                        'provider_user_id': match.get('provider_user_id'),
                        'provider_username': match.get('provider_username'),
                        'provider_user': match.get('provider_user'),
                    })
                elif match_type == 'provider_provider':
                    matched_itinerary = match['matched_provider_itinerary']
                    if _is_current_user(matched_itinerary.user_id):
                        continue
                    provider_segment = match.get('provider_segment')
                    matched_provider_segment = match.get('matched_provider_segment')

                    if matched_provider_segment:
                        from_airport = matched_provider_segment.from_airport
                        to_airport = matched_provider_segment.to_airport
                    elif provider_segment:
                        from_airport = provider_segment.from_airport
                        to_airport = provider_segment.to_airport

                    serialized_matches.append({
                        'match_type': 'provider',
                        'match_quality':match.get('match_quality'),
                        'from_airport': from_airport,
                        'to_airport': to_airport,
                        'provider_itinerary_id': matched_itinerary.id,
                        'provider_user_id': matched_itinerary.user.id,
                        'provider_username': matched_itinerary.user.full_name,
                        'provider_user': _serialize_user(matched_itinerary.user),
                    })

            if not save_itinerary:
                logger.info(f"🔍 Temporary search completed, {len(serialized_matches)} matches found (not saved).")
                return Response({
                    'message': 'Route search completed successfully!',
                    'status': 'searched',
                    'saved': False,
                    'matching_status': 'completed',
                    'matches': serialized_matches
                }, status=status.HTTP_200_OK)
            else:
                logger.info(f"✅ Itinerary {itinerary.id} created successfully, {len(serialized_matches)} matches found.")
                return Response({
                    'message': 'Itinerary created successfully!',
                    'itinerary_id': itinerary.id,
                    'status': 'created',
                    'saved': True,
                    'matching_status': 'completed',
                    'matches': serialized_matches
                }, status=status.HTTP_201_CREATED)
            
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON data'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({'error': f'Invalid date/time format: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            user_id = request.user.id if (request.user and request.user.is_authenticated) else 'anonymous'
            logger.error(f"Error creating itinerary for user {user_id}: {str(e)}")
            return Response(
                {'error': 'Failed to create itinerary'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _validate_segment(self, segment, index):
        """Validate individual segment data"""
        errors = {}
        
        if not segment.get('from_airport'):
            errors['from_airport'] = 'From airport is required'
        elif len(segment.get('from_airport', '')) != 3:
            errors['from_airport'] = 'Airport code must be 3 characters'
        
        if not segment.get('to_airport'):
            errors['to_airport'] = 'To airport is required'
        elif len(segment.get('to_airport', '')) != 3:
            errors['to_airport'] = 'Airport code must be 3 characters'
        
        if not segment.get('departure_date_from'):
            errors['departure_date_from'] = 'Departure date from is required'
        if not segment.get('departure_date_to'):
            errors['departure_date_to'] = 'Departure date to is required'
        
        try:
            if segment.get('departure_date_from') and segment.get('departure_date_to'):
                dep_from = datetime.strptime(segment['departure_date_from'], '%Y-%m-%d').date()
                dep_to = datetime.strptime(segment['departure_date_to'], '%Y-%m-%d').date()
                
                if dep_from > dep_to:
                    errors['dates'] = 'Departure date from cannot be after departure date to'
        except ValueError:
            errors['date_format'] = 'Invalid date format. Use YYYY-MM-DD'
        
        layover_errors = self._validate_layovers(segment.get('layovers'))
        if layover_errors:
            errors['layovers'] = layover_errors
        
        return errors

    def _validate_layovers(self, layovers):
        if layovers in (None, [], ()):
            return None
        if not isinstance(layovers, list):
            return 'Layovers must be a list of airport codes'
        errors = []
        for idx, layover in enumerate(layovers):
            if isinstance(layover, dict):
                airport = layover.get('airport')
            else:
                airport = layover

            if not airport:
                errors.append(f'Layover #{idx + 1} requires an airport code')
                continue

            airport_code = str(airport).strip().upper()
            if len(airport_code) != 3 or not airport_code.isalpha():
                errors.append(f'Layover #{idx + 1} airport must be a 3-letter code')
        return errors if errors else None

    def _sanitize_layovers(self, layovers):
        if not layovers:
            return []
        sanitized = []
        for layover in layovers:
            if isinstance(layover, dict):
                airport = layover.get('airport')
            else:
                airport = layover

            if not airport:
                continue

            airport_code = str(airport).strip().upper()
            if len(airport_code) != 3 or not airport_code.isalpha():
                continue

            sanitized.append(airport_code)
        return sanitized


class ItineraryDetailView(APIView):
    """
    API view to retrieve, update, or delete a specific itinerary
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, itinerary_id):
        """Get a specific itinerary"""
        try:
            itinerary = Itinerary.objects.get(id=itinerary_id, user=request.user)
            
            segments_data = []
            for segment in itinerary.segments.all():
                segments_data.append({
                    'id': segment.id,
                    'from_airport': segment.from_airport,
                    'to_airport': segment.to_airport,
                    'departure_date_from': segment.departure_date_from,
                    'departure_date_to': segment.departure_date_to,
                    'departure_time_from': segment.departure_time_from,
                    'departure_time_to': segment.departure_time_to,
                    'airline': segment.airline,
                    'flight_number': segment.flight_number,
                    'segment_order': segment.segment_order,
                    'route': segment.route,
                    'layovers': _format_layovers(segment.layovers)
                })
            
            def _serialize_segment(segment):
                if not segment:
                    return None
                return {
                    'id': segment.id,
                    'from_airport': segment.from_airport,
                    'to_airport': segment.to_airport,
                    'departure_date_from': segment.departure_date_from,
                    'departure_date_to': segment.departure_date_to,
                    'departure_time_from': segment.departure_time_from,
                    'departure_time_to': segment.departure_time_to,
                    'airline': segment.airline,
                    'flight_number': segment.flight_number,
                    'route': segment.route,
                    'layovers': _format_layovers(segment.layovers)
                }

            matches = Match.objects.filter(
                status='active',
                expires_at__gt=timezone.now()
            ).filter(
                Q(provider_itinerary=itinerary) | Q(matched_provider_itinerary=itinerary)
            ).select_related(
                'provider_itinerary',
                'provider_itinerary__user',
                'provider_segment',
                'seeker_request',
                'seeker_request__user',
                'matched_provider_itinerary',
                'matched_provider_itinerary__user',
                'matched_provider_segment',
                'user1',
                'user2'
            ).order_by('-created_at')

            serialized_matches = []
            for match in matches:
                match_from_airport = None
                match_to_airport = None
                if match.match_type == 'provider_seeker':
                    seeker_request = match.seeker_request
                    provider_segment = match.provider_segment
                    if provider_segment:
                        match_from_airport = provider_segment.from_airport
                        match_to_airport = provider_segment.to_airport
                    elif seeker_request:
                        match_from_airport = seeker_request.from_airport
                        match_to_airport = seeker_request.to_airport
                    if seeker_request:
                        seeker_user = seeker_request.user
                        serialized_matches.append({
                            'match_id': match.id,
                            'match_type': 'seeker',
                            'match_quality': match.match_quality,
                            'route': match.route,
                            'from_airport': match_from_airport,
                            'to_airport': match_to_airport,
                            'seeker_request': {
                                'id': seeker_request.id,
                                'title': seeker_request.title,
                                'from_airport': seeker_request.from_airport,
                                'to_airport': seeker_request.to_airport,
                                'departure_date_from': seeker_request.departure_date_from,
                                'departure_date_to': seeker_request.departure_date_to,
                                'departure_time_from': seeker_request.departure_time_from,
                                'departure_time_to': seeker_request.departure_time_to,
                                'is_active': seeker_request.is_active,
                                'expires_at': seeker_request.expires_at,
                                'created_at': seeker_request.created_at,
                                'updated_at': seeker_request.updated_at,
                            },
                            'provider_segment': _serialize_segment(provider_segment),
                            'seeker_user': {
                                'id': seeker_user.id,
                                'full_name': seeker_user.full_name,
                                'email': seeker_user.email,
                                'phonenumber': seeker_user.phonenumber,
                                'role': seeker_user.role,
                                'profile_picture': (seeker_user.profile_picture.url if seeker_user.profile_picture else None),
                                'bio': seeker_user.bio,
                            }
                        })
                elif match.match_type == 'provider_provider':
                    matched_itinerary = match.matched_provider_itinerary if match.provider_itinerary == itinerary else match.provider_itinerary
                    matched_segment = match.matched_provider_segment if matched_itinerary == match.matched_provider_itinerary else match.provider_segment
                    if matched_segment:
                        match_from_airport = matched_segment.from_airport
                        match_to_airport = matched_segment.to_airport
                    if matched_itinerary:
                        provider_user = matched_itinerary.user
                        serialized_matches.append({
                            'match_id': match.id,
                            'match_type': 'provider',
                            'match_quality': match.match_quality,
                            'route': match.route,
                            'from_airport': match_from_airport,
                            'to_airport': match_to_airport,
                            'provider_itinerary': {
                                'id': matched_itinerary.id,
                                'title': matched_itinerary.title,
                                'travel_type': matched_itinerary.travel_type,
                                'is_available': matched_itinerary.is_available,
                                'total_segments': matched_itinerary.total_segments,
                                'departure_date': matched_itinerary.departure_date,
                                'arrival_date': matched_itinerary.arrival_date,
                                'created_at': matched_itinerary.created_at,
                                'updated_at': matched_itinerary.updated_at,
                            },
                            'matched_segment': _serialize_segment(matched_segment),
                            'provider_user': {
                                'id': provider_user.id,
                                'full_name': provider_user.full_name,
                                'email': provider_user.email,
                                'phonenumber': provider_user.phonenumber,
                                'role': provider_user.role,
                                'profile_picture': (provider_user.profile_picture.url if provider_user.profile_picture else None),
                                'bio': provider_user.bio,
                            }
                        })
            itinerary_data = {
                'id': itinerary.id,
                'title': itinerary.title,
                'travel_type': itinerary.travel_type,
                'is_available': itinerary.is_available,
                'total_segments': itinerary.total_segments,
                'departure_date': itinerary.departure_date,
                'arrival_date': itinerary.arrival_date,
                'created_at': itinerary.created_at,
                'updated_at': itinerary.updated_at,
                'segments': segments_data,
                'matches': serialized_matches
            }
            
            return Response(itinerary_data, status=status.HTTP_200_OK)
            
        except Itinerary.DoesNotExist:
            return Response(
                {'error': 'Itinerary not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error retrieving itinerary {itinerary_id} for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve itinerary'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def put(self, request, itinerary_id):
        """Update an itinerary"""
        try:
            itinerary = Itinerary.objects.get(id=itinerary_id, user=request.user)
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            if 'title' in data:
                itinerary.title = data['title'].strip()
            if 'travel_type' in data:
                if data['travel_type'] in ['one_way', 'round_trip', 'multi_city']:
                    itinerary.travel_type = data['travel_type']
            if 'is_available' in data:
                itinerary.is_available = data['is_available']
            
            itinerary.save()
            
            return Response({
                'message': 'Itinerary updated successfully'
            }, status=status.HTTP_200_OK)
            
        except Itinerary.DoesNotExist:
            return Response(
                {'error': 'Itinerary not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON data'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error updating itinerary {itinerary_id} for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to update itinerary'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def delete(self, request, itinerary_id):
        """Delete an itinerary and all associated matches"""
        try:
            itinerary = Itinerary.objects.get(id=itinerary_id, user=request.user)
            
            # Delete all matches associated with this itinerary
            deleted_matches = Match.objects.filter(
                Q(provider_itinerary=itinerary) | Q(matched_provider_itinerary=itinerary)
            ).delete()
            
            # Delete the itinerary (segments will cascade delete)
            itinerary.delete()
            
            logger.info(f"🗑️ Itinerary {itinerary_id} deleted along with {deleted_matches[0]} matches")
            
            return Response({
                'message': 'Itinerary and associated matches deleted successfully',
                'deleted_matches': deleted_matches[0]
            }, status=status.HTTP_200_OK)
            
        except Itinerary.DoesNotExist:
            return Response(
                {'error': 'Itinerary not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error deleting itinerary {itinerary_id} for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to delete itinerary'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ItineraryMatchView(APIView):
    """
    API for seekers to find matching itineraries using only airport codes.
    No other parameters are required. Returns both perfect (full) matches
    where a segment has both airports, and partial matches where a segment
    has either the from or to airport.
    """
    permission_classes = []

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)

            from_airport = data.get('from_airport')
            to_airport = data.get('to_airport')

            errors = {}

            if not from_airport and not to_airport:
                errors['airports'] = 'Provide at least from_airport or to_airport'
            if from_airport:
                fa = str(from_airport).strip().upper()
                if len(fa) != 3 or not fa.isalpha():
                    errors['from_airport'] = 'Airport code must be 3 alphabetic chars'
            if to_airport:
                ta = str(to_airport).strip().upper()
                if len(ta) != 3 or not ta.isalpha():
                    errors['to_airport'] = 'Airport code must be 3 alphabetic chars'

            if errors:
                return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

            from_airport = str(from_airport).strip().upper() if from_airport else None
            to_airport = str(to_airport).strip().upper() if to_airport else None

            base_qs = (
                TravelSegment.objects
                .filter(itinerary__is_available=True)
                .select_related('itinerary', 'itinerary__user')
                .order_by('departure_date_from', 'departure_time_from')
            )

            if request.user and request.user.is_authenticated:
                base_qs = base_qs.exclude(itinerary__user=request.user)

            full_segments = []
            partial_segments = []

            if from_airport and to_airport:
                full_qs = base_qs.filter(from_airport=from_airport, to_airport=to_airport)
                partial_qs = base_qs.filter(Q(from_airport=from_airport) | Q(to_airport=to_airport)).exclude(id__in=full_qs.values_list('id', flat=True))
            elif from_airport:
                full_qs = base_qs.none()
                partial_qs = base_qs.filter(from_airport=from_airport)
            else:  # to_airport only
                full_qs = base_qs.none()
                partial_qs = base_qs.filter(to_airport=to_airport)

            full_segments = list(full_qs)
            partial_segments = list(partial_qs)

            results = []

            def serialize_match(seg, match_type):
                itinerary = seg.itinerary
                user = itinerary.user
                segments_data = []
                for s in itinerary.segments.all():
                    segments_data.append({
                        'id': s.id,
                        'from_airport': s.from_airport,
                        'to_airport': s.to_airport,
                        'departure_date_from': s.departure_date_from,
                        'departure_date_to': s.departure_date_to,
                        'departure_time_from': s.departure_time_from,
                        'departure_time_to': s.departure_time_to,
                        'airline': s.airline,
                        'flight_number': s.flight_number,
                        'segment_order': s.segment_order,
                        'route': s.route,
                        'layovers': _format_layovers(s.layovers)
                    })

                return {
                    'match_type': match_type,
                    'itinerary': {
                        'id': itinerary.id,
                        'title': itinerary.title,
                        'travel_type': itinerary.travel_type,
                        'is_available': itinerary.is_available,
                        'total_segments': itinerary.total_segments,
                        'departure_date': itinerary.departure_date,
                        'arrival_date': itinerary.arrival_date,
                        'created_at': itinerary.created_at,
                        'updated_at': itinerary.updated_at,
                        'segments': segments_data
                    },
                    'person': {
                        'id': user.id,
                        'full_name': user.full_name,
                        'email': user.email,
                        'phonenumber': user.phonenumber,
                        'role': user.role,
                        'profile_picture': (user.profile_picture.url if user.profile_picture else None),
                        'bio': user.bio,
                        'chat_connection': {
                            'websocket_url': f"ws://localhost:8000/ws/chat/{user.id}/",
                            'other_user_id': user.id,
                            'requires_token': True,
                            'token_param': 'token'
                        }
                    },
                    'matched_segment': {
                        'id': seg.id,
                        'from_airport': seg.from_airport,
                        'to_airport': seg.to_airport,
                        'departure_date_from': seg.departure_date_from,
                        'departure_date_to': seg.departure_date_to,
                        'departure_time_from': seg.departure_time_from,
                        'departure_time_to': seg.departure_time_to,
                        'layovers': _format_layovers(seg.layovers)
                    }
                }

            for seg in full_segments:
                results.append(serialize_match(seg, 'full'))
            for seg in partial_segments:
                results.append(serialize_match(seg, 'partial'))

            return Response({'matches': results, 'count': len(results)}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error matching itineraries for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to match itineraries'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ItineraryAllView(APIView):
    """
    API view to list itineraries across all users.
    Returns only itineraries marked as available.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            itineraries = (
                Itinerary.objects
                .filter(is_available=True)
                .select_related('user')
                .prefetch_related('segments')
            )

            results = []
            for itinerary in itineraries:
                segments_data = []
                for segment in itinerary.segments.all():
                    segments_data.append({
                        'id': segment.id,
                        'from_airport': segment.from_airport,
                        'to_airport': segment.to_airport,
                        'departure_date_from': segment.departure_date_from,
                        'departure_date_to': segment.departure_date_to,
                        'departure_time_from': segment.departure_time_from,
                        'departure_time_to': segment.departure_time_to,
                        'airline': segment.airline,
                        'flight_number': segment.flight_number,
                        'segment_order': segment.segment_order,
                        'route': segment.route,
                        'layovers': _format_layovers(segment.layovers)
                    })

                user = itinerary.user
                results.append({
                    'id': itinerary.id,
                    'title': itinerary.title,
                    'travel_type': itinerary.travel_type,
                    'is_available': itinerary.is_available,
                    'total_segments': itinerary.total_segments,
                    'departure_date': itinerary.departure_date,
                    'arrival_date': itinerary.arrival_date,
                    'created_at': itinerary.created_at,
                    'updated_at': itinerary.updated_at,
                    'segments': segments_data,
                    'owner': {
                        'id': user.id,
                        'full_name': user.full_name,
                        'email': user.email,
                        'phonenumber': user.phonenumber,
                        'role': user.role,
                        'profile_picture': (user.profile_picture.url if user.profile_picture else None),
                        'bio': user.bio,
                        'chat_connection': {
                            'websocket_url': f"ws://localhost:8000/ws/chat/{user.id}/",
                            'other_user_id': user.id,
                            'requires_token': True,
                            'token_param': 'token'
                        }
                    }
                })

            return Response({
                'itineraries': results,
                'count': len(results)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error retrieving all itineraries for user {request.user.id}: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve itineraries'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
