import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from users.models import Itinerary, SeekerRequest, TravelSegment
from users.services.matching_service import MatchingService

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Itinerary)
def itinerary_created_handler(sender, instance, created, **kwargs):
    """
    Handle new itinerary creation and find matches with seeker requests
    Note: This signal runs when the itinerary is created, but segments might not exist yet.
    The actual matching is handled by the travel_segment_created_handler.
    """
    if created and instance.is_available:
        try:
            MatchingService.cleanup_expired_requests()
            logger.info(f"📋 Itinerary {instance.id} created, waiting for segments to be added")
            
        except Exception as e:
            logger.error(f"Error in itinerary_created_handler: {str(e)}")


@receiver(post_save, sender=TravelSegment)
def travel_segment_created_handler(sender, instance, created, **kwargs):
    """
    Handle new travel segment creation and find matches with seeker requests
    This is the main signal that triggers matching when segments are added to itineraries
    """
    if created and instance.itinerary.is_available:
        try:
            logger.info(f"✈️ Travel segment created for itinerary {instance.itinerary.id}")

            from django.utils import timezone
            from datetime import timedelta
            from users.services.background_tasks import BackgroundTaskManager
            
            recent_cutoff = timezone.now() - timedelta(minutes=5)
            is_new_itinerary = instance.itinerary.created_at >= recent_cutoff
            
            if is_new_itinerary:
                logger.info(f"🆕 New itinerary detected, starting background matching for itinerary {instance.itinerary.id}")
                BackgroundTaskManager.run_matching_async(instance.itinerary.id, 'itinerary')
            else:
                logger.info(f"📝 Existing itinerary updated, skipping matching for itinerary {instance.itinerary.id}")
            
        except Exception as e:
            logger.error(f"Error in travel_segment_created_handler: {str(e)}")


@receiver(post_save, sender=SeekerRequest)
def seeker_request_created_handler(sender, instance, created, **kwargs):
    """
    Handle new seeker request creation and find matches with provider itineraries
    """
    if created and instance.is_active:
        try:
            from users.services.background_tasks import BackgroundTaskManager
            logger.info(f"🆕 New seeker request detected, starting background matching for seeker request {instance.id}")
            BackgroundTaskManager.run_matching_async(instance.id, 'seeker_request')
            
        except Exception as e:
            logger.error(f"Error in seeker_request_created_handler: {str(e)}")
