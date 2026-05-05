from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from users.services.matching_service import MatchingService
import logging

logger = logging.getLogger(__name__)


class MatchingStatsView(APIView):
    """Get matching statistics and test matching functionality"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get matching statistics"""
        try:
            from users.models import SeekerRequest, Itinerary
            
            # Get user's active seeker requests
            user_requests = SeekerRequest.objects.filter(
                user=request.user,
                is_active=True
            ).count()
            
            # Get user's available itineraries
            user_itineraries = Itinerary.objects.filter(
                user=request.user,
                is_available=True
            ).count()
            
            # Get total active requests in system
            total_active_requests = SeekerRequest.objects.filter(
                is_active=True
            ).count()
            
            # Get total available itineraries in system
            total_available_itineraries = Itinerary.objects.filter(
                is_available=True
            ).count()
            
            return Response({
                'user_stats': {
                    'active_seeker_requests': user_requests,
                    'available_itineraries': user_itineraries
                },
                'system_stats': {
                    'total_active_requests': total_active_requests,
                    'total_available_itineraries': total_available_itineraries
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting matching stats: {str(e)}")
            return Response({'error': 'Failed to get matching stats'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TestMatchingView(APIView):
    """Test matching functionality"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Test matching for a specific seeker request or itinerary"""
        try:
            data = request.data
            test_type = data.get('test_type')  # 'seeker_request' or 'itinerary'
            target_id = data.get('target_id')
            
            if not test_type or not target_id:
                return Response({
                    'error': 'test_type and target_id are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            matches = []
            
            if test_type == 'seeker_request':
                from users.models import SeekerRequest
                try:
                    seeker_request = SeekerRequest.objects.get(id=target_id, user=request.user)
                    matches = MatchingService.find_matches_for_new_seeker_request(seeker_request)
                except SeekerRequest.DoesNotExist:
                    return Response({'error': 'Seeker request not found'}, status=status.HTTP_404_NOT_FOUND)
            
            elif test_type == 'itinerary':
                from users.models import Itinerary
                try:
                    itinerary = Itinerary.objects.get(id=target_id, user=request.user)
                    matches = MatchingService.find_matches_for_new_itinerary(itinerary)
                except Itinerary.DoesNotExist:
                    return Response({'error': 'Itinerary not found'}, status=status.HTTP_404_NOT_FOUND)
            
            else:
                return Response({
                    'error': 'test_type must be "seeker_request" or "itinerary"'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            return Response({
                'test_type': test_type,
                'target_id': target_id,
                'matches_found': len(matches),
                'matches': matches
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error testing matching: {str(e)}")
            return Response({'error': 'Failed to test matching'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CleanupExpiredView(APIView):
    """Manually trigger cleanup of expired seeker requests"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Clean up expired seeker requests"""
        try:
            cleaned_count = MatchingService.cleanup_expired_requests()
            
            return Response({
                'message': f'Successfully cleaned up {cleaned_count} expired seeker requests',
                'cleaned_count': cleaned_count
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error cleaning up expired requests: {str(e)}")
            return Response({'error': 'Failed to clean up expired requests'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
