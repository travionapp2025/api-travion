import logging
from django.utils import timezone
from django.db.models import Q
from django.core.cache import cache
from datetime import timedelta
from users.models import SeekerRequest, TravelSegment, Notification, User, Match
from users.services.firebase_admin_service import firebase_admin_service

logger = logging.getLogger(__name__)


class MatchingService:
    """
    Service to handle matching between seeker requests and provider itineraries
    """
    
    @staticmethod
    def find_matches_for_new_itinerary(itinerary):
        try:
            if not itinerary.is_available:
                return []

            cache_key = f"matching_itinerary_{itinerary.id}"
            if cache.get(cache_key):
                logger.info(f"⏭️ Skipping matching for itinerary {itinerary.id} (rate limited - too recent)")
                return []
            
            cache.set(cache_key, True, 30)
            logger.info(f"🔍 Starting optimized matching for itinerary {itinerary.id}")
            
            # Get segments with optimized query
            segments = list(itinerary.segments.select_related().all())
            if not segments:
                logger.info(f"❌ No segments found for itinerary {itinerary.id}")
                return []
            
            logger.info(f"🔍 Itinerary {itinerary.id} has {len(segments)} segments")

            provider_routes = set()
            for segment in segments:
                provider_routes.add((segment.from_airport, segment.to_airport))
            
            logger.info(f"🔍 Provider routes: {list(provider_routes)}")
            
            matches = []

            matching_requests = SeekerRequest.objects.filter(
                is_active=True,
                expires_at__gt=timezone.now(),
                from_airport__in=[route[0] for route in provider_routes],
                to_airport__in=[route[1] for route in provider_routes]
            ).exclude(user=itinerary.user).select_related('user')

            exact_seeker_matches = []
            for request in matching_requests:
                if (request.from_airport, request.to_airport) in provider_routes:
                    exact_seeker_matches.append(request)
            
            logger.info(f"🔍 Found {len(exact_seeker_matches)} seeker requests with matching routes")
            
            for seeker_request in exact_seeker_matches:
                for provider_segment in segments:
                    if (provider_segment.from_airport == seeker_request.from_airport and 
                        provider_segment.to_airport == seeker_request.to_airport):
                        
                        if MatchingService._dates_overlap(provider_segment, seeker_request):
                            if MatchingService._times_overlap(provider_segment, seeker_request):
                                match_quality = MatchingService._layovers_match(provider_segment, seeker_request)
                                logger.info(f"✅ SEEKER MATCH FOUND! Provider {provider_segment.from_airport}→{provider_segment.to_airport} matches Seeker {seeker_request.from_airport}→{seeker_request.to_airport}")
                                matches.append({
                                    'seeker_request': seeker_request,
                                    'seeker_segment': None,  
                                    'provider_itinerary': itinerary,
                                    'provider_segment': provider_segment,
                                    'match_type': 'provider_seeker',
                                    "match_quality" : "exact" if match_quality else "partial",
                                })
                                break  
                            
            from users.models import Itinerary
            matching_provider_itineraries = Itinerary.objects.filter(
                is_available=True
            ).exclude(user=itinerary.user).exclude(id=itinerary.id).select_related('user')
            
            logger.info(f"🔍 Checking {matching_provider_itineraries.count()} other provider itineraries")
            
            for other_itinerary in matching_provider_itineraries:
                other_segments = list(other_itinerary.segments.select_related().all())
                
                for provider_segment in segments:
                    for other_segment in other_segments:
                        if (provider_segment.from_airport == other_segment.from_airport and 
                            provider_segment.to_airport == other_segment.to_airport):
                            
                            if MatchingService._dates_overlap_segments(provider_segment, other_segment):
                                if MatchingService._times_overlap_segments(provider_segment, other_segment):
                                    match_quality = MatchingService._layovers_match(provider_segment, other_segment)
                                    logger.info(f"✅ PROVIDER MATCH FOUND! Provider {provider_segment.from_airport}→{provider_segment.to_airport} matches Other Provider {other_segment.from_airport}→{other_segment.to_airport}")
                                    matches.append({
                                        'seeker_request': None,
                                        'seeker_segment': None,
                                        'provider_itinerary': itinerary,
                                        'provider_segment': provider_segment,
                                        'matched_provider_itinerary': other_itinerary,
                                        'matched_provider_segment': other_segment,
                                        'match_type': 'provider_provider',
                                        "match_quality": "exact" if match_quality else "partial",
                                    })
                                    break 
            
            if matches:
                logger.info(f"📤 Sending notifications for {len(matches)} matches (exact and partial)")
                MatchingService._send_match_notifications(matches)
            else:
                logger.info(f"ℹ️ No matches found for itinerary {itinerary.id}")
            
            return matches
            
        except Exception as e:
            logger.error(f"Error finding matches for new itinerary: {str(e)}")
            return []
    
    @staticmethod
    def get_matches_for_itinerary_display(itinerary):
        """
        Get matches for itinerary display (without sending notifications)
        """
        try:
            if not itinerary.is_available:
                return []
            
            matches = []
            # Get all segments for this itinerary in one query
            segments = list(itinerary.segments.all())
            
            # Get all active seeker requests in one query
            active_requests = list(SeekerRequest.objects.filter(
                is_active=True,
                expires_at__gt=timezone.now()
            ).exclude(user=itinerary.user).select_related('user'))
            
            # Create a set of provider routes for faster lookup
            provider_routes = set()
            for segment in segments:
                provider_routes.add((segment.from_airport, segment.to_airport))
            
            # Filter seeker requests that have matching routes
            matching_requests = []
            for seeker_request in active_requests:
                if (seeker_request.from_airport, seeker_request.to_airport) in provider_routes:
                    matching_requests.append(seeker_request)
            
            # Now do detailed matching only for requests with matching routes
            for seeker_request in matching_requests:
                for provider_segment in segments:
                    if (provider_segment.from_airport == seeker_request.from_airport and 
                        provider_segment.to_airport == seeker_request.to_airport and
                        MatchingService._simple_match(provider_segment, seeker_request)):
                        matches.append({
                            'seeker_request': seeker_request,
                            'seeker_segment': None,  
                            'provider_itinerary': itinerary,
                            'provider_segment': provider_segment
                        })
            
            return matches
            
        except Exception as e:
            logger.error(f"Error getting matches for itinerary display: {str(e)}")
            return []
    
    @staticmethod
    def find_matches_for_new_seeker_request(seeker_request, send_notifications=True):
        """
        Find matching provider itineraries and seeker requests when a new seeker request is created
        Optimized version with better database queries
        """
        try:
            if not seeker_request.is_active or seeker_request.is_expired:
                return []
            
            # Rate limiting: prevent excessive matching calls for the same seeker request within a short time
            cache_key = f"matching_seeker_{seeker_request.id}"
            if cache.get(cache_key):
                logger.info(f"⏭️ Skipping matching for seeker request {seeker_request.id} (rate limited - too recent)")
                return []
            
            cache.set(cache_key, True, 30)
            logger.info(f"🔍 Starting optimized matching for seeker request {seeker_request.id}")
            
            matches = []
            
            # 1. Find matching provider itineraries (seeker-provider matches)
            provider_segments = TravelSegment.objects.filter(
                itinerary__is_available=True,
                from_airport=seeker_request.from_airport,
                to_airport=seeker_request.to_airport
            ).exclude(itinerary__user=seeker_request.user).select_related('itinerary', 'itinerary__user')
            
            logger.info(f"🔍 Found {provider_segments.count()} provider segments with matching route: {seeker_request.from_airport}→{seeker_request.to_airport}")
            
            for provider_segment in provider_segments:
                # Quick date check first
                if MatchingService._dates_overlap(provider_segment, seeker_request):
                    # Then check times
                    if MatchingService._times_overlap(provider_segment, seeker_request):
                        logger.info(f"✅ PROVIDER MATCH FOUND! Provider {provider_segment.from_airport}→{provider_segment.to_airport} matches Seeker {seeker_request.from_airport}→{seeker_request.to_airport}")
                        matches.append({
                            'seeker_request': seeker_request,
                            'seeker_segment': None,  
                            'provider_itinerary': provider_segment.itinerary,
                            'provider_segment': provider_segment,
                            'match_type': 'seeker_provider'  # Seeker finding a provider
                        })
            
            # 2. Find matching seeker requests (seeker-seeker matches)
            matching_seeker_requests = SeekerRequest.objects.filter(
                is_active=True,
                expires_at__gt=timezone.now(),
                from_airport=seeker_request.from_airport,
                to_airport=seeker_request.to_airport
            ).exclude(user=seeker_request.user).exclude(id=seeker_request.id).select_related('user')
            
            logger.info(f"🔍 Found {matching_seeker_requests.count()} other seeker requests with matching routes")
            
            for other_seeker_request in matching_seeker_requests:
                if MatchingService._dates_overlap_seekers(seeker_request, other_seeker_request):
                    if MatchingService._times_overlap_seekers(seeker_request, other_seeker_request):
                        logger.info(f"✅ SEEKER MATCH FOUND! Seeker {seeker_request.from_airport}→{seeker_request.to_airport} matches Other Seeker {other_seeker_request.from_airport}→{other_seeker_request.to_airport}")
                        matches.append({
                            'seeker_request': seeker_request,
                            'seeker_segment': None,
                            'provider_itinerary': None,
                            'provider_segment': None,
                            'matched_seeker_request': other_seeker_request,
                            'match_type': 'seeker_seeker'
                        })
            
            if matches:
                logger.info(f"💾 Saving {len(matches)} matches to database")
                # Always save matches to database
                saved_matches = []
                for match in matches:
                    saved_match = MatchingService._save_match_to_database(match)
                    if saved_match:
                        match['saved_match_obj'] = saved_match
                        saved_matches.append(match)

                if send_notifications and saved_matches:
                    logger.info(f"📤 Sending notifications for {len(saved_matches)} matches (exact and partial)")
                    MatchingService._send_match_notifications(saved_matches)
                elif saved_matches:
                    logger.info(f"📤 Skipping notifications for {len(saved_matches)} matches (send_notifications=False)")
            else:
                logger.info(f"ℹ️ No matches found for seeker request {seeker_request.id}")
            
            return matches
            
        except Exception as e:
            logger.error(f"Error finding matches for new seeker request: {str(e)}")
            return []
    
    @staticmethod
    def get_matches_for_seeker_request_display(seeker_request):
        """
        Get matches for seeker request display and save them to database
        """
        try:
            if not seeker_request.is_active or seeker_request.is_expired:
                return []

            matches = []
            provider_segments = TravelSegment.objects.filter(
                itinerary__is_available=True,
                from_airport=seeker_request.from_airport,
                to_airport=seeker_request.to_airport
            ).exclude(itinerary__user=seeker_request.user).select_related('itinerary', 'itinerary__user')

            match_data_list = []
            for provider_segment in provider_segments:
                if MatchingService._simple_match(provider_segment, seeker_request):
                    match_data = {
                        'seeker_request': seeker_request,
                        'seeker_segment': None,
                        'provider_itinerary': provider_segment.itinerary,
                        'provider_segment': provider_segment,
                        'match_type': 'seeker_provider'  # Seeker finding a provider
                    }
                    match_data_list.append(match_data)
                    matches.append({
                        'seeker_request': seeker_request,
                        'seeker_segment': None,
                        'provider_itinerary': provider_segment.itinerary,
                        'provider_segment': provider_segment
                    })

            # Save matches to database without sending notifications
            if match_data_list:
                print(match_data_list)
                for match_data in match_data_list:
                    MatchingService._save_match_to_database(match_data)

            return matches

        except Exception as e:
            logger.error(f"Error getting matches for seeker request display: {str(e)}")
            return []
    
    @staticmethod
    def _segments_match(provider_segment, seeker_segment, seeker_request):
        """
        Check if a provider segment matches a seeker segment
        """
        try:
            # Check if routes match
            if (provider_segment.from_airport != seeker_segment.from_airport or 
                provider_segment.to_airport != seeker_segment.to_airport):
                return False
            
            # Check if dates overlap
            if not MatchingService._dates_overlap(provider_segment, seeker_request):
                return False
            
            # Check if times overlap (if specified)
            if not MatchingService._times_overlap(provider_segment, seeker_segment):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking segment match: {str(e)}")
            return False
    
    
    @staticmethod
    def _times_overlap(provider_segment, seeker_segment):
        """
        Check if provider segment times overlap with seeker segment time preferences
        """
        try:
            if (not seeker_segment.departure_time_from and not seeker_segment.departure_time_to and
                not seeker_segment.arrival_time_from and not seeker_segment.arrival_time_to):
                return True
            
            if seeker_segment.departure_time_from and seeker_segment.departure_time_to:
                if not provider_segment.departure_time:
                    return False  
                
                if not (seeker_segment.departure_time_from <= provider_segment.departure_time <= seeker_segment.departure_time_to):
                    return False
            
            # Check arrival time overlap
            if seeker_segment.arrival_time_from and seeker_segment.arrival_time_to:
                if not provider_segment.arrival_time:
                    return False  
                
                if not (seeker_segment.arrival_time_from <= provider_segment.arrival_time <= seeker_segment.arrival_time_to):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking time overlap: {str(e)}")
            return False
    
    @staticmethod
    def _determine_match_quality(match_data):
        """
        Determine if match is 'exact' or 'partial'
        Exact: routes match AND dates overlap AND times overlap (if specified) AND layovers match (for provider-provider)
        Partial: routes match but dates/times/layovers don't overlap perfectly
        """
        try:
            match_type = match_data.get('match_type', 'provider_seeker')

            if match_type == 'provider_seeker':
                seeker_request = match_data['seeker_request']
                provider_segment = match_data['provider_segment']

                # Check dates overlap
                dates_overlap = MatchingService._dates_overlap(provider_segment, seeker_request)
                if not dates_overlap:
                    return 'partial'

                # # Check times overlap (if specified)
                # times_overlap = MatchingService._times_overlap(provider_segment, seeker_request)
                # if not times_overlap:
                #     return 'partial'

                dates_overlap = MatchingService._dates_overlap_segments(provider_segment, matched_provider_segment)
                if not dates_overlap:
                    return 'partial'
                
                layovers_match = MatchingService._layovers_match(provider_segment, matched_provider_segment)
                if not layovers_match:
                    return 'partial'

                # Since seekers don't specify layover preferences, match is exact if dates and times match
                return 'exact'

            elif match_type == 'provider_provider':
                provider_segment = match_data['provider_segment']
                matched_provider_segment = match_data['matched_provider_segment']

                # Check dates overlap
                dates_overlap = MatchingService._dates_overlap_segments(provider_segment, matched_provider_segment)
                if not dates_overlap:
                    return 'partial'

                # Check times overlap
                # times_overlap = MatchingService._times_overlap_segments(provider_segment, matched_provider_segment)
                # if not times_overlap:
                #     return 'partial'

                # Check layovers match exactly
                layovers_match = MatchingService._layovers_match(provider_segment, matched_provider_segment)
                if not layovers_match:
                    return 'partial'

                return 'exact'

            elif match_type == 'seeker_seeker':
                seeker_request = match_data['seeker_request']
                matched_seeker_request = match_data['matched_seeker_request']

                # Check dates overlap
                dates_overlap = MatchingService._dates_overlap_seekers(seeker_request, matched_seeker_request)
                if not dates_overlap:
                    return 'partial'

                # # Check times overlap
                # times_overlap = MatchingService._times_overlap_seekers(seeker_request, matched_seeker_request)
                # if not times_overlap:
                #     return 'partial'

                dates_overlap = MatchingService._dates_overlap_segments(provider_segment, matched_provider_segment)
                if not dates_overlap:
                    return 'partial'
                
                layovers_match = MatchingService._layovers_match(provider_segment, matched_provider_segment)                
                if not layovers_match:
                    return 'partial'

                return 'exact'

            return 'exact'  # Default to exact
        except Exception as e:
            logger.error(f"Error determining match quality: {str(e)}")
            return 'exact'  # Default to exact on error
    
    @staticmethod
    def _save_match_to_database(match_data):
        """
        Save a match to the database
        """
        try:
            match_type = match_data.get('match_type', 'provider_seeker')
            # Normalize seeker_provider to provider_seeker
            if match_type == 'seeker_provider':
                match_type = 'provider_seeker'
            match_quality = MatchingService._determine_match_quality(match_data)
            print("match quality", match_quality)

            if match_type == 'provider_seeker':
                seeker_request = match_data['seeker_request']
                provider_itinerary = match_data['provider_itinerary']
                provider_segment = match_data['provider_segment']
                
                user1 = seeker_request.user
                user2 = provider_itinerary.user
                route = f"{provider_segment.from_airport} → {provider_segment.to_airport}"
                departure_date_from = provider_segment.departure_date_from
                departure_date_to = provider_segment.departure_date_to
                # Ensure expires_at is in the future
                itinerary_expires = provider_segment.itinerary.updated_at + timedelta(days=30)
                expires_at = min(seeker_request.expires_at, itinerary_expires)
                # If expires_at is in the past, set it to 30 days from now
                if expires_at <= timezone.now():
                    expires_at = timezone.now() + timedelta(days=30)
                    logger.warning(f"⚠️ Match expires_at was in the past, adjusted to {expires_at}")
                
                # Check if match already exists
                existing_match = Match.objects.filter(
                    match_type='provider_seeker',
                    user1=user1,
                    user2=user2,
                    provider_itinerary=provider_itinerary,
                    seeker_request=seeker_request,
                    status='active'
                ).first()
                
                if existing_match:
                    logger.info(f"⏭️ Match already exists in database: {existing_match.id}")
                    return existing_match
                
                match = Match.objects.create(
                    match_type='provider_seeker',
                    match_quality=match_quality,
                    provider_itinerary=provider_itinerary,
                    provider_segment=provider_segment,
                    seeker_request=seeker_request,
                    user1=user1,
                    user2=user2,
                    route=route,
                    departure_date_from=departure_date_from,
                    departure_date_to=departure_date_to,
                    expires_at=expires_at
                )
                logger.info(f"✅ Saved provider-seeker match to database: {match.id}")
                return match
                
            elif match_type == 'provider_provider':
                provider_itinerary = match_data['provider_itinerary']
                provider_segment = match_data['provider_segment']
                matched_provider_itinerary = match_data['matched_provider_itinerary']
                matched_provider_segment = match_data['matched_provider_segment']
                
                user1 = provider_itinerary.user
                user2 = matched_provider_itinerary.user
                route = f"{provider_segment.from_airport} → {provider_segment.to_airport}"
                departure_date_from = min(provider_segment.departure_date_from, matched_provider_segment.departure_date_from)
                departure_date_to = max(provider_segment.departure_date_to, matched_provider_segment.departure_date_to)
                expires_at = max(provider_itinerary.updated_at, matched_provider_itinerary.updated_at) + timedelta(days=30)
                
                # Check if match already exists
                existing_match = Match.objects.filter(
                    match_type='provider_provider',
                    user1=user1,
                    user2=user2,
                    provider_itinerary=provider_itinerary,
                    matched_provider_itinerary=matched_provider_itinerary,
                    status='active'
                ).first()
                
                if existing_match:
                    logger.info(f"⏭️ Match already exists in database: {existing_match.id}")
                    return existing_match
                
                match = Match.objects.create(
                    match_type='provider_provider',
                    match_quality=match_quality,
                    provider_itinerary=provider_itinerary,
                    provider_segment=provider_segment,
                    matched_provider_itinerary=matched_provider_itinerary,
                    matched_provider_segment=matched_provider_segment,
                    user1=user1,
                    user2=user2,
                    route=route,
                    departure_date_from=departure_date_from,
                    departure_date_to=departure_date_to,
                    expires_at=expires_at
                )
                logger.info(f"✅ Saved provider-provider match to database: {match.id}")
                return match
                
            elif match_type == 'seeker_seeker':
                seeker_request = match_data['seeker_request']
                matched_seeker_request = match_data['matched_seeker_request']
                
                user1 = seeker_request.user
                user2 = matched_seeker_request.user
                route = f"{seeker_request.from_airport} → {seeker_request.to_airport}"
                departure_date_from = min(seeker_request.departure_date_from, matched_seeker_request.departure_date_from)
                departure_date_to = max(seeker_request.departure_date_to, matched_seeker_request.departure_date_to)
                expires_at = min(seeker_request.expires_at, matched_seeker_request.expires_at)
                # If expires_at is in the past, set it to 30 days from now
                if expires_at <= timezone.now():
                    expires_at = timezone.now() + timedelta(days=30)
                    logger.warning(f"⚠️ Match expires_at was in the past, adjusted to {expires_at}")
                
                # Check if match already exists
                existing_match = Match.objects.filter(
                    match_type='seeker_seeker',
                    user1=user1,
                    user2=user2,
                    seeker_request=seeker_request,
                    matched_seeker_request=matched_seeker_request,
                    status='active'
                ).first()
                
                if existing_match:
                    logger.info(f"⏭️ Match already exists in database: {existing_match.id}")
                    return existing_match
                
                match = Match.objects.create(
                    match_type='seeker_seeker',
                    match_quality=match_quality,
                    seeker_request=seeker_request,
                    matched_seeker_request=matched_seeker_request,
                    user1=user1,
                    user2=user2,
                    route=route,
                    departure_date_from=departure_date_from,
                    departure_date_to=departure_date_to,
                    expires_at=expires_at
                )
                logger.info(f"✅ Saved seeker-seeker match to database: {match.id}")
                return match
                
        except Exception as e:
            print(f"❌ Error saving match to database: {str(e)}")
            logger.error(f"❌ Error saving match to database: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            # Log the match_data for debugging
            logger.error(f"❌ Match data that failed to save: {match_data}")
            return None
    
    @staticmethod
    def _send_match_notifications(matches):
        """
        Send notifications for all types of matches (provider-seeker, provider-provider, seeker-seeker)
        Also saves matches to database
        """
        try:
            logger.info(f"🔔 Starting to send notifications for {len(matches)} matches")
            
            # Deduplicate matches to prevent multiple notifications for the same match
            seen_matches = set()
            unique_matches = []
            
            for match in matches:
                match_type = match.get('match_type', 'provider_seeker')
                # Normalize seeker_provider to provider_seeker
                if match_type == 'seeker_provider':
                    match_type = 'provider_seeker'

                # Create unique key based on match type
                if match_type == 'provider_seeker':
                    seeker_request = match['seeker_request']
                    provider_itinerary = match['provider_itinerary']
                    match_key = (match_type, seeker_request.id, provider_itinerary.id)
                elif match_type == 'provider_provider':
                    provider_itinerary = match['provider_itinerary']
                    matched_provider_itinerary = match['matched_provider_itinerary']
                    match_key = (match_type, provider_itinerary.id, matched_provider_itinerary.id)
                elif match_type == 'seeker_seeker':
                    seeker_request = match['seeker_request']
                    matched_seeker_request = match['matched_seeker_request']
                    match_key = (match_type, seeker_request.id, matched_seeker_request.id)
                else:
                    match_key = (match_type, id(match))
                
                if match_key not in seen_matches:
                    seen_matches.add(match_key)
                    # Check if match is already saved
                    saved_match = match.get('saved_match_obj')
                    if not saved_match:
                        # Save match to database FIRST before adding to notifications
                        saved_match = MatchingService._save_match_to_database(match)
                        if saved_match:
                            match['saved_match_obj'] = saved_match
                            logger.info(f"✅ Match saved successfully: {saved_match.id}")
                        else:
                            logger.error(f"❌ Failed to save match to database, skipping notifications")
                            continue

                    # Only add to unique_matches if save was successful
                    unique_matches.append(match)
                else:
                    logger.info(f"⏭️ Skipping duplicate match: {match_type}")
            
            logger.info(f"📊 Processing {len(unique_matches)} unique matches out of {len(matches)} total matches")
            
            for i, match in enumerate(unique_matches):
                try:
                    match_type = match.get('match_type', 'provider_seeker')
                    # Normalize seeker_provider to provider_seeker
                    if match_type == 'seeker_provider':
                        match_type = 'provider_seeker'
                    saved_match_obj = match.get('saved_match_obj')

                    if not saved_match_obj:
                        logger.warning(f"⚠️ No saved match object for match {i+1}, skipping notifications")
                        continue

                    print(f"🔔 Processing match {i+1}/{len(unique_matches)}: Type={match_type}, Match ID={saved_match_obj.id}")

                    if match_type == 'provider_seeker':
                        # Original provider-seeker matching
                        seeker_request = match['seeker_request']
                        provider_itinerary = match['provider_itinerary']
                        provider_segment = match['provider_segment']
                        
                        logger.info(f"🔔 Notifying seeker {seeker_request.user.email}")
                        MatchingService._notify_seeker_match(
                            seeker_request, provider_itinerary, provider_segment
                        )
                        
                        logger.info(f"🔔 Notifying provider {provider_itinerary.user.email}")
                        MatchingService._notify_provider_match(
                            provider_itinerary, seeker_request, None
                        )
                    
                    elif match_type == 'provider_provider':
                        provider_itinerary = match['provider_itinerary']
                        provider_segment = match['provider_segment']
                        matched_provider_itinerary = match['matched_provider_itinerary']
                        matched_provider_segment = match['matched_provider_segment']
                        
                        logger.info(f"🔔 Notifying provider {provider_itinerary.user.email}")
                        MatchingService._notify_provider_provider_match(
                            provider_itinerary, provider_segment,
                            matched_provider_itinerary, matched_provider_segment
                        )
                        
                        logger.info(f"🔔 Notifying other provider {matched_provider_itinerary.user.email}")
                        MatchingService._notify_provider_provider_match(
                            matched_provider_itinerary, matched_provider_segment,
                            provider_itinerary, provider_segment
                        )
                    
                    elif match_type == 'seeker_seeker':
                        seeker_request = match['seeker_request']
                        matched_seeker_request = match['matched_seeker_request']
                        
                        logger.info(f"🔔 Notifying seeker {seeker_request.user.email}")
                        MatchingService._notify_seeker_seeker_match(
                            seeker_request, matched_seeker_request
                        )
                        
                        logger.info(f"🔔 Notifying other seeker {matched_seeker_request.user.email}")
                        MatchingService._notify_seeker_seeker_match(
                            matched_seeker_request, seeker_request
                        )
                    
                except Exception as match_error:
                    logger.error(f"❌ Error processing match {i+1}: {str(match_error)}")
                    import traceback
                    logger.error(f"❌ Traceback: {traceback.format_exc()}")
                    continue
                
        except Exception as e:
            logger.error(f"❌ Error sending match notifications: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
    
    @staticmethod
    def _notify_seeker_match(seeker_request, provider_itinerary, provider_segment):
        """
        Send notification to seeker about a new match
        """
        try:
            logger.info(f"🔔 Starting seeker notification for {seeker_request.user.email}")
            
            from django.utils import timezone
            from datetime import timedelta
            
            recent_cutoff = timezone.now() - timedelta(minutes=1)
            existing_notification = Notification.objects.filter(
                user=seeker_request.user,
                notification_type='itinerary_match',
                data__seeker_request_id=seeker_request.id,
                data__provider_itinerary_id=provider_itinerary.id,
                created_at__gte=recent_cutoff
            ).first()
            
            if existing_notification:
                logger.info(f"⏭️ Skipping duplicate notification for seeker {seeker_request.user.email} (created {existing_notification.created_at})")
                return
            
            # Create notification record
            logger.info(f"🔔 Creating notification for seeker {seeker_request.user.email}")
            notification = Notification.objects.create(
                user=seeker_request.user,
                notification_type='itinerary_match',
                title='New Travel Match Found!',
                message=f"Found a match for your {seeker_request.title} request: {provider_segment.route} on {provider_segment.departure_date_from} to {provider_segment.departure_date_to}",
                data={
                    'seeker_request_id': seeker_request.id,
                    'provider_itinerary_id': provider_itinerary.id,
                    'provider_user_id': provider_itinerary.user.id,
                    'matched_route': provider_segment.route,
                    'departure_date_from': provider_segment.departure_date_from.isoformat(),
                    'departure_date_to': provider_segment.departure_date_to.isoformat(),
                    'match_type': 'seeker_match'
                },
                sender=provider_itinerary.user,
                priority='high'
            )
            logger.info(f"✅ Notification created with ID: {notification.id}")
            
            # Send push notification using existing notification
            logger.info(f"📱 Sending Firebase notification to seeker {seeker_request.user.email}")
            firebase_result = firebase_admin_service.send_notification_to_user(
                user=seeker_request.user,
                title='New Travel Match Found!',
                body=f"Found a match for your {seeker_request.title} request: {provider_segment.route} on {provider_segment.departure_date_from} to {provider_segment.departure_date_to}",
                notification_type='itinerary_match',
                data={
                    'notification_id': notification.id,
                    'seeker_request_id': seeker_request.id,
                    'provider_itinerary_id': provider_itinerary.id,
                    'provider_user_id': provider_itinerary.user.id,
                    'matched_route': provider_segment.route,
                    'departure_date_from': provider_segment.departure_date_from.isoformat(),
                    'departure_date_to': provider_segment.departure_date_to.isoformat(),
                    'match_type': 'seeker_match'
                },
                notification_id=notification.id
            )
            logger.info(f"📱 Firebase notification result: {firebase_result}")
            
            logger.info(f"✅ Seeker match notification sent to {seeker_request.user.email}")
            
            # Send WebSocket event for real-time updates
            logger.info(f"📡 Sending WebSocket event to seeker {seeker_request.user.email}")
            MatchingService._send_websocket_match_event(
                user=seeker_request.user,
                event_type='seeker_request_matched',
                data={
                    'seeker_request_id': seeker_request.id,
                    'provider_info': {
                        'id': provider_itinerary.user.id,
                        'full_name': provider_itinerary.user.full_name,
                        'email': provider_itinerary.user.email,
                        'role': provider_itinerary.user.role,
                        'profile_picture': (provider_itinerary.user.profile_picture.url if provider_itinerary.user.profile_picture else None),
                        'bio': provider_itinerary.user.bio,
                    },
                    'match_details': {
                        'route': provider_segment.route,
                        'departure_date_from': provider_segment.departure_date_from.isoformat(),
                        'departure_date_to': provider_segment.departure_date_to.isoformat(),
                        'departure_time_from': provider_segment.departure_time_from.isoformat() if provider_segment.departure_time_from else None,
                        'departure_time_to': provider_segment.departure_time_to.isoformat() if provider_segment.departure_time_to else None,
                        'airline': provider_segment.airline,
                        'flight_number': provider_segment.flight_number,
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"❌ Error notifying seeker match: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
    
    @staticmethod
    def _notify_provider_match(provider_itinerary, seeker_request, seeker_segment):
        """
        Send notification to provider about a new match
        """
        try:
            logger.info(f"🔔 Starting provider notification for {provider_itinerary.user.email}")
            
            from django.utils import timezone
            from datetime import timedelta
            
            recent_cutoff = timezone.now() - timedelta(minutes=1)
            existing_notification = Notification.objects.filter(
                user=provider_itinerary.user,
                notification_type='itinerary_match',
                data__seeker_request_id=seeker_request.id,
                data__provider_itinerary_id=provider_itinerary.id,
                created_at__gte=recent_cutoff
            ).first()
            
            if existing_notification:
                logger.info(f"⏭️ Skipping duplicate notification for provider {provider_itinerary.user.email} (created {existing_notification.created_at})")
                return
            
            # Create notification record
            logger.info(f"🔔 Creating notification for provider {provider_itinerary.user.email}")
            notification = Notification.objects.create(
                user=provider_itinerary.user,
                notification_type='itinerary_match',
                title='Someone is Looking for Your Route!',
                message=f"Someone is looking for your {provider_itinerary.title} route: {seeker_request.from_airport} → {seeker_request.to_airport}",
                data={
                    'seeker_request_id': seeker_request.id,
                    'provider_itinerary_id': provider_itinerary.id,
                    'seeker_user_id': seeker_request.user.id,
                    'matched_route': f"{seeker_request.from_airport} → {seeker_request.to_airport}",
                    'departure_date_from': seeker_request.departure_date_from.isoformat(),
                    'departure_date_to': seeker_request.departure_date_to.isoformat(),
                    'match_type': 'provider_match'
                },
                sender=seeker_request.user,
                priority='normal'
            )
            logger.info(f"✅ Provider notification created with ID: {notification.id}")
            
            # Send push notification using existing notification
            logger.info(f"📱 Sending Firebase notification to provider {provider_itinerary.user.email}")
            firebase_result = firebase_admin_service.send_notification_to_user(
                user=provider_itinerary.user,
                title='Someone is Looking for Your Route!',
                body=f"Someone is looking for your {provider_itinerary.title} route: {seeker_request.from_airport} → {seeker_request.to_airport}",
                notification_type='itinerary_match',
                data={
                    'notification_id': notification.id,
                    'seeker_request_id': seeker_request.id,
                    'provider_itinerary_id': provider_itinerary.id,
                    'seeker_user_id': seeker_request.user.id,
                    'matched_route': f"{seeker_request.from_airport} → {seeker_request.to_airport}",
                    'departure_date_from': seeker_request.departure_date_from.isoformat(),
                    'departure_date_to': seeker_request.departure_date_to.isoformat(),
                    'match_type': 'provider_match'
                },
                notification_id=notification.id
            )
            logger.info(f"📱 Firebase notification result: {firebase_result}")
            
            logger.info(f"✅ Provider match notification sent to {provider_itinerary.user.email}")
            
            # Send WebSocket event for real-time updates
            logger.info(f"📡 Sending WebSocket event to provider {provider_itinerary.user.email}")
            MatchingService._send_websocket_match_event(
                user=provider_itinerary.user,
                event_type='provider_itinerary_matched',
                data={
                    'provider_itinerary_id': provider_itinerary.id,
                    'seeker_info': {
                        'id': seeker_request.user.id,
                        'full_name': seeker_request.user.full_name,
                        'email': seeker_request.user.email,
                        'role': seeker_request.user.role,
                        'profile_picture': (seeker_request.user.profile_picture.url if seeker_request.user.profile_picture else None),
                        'bio': seeker_request.user.bio,
                    },
                    'match_details': {
                        'route': f"{seeker_request.from_airport} → {seeker_request.to_airport}",
                        'departure_date_from': seeker_request.departure_date_from.isoformat(),
                        'departure_date_to': seeker_request.departure_date_to.isoformat(),
                        'departure_time_from': seeker_request.departure_time_from.isoformat() if seeker_request.departure_time_from else None,
                        'departure_time_to': seeker_request.departure_time_to.isoformat() if seeker_request.departure_time_to else None,
                        'request_title': seeker_request.title,
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"❌ Error notifying provider match: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
    
    @staticmethod
    def cleanup_expired_requests():
        """
        Clean up expired seeker requests
        """
        try:
            expired_requests = SeekerRequest.objects.filter(
                is_active=True,
                expires_at__lte=timezone.now()
            )
            
            count = expired_requests.count()
            expired_requests.update(is_active=False)
            
            if count > 0:
                logger.info(f"🧹 Cleaned up {count} expired seeker requests")
            
            return count
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up expired requests: {str(e)}")
            return 0
    
    @staticmethod
    def _simple_match(provider_segment, seeker_request):
        """Check if provider segment matches seeker request"""
        try:
            # Check if airports match
            if (provider_segment.from_airport != seeker_request.from_airport or 
                provider_segment.to_airport != seeker_request.to_airport):
                logger.info(f"❌ Airport mismatch: Provider {provider_segment.from_airport}→{provider_segment.to_airport} vs Seeker {seeker_request.from_airport}→{seeker_request.to_airport}")
                return False
            
            # Check if dates overlap
            if not MatchingService._dates_overlap(provider_segment, seeker_request):
                logger.info(f"❌ Date mismatch: Provider {provider_segment.departure_date_from} to {provider_segment.departure_date_to} vs Seeker {seeker_request.departure_date_from} to {seeker_request.departure_date_to}")
                return False
            
            # Check if times overlap (if specified)
            if not MatchingService._times_overlap(provider_segment, seeker_request):
                logger.info(f"❌ Time mismatch: Provider {provider_segment.departure_time_from} to {provider_segment.departure_time_to} vs Seeker {seeker_request.departure_time_from} to {seeker_request.departure_time_to}")
                return False
            
            logger.info(f"✅ All checks passed - MATCH FOUND!")
            return True
            
        except Exception as e:
            logger.error(f"Error checking simple match: {str(e)}")
            return False
    
    @staticmethod
    def _dates_overlap(provider_segment, seeker_request):
        """Check if provider segment dates overlap with seeker request dates"""
        try:
            provider_from = provider_segment.departure_date_from
            provider_to = provider_segment.departure_date_to
            seeker_from = seeker_request.departure_date_from
            seeker_to = seeker_request.departure_date_to
            
            logger.info(f"🔍 Date overlap check: Provider {provider_from} to {provider_to} vs Seeker {seeker_from} to {seeker_to}")
            
            if (provider_from <= seeker_to and provider_to >= seeker_from):
                logger.info(f"✅ Date overlap found!")
                return True
            
            logger.info(f"❌ No date overlap")
            return False
            
        except Exception as e:
            logger.error(f"Error checking date overlap: {str(e)}")
            return False
    
    @staticmethod
    def _times_overlap(provider_segment, seeker_request):
        """Check if provider segment times overlap with seeker request times"""
        try:
            # If seeker doesn't specify time preferences, consider it a match
            if not seeker_request.departure_time_from or not seeker_request.departure_time_to:
                logger.info(f"✅ Time overlap: Seeker has no time preferences")
                return True
            
            # If provider doesn't specify time preferences, consider it a match
            if not provider_segment.departure_time_from or not provider_segment.departure_time_to:
                logger.info(f"✅ Time overlap: Provider has no time preferences")
                return True
            
            # Check if time ranges overlap
            provider_from = provider_segment.departure_time_from
            provider_to = provider_segment.departure_time_to
            seeker_from = seeker_request.departure_time_from
            seeker_to = seeker_request.departure_time_to
            
            logger.info(f"🔍 Time overlap check: Provider {provider_from} to {provider_to} vs Seeker {seeker_from} to {seeker_to}")
            
            if (provider_from <= seeker_to and provider_to >= seeker_from):
                logger.info(f"✅ Time overlap found!")
                return True
            
            logger.info(f"❌ No time overlap")
            return False
            
        except Exception as e:
            logger.error(f"Error checking time overlap: {str(e)}")
            return False
    
    @staticmethod
    def _dates_overlap_segments(segment1, segment2):
        """Check if two segments' dates overlap"""
        try:
            seg1_from = segment1.departure_date_from
            seg1_to = segment1.departure_date_to
            seg2_from = segment2.departure_date_from
            seg2_to = segment2.departure_date_to
            
            if (seg1_from <= seg2_to and seg1_to >= seg2_from):
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking segment date overlap: {str(e)}")
            return False
    
    @staticmethod
    def _times_overlap_segments(segment1, segment2):
        """Check if two segments' times overlap"""
        try:
            # If either segment doesn't specify time preferences, consider it a match
            if (not segment1.departure_time_from or not segment1.departure_time_to or
                not segment2.departure_time_from or not segment2.departure_time_to):
                return True
            
            seg1_from = segment1.departure_time_from
            seg1_to = segment1.departure_time_to
            seg2_from = segment2.departure_time_from
            seg2_to = segment2.departure_time_to
            
            if (seg1_from <= seg2_to and seg1_to >= seg2_from):
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking segment time overlap: {str(e)}")
            return False
    
    @staticmethod
    def _dates_overlap_seekers(seeker1, seeker2):
        """Check if two seeker requests' dates overlap"""
        try:
            seeker1_from = seeker1.departure_date_from
            seeker1_to = seeker1.departure_date_to
            seeker2_from = seeker2.departure_date_from
            seeker2_to = seeker2.departure_date_to
            
            if (seeker1_from <= seeker2_to and seeker1_to >= seeker2_from):
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking seeker date overlap: {str(e)}")
            return False
    
    @staticmethod
    def _times_overlap_seekers(seeker1, seeker2):
        """Check if two seeker requests' times overlap"""
        try:
            # If either seeker doesn't specify time preferences, consider it a match
            if (not seeker1.departure_time_from or not seeker1.departure_time_to or
                not seeker2.departure_time_from or not seeker2.departure_time_to):
                return True

            seeker1_from = seeker1.departure_time_from
            seeker1_to = seeker1.departure_time_to
            seeker2_from = seeker2.departure_time_from
            seeker2_to = seeker2.departure_time_to

            if (seeker1_from <= seeker2_to and seeker1_to >= seeker2_from):
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking seeker time overlap: {str(e)}")
            return False

    @staticmethod
    def _layovers_match(segment1, segment2):
        """Check if two segments have matching layovers"""
        try:
            layovers1 = segment1.layovers or []
            layovers2 = segment2.layovers or []

            print(layovers1, "==========", layovers2)

            # If both have no layovers, it's an exact match
            if not layovers1 and not layovers2:
                return True

            # If one has layovers and the other doesn't, it's partial
            if (layovers1 and not layovers2) or (not layovers1 and layovers2):
                return False

            # If both have layovers, they must match exactly
            if layovers1 == layovers2:
                return True 
            
            set1 = set(layovers1)
            set2 = set(layovers2)

            # Single layover subset → partial (explicitly False)
            if len(set1) == 1 and set1.issubset(set2):
                return False

            if len(set2) == 1 and set2.issubset(set1):
                return False
            
            return False
        except Exception as e:
            logger.error(f"Error checking layover match: {str(e)}")
            return False
    
    @staticmethod
    def _notify_provider_provider_match(provider_itinerary, provider_segment, matched_provider_itinerary, matched_provider_segment):
        """
        Send notification to provider about a matching provider itinerary
        """
        try:
            logger.info(f"🔔 Starting provider-provider notification for {provider_itinerary.user.email}")
            
            from django.utils import timezone
            from datetime import timedelta
            
            recent_cutoff = timezone.now() - timedelta(minutes=1)
            existing_notification = Notification.objects.filter(
                user=provider_itinerary.user,
                notification_type='itinerary_match',
                data__provider_itinerary_id=provider_itinerary.id,
                data__matched_provider_itinerary_id=matched_provider_itinerary.id,
                created_at__gte=recent_cutoff
            ).first()
            
            if existing_notification:
                logger.info(f"⏭️ Skipping duplicate notification for provider {provider_itinerary.user.email}")
                return
            
            # Create notification record
            notification = Notification.objects.create(
                user=provider_itinerary.user,
                notification_type='itinerary_match',
                title='Matching Provider Route Found!',
                message=f"Another provider has a matching route: {matched_provider_segment.route} on {matched_provider_segment.departure_date_from} to {matched_provider_segment.departure_date_to}",
                data={
                    'provider_itinerary_id': provider_itinerary.id,
                    'matched_provider_itinerary_id': matched_provider_itinerary.id,
                    'matched_provider_user_id': matched_provider_itinerary.user.id,
                    'matched_route': matched_provider_segment.route,
                    'departure_date_from': matched_provider_segment.departure_date_from.isoformat(),
                    'departure_date_to': matched_provider_segment.departure_date_to.isoformat(),
                    'match_type': 'provider_provider'
                },
                sender=matched_provider_itinerary.user,
                priority='normal'
            )
            
            # Send push notification
            firebase_admin_service.send_notification_to_user(
                user=provider_itinerary.user,
                title='Matching Provider Route Found!',
                body=f"Another provider has a matching route: {matched_provider_segment.route}",
                notification_type='itinerary_match',
                data={
                    'notification_id': notification.id,
                    'provider_itinerary_id': provider_itinerary.id,
                    'matched_provider_itinerary_id': matched_provider_itinerary.id,
                    'matched_provider_user_id': matched_provider_itinerary.user.id,
                    'matched_route': matched_provider_segment.route,
                    'match_type': 'provider_provider'
                },
                notification_id=notification.id
            )
            
            # Send WebSocket event
            MatchingService._send_websocket_match_event(
                user=provider_itinerary.user,
                event_type='provider_provider_matched',
                data={
                    'provider_itinerary_id': provider_itinerary.id,
                    'matched_provider_info': {
                        'id': matched_provider_itinerary.user.id,
                        'full_name': matched_provider_itinerary.user.full_name,
                        'email': matched_provider_itinerary.user.email,
                    },
                    'match_details': {
                        'route': matched_provider_segment.route,
                        'departure_date_from': matched_provider_segment.departure_date_from.isoformat(),
                        'departure_date_to': matched_provider_segment.departure_date_to.isoformat(),
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"❌ Error notifying provider-provider match: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
    
    @staticmethod
    def _notify_seeker_seeker_match(seeker_request, matched_seeker_request):
        """
        Send notification to seeker about a matching seeker request
        """
        try:
            logger.info(f"🔔 Starting seeker-seeker notification for {seeker_request.user.email}")
            
            from django.utils import timezone
            from datetime import timedelta
            
            recent_cutoff = timezone.now() - timedelta(minutes=1)
            existing_notification = Notification.objects.filter(
                user=seeker_request.user,
                notification_type='itinerary_match',
                data__seeker_request_id=seeker_request.id,
                data__matched_seeker_request_id=matched_seeker_request.id,
                created_at__gte=recent_cutoff
            ).first()
            
            if existing_notification:
                logger.info(f"⏭️ Skipping duplicate notification for seeker {seeker_request.user.email}")
                return
            
            # Create notification record
            notification = Notification.objects.create(
                user=seeker_request.user,
                notification_type='itinerary_match',
                title='Matching Seeker Request Found!',
                message=f"Another seeker has a matching request: {matched_seeker_request.from_airport} → {matched_seeker_request.to_airport}",
                data={
                    'seeker_request_id': seeker_request.id,
                    'matched_seeker_request_id': matched_seeker_request.id,
                    'matched_seeker_user_id': matched_seeker_request.user.id,
                    'matched_route': f"{matched_seeker_request.from_airport} → {matched_seeker_request.to_airport}",
                    'departure_date_from': matched_seeker_request.departure_date_from.isoformat(),
                    'departure_date_to': matched_seeker_request.departure_date_to.isoformat(),
                    'match_type': 'seeker_seeker'
                },
                sender=matched_seeker_request.user,
                priority='normal'
            )
            
            # Send push notification
            firebase_admin_service.send_notification_to_user(
                user=seeker_request.user,
                title='Matching Seeker Request Found!',
                body=f"Another seeker has a matching request: {matched_seeker_request.from_airport} → {matched_seeker_request.to_airport}",
                notification_type='itinerary_match',
                data={
                    'notification_id': notification.id,
                    'seeker_request_id': seeker_request.id,
                    'matched_seeker_request_id': matched_seeker_request.id,
                    'matched_seeker_user_id': matched_seeker_request.user.id,
                    'matched_route': f"{matched_seeker_request.from_airport} → {matched_seeker_request.to_airport}",
                    'match_type': 'seeker_seeker'
                },
                notification_id=notification.id
            )
            
            # Send WebSocket event
            MatchingService._send_websocket_match_event(
                user=seeker_request.user,
                event_type='seeker_seeker_matched',
                data={
                    'seeker_request_id': seeker_request.id,
                    'matched_seeker_info': {
                        'id': matched_seeker_request.user.id,
                        'full_name': matched_seeker_request.user.full_name,
                        'email': matched_seeker_request.user.email,
                    },
                    'match_details': {
                        'route': f"{matched_seeker_request.from_airport} → {matched_seeker_request.to_airport}",
                        'departure_date_from': matched_seeker_request.departure_date_from.isoformat(),
                        'departure_date_to': matched_seeker_request.departure_date_to.isoformat(),
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"❌ Error notifying seeker-seeker match: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
    
    @staticmethod
    def _send_websocket_match_event(user, event_type, data):
        """
        Send WebSocket event for real-time match updates
        """
        try:
            logger.info(f"📡 Starting WebSocket event send for user {user.id}, event: {event_type}")
            
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            
            channel_layer = get_channel_layer()
            if channel_layer:
                group_name = f"chat_updates_{user.id}"
                logger.info(f"📡 Sending to group: {group_name}")
                
                event_data = {
                    'type': event_type,
                    **data
                }
                
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    event_data
                )
                logger.info(f"📡 WebSocket match event sent to user {user.id}: {event_type}")
            else:
                logger.warning("❌ Channel layer not available for WebSocket match event")
                
        except Exception as e:
            logger.error(f"❌ Error sending WebSocket match event: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")

