import threading
import logging
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """
    Simple background task manager for running matching in the background
    """
    
    @staticmethod
    def run_matching_async(itinerary_id, task_type='itinerary'):
        """
        Run matching in a background thread
        """
        def run_matching():
            try:
                from users.services.matching_service import MatchingService
                from users.models import Itinerary, SeekerRequest
                
                if task_type == 'itinerary':
                    itinerary = Itinerary.objects.get(id=itinerary_id)
                    logger.info(f"🔄 Background matching started for itinerary {itinerary_id}")
                    matches = MatchingService.find_matches_for_new_itinerary(itinerary)
                    logger.info(f"🔄 Background matching completed for itinerary {itinerary_id}: {len(matches)} matches")
                    
                elif task_type == 'seeker_request':
                    seeker_request = SeekerRequest.objects.get(id=itinerary_id)
                    logger.info(f"🔄 Background matching started for seeker request {itinerary_id}")
                    matches = MatchingService.find_matches_for_new_seeker_request(seeker_request, send_notifications=True)
                    logger.info(f"🔄 Background matching completed for seeker request {itinerary_id}: {len(matches)} matches")
                    
            except Exception as e:
                logger.error(f"❌ Background matching failed for {task_type} {itinerary_id}: {str(e)}")
        
        # Run in background thread
        thread = threading.Thread(target=run_matching, daemon=True)
        thread.start()
        logger.info(f"🚀 Started background matching thread for {task_type} {itinerary_id}")


class OptimizedMatchingService:
    """
    Optimized matching service with caching and background processing
    """
    
    @staticmethod
    def find_matches_for_new_itinerary_optimized(itinerary):
        """
        Ultra-optimized matching with caching and background processing
        """
        try:
            if not itinerary.is_available or itinerary.user.role not in ['provider', 'both']:
                return []

            # Check cache first
            cache_key = f"matching_itinerary_{itinerary.id}"
            if cache.get(cache_key):
                logger.info(f"⏭️ Skipping matching for itinerary {itinerary.id} (rate limited)")
                return []
            
            cache.set(cache_key, True, 30)
            logger.info(f"🚀 Starting ultra-optimized matching for itinerary {itinerary.id}")
            
            # Get segments with single query
            segments = list(itinerary.segments.all())
            if not segments:
                logger.info(f"❌ No segments found for itinerary {itinerary.id}")
                return []
            
            # Create route lookup set
            provider_routes = {(s.from_airport, s.to_airport) for s in segments}
            
            # Single optimized query with all filters
            from users.models import SeekerRequest
            matching_requests = SeekerRequest.objects.filter(
                is_active=True,
                expires_at__gt=timezone.now(),
                from_airport__in=[r[0] for r in provider_routes],
                to_airport__in=[r[1] for r in provider_routes]
            ).exclude(user=itinerary.user).select_related('user')
            
            # Filter to exact matches
            exact_matches = [
                req for req in matching_requests 
                if (req.from_airport, req.to_airport) in provider_routes
            ]
            
            logger.info(f"🔍 Found {len(exact_matches)} potential matches")
            
            matches = []
            for seeker_request in exact_matches:
                # Find matching segment
                for segment in segments:
                    if (segment.from_airport == seeker_request.from_airport and 
                        segment.to_airport == seeker_request.to_airport):
                        
                        # Quick checks
                        if (segment.departure_date_from <= seeker_request.departure_date_to and 
                            segment.departure_date_to >= seeker_request.departure_date_from):
                            
                            # Time check (if needed)
                            if (not seeker_request.departure_time_from or not seeker_request.departure_time_to or
                                not segment.departure_time_from or not segment.departure_time_to or
                                (segment.departure_time_from <= seeker_request.departure_time_to and
                                 segment.departure_time_to >= seeker_request.departure_time_from)):
                                
                                matches.append({
                                    'seeker_request': seeker_request,
                                    'seeker_segment': None,
                                    'provider_itinerary': itinerary,
                                    'provider_segment': segment
                                })
                                break
            
            if matches:
                logger.info(f"📤 Sending notifications for {len(matches)} matches")
                from users.services.matching_service import MatchingService
                MatchingService._send_match_notifications(matches)
            else:
                logger.info(f"ℹ️ No matches found for itinerary {itinerary.id}")
            
            return matches
            
        except Exception as e:
            logger.error(f"Error in optimized matching: {str(e)}")
            return []
