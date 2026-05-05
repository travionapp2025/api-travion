import json
from datetime import datetime, timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.core.exceptions import ValidationError
from users.models import SeekerRequest
import logging

logger = logging.getLogger(__name__)


class SeekerRequestListView(APIView):
    """List and create seeker requests"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get user's seeker requests"""
        try:
            limit = int(request.query_params.get('limit', 50))
            offset = int(request.query_params.get('offset', 0))
            active_only = request.query_params.get('active_only', 'true').lower() == 'true'
            
            requests = SeekerRequest.objects.filter(user=request.user)
            
            if active_only:
                requests = requests.filter(is_active=True)
            
            requests = requests.order_by('-created_at')[offset:offset+limit]
            
            requests_data = []
            for req in requests:
                requests_data.append({
                    'id': req.id,
                    'title': req.title,
                    'is_active': req.is_active,
                    'is_expired': req.is_expired,
                    'from_airport': req.from_airport,
                    'to_airport': req.to_airport,
                    'departure_date_from': req.departure_date_from.isoformat(),
                    'departure_date_to': req.departure_date_to.isoformat(),
                    'departure_time_from': req.departure_time_from.isoformat() if req.departure_time_from else None,
                    'departure_time_to': req.departure_time_to.isoformat() if req.departure_time_to else None,
                    'expires_at': req.expires_at.isoformat(),
                    'created_at': req.created_at.isoformat(),
                    'updated_at': req.updated_at.isoformat(),
                })
            
            return Response({
                'requests': requests_data,
                'total_count': SeekerRequest.objects.filter(user=request.user).count()
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting seeker requests: {str(e)}")
            return Response({'error': 'Failed to get seeker requests'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        """Create a new seeker request"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            # Extract request data with date ranges
            from_airport = data.get('from_airport', '').strip().upper()
            to_airport = data.get('to_airport', '').strip().upper()
            departure_date_from = data.get('departure_date_from')
            departure_date_to = data.get('departure_date_to')
            departure_time_from = data.get('departure_time_from')
            departure_time_to = data.get('departure_time_to')
            
            # Validation errors
            errors = {}
            
            if not from_airport:
                errors['from_airport'] = 'From airport is required'
            elif len(from_airport) != 3:
                errors['from_airport'] = 'From airport must be 3 characters'
            
            if not to_airport:
                errors['to_airport'] = 'To airport is required'
            elif len(to_airport) != 3:
                errors['to_airport'] = 'To airport must be 3 characters'
            
            if not departure_date_from:
                errors['departure_date_from'] = 'Departure date from is required'
            if not departure_date_to:
                errors['departure_date_to'] = 'Departure date to is required'
            
            if errors:
                return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
            
            # Parse dates and times
            try:
                departure_date_from = datetime.strptime(departure_date_from, '%Y-%m-%d').date()
                departure_date_to = datetime.strptime(departure_date_to, '%Y-%m-%d').date()
                departure_time_from = datetime.strptime(departure_time_from, '%H:%M').time() if departure_time_from else None
                departure_time_to = datetime.strptime(departure_time_to, '%H:%M').time() if departure_time_to else None
                
                # Validate date range
                if departure_date_from > departure_date_to:
                    return Response({'error': 'Departure date from cannot be after departure date to'}, status=status.HTTP_400_BAD_REQUEST)
            except ValueError as e:
                return Response({'error': f'Invalid date/time format: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
            
            # ❗ Check if overlapping seeker request already exists
            existing_request = SeekerRequest.objects.filter(
                user=request.user,
                from_airport=from_airport,
                to_airport=to_airport,
                is_active=True,
                # Date overlap:
                departure_date_from__lte=departure_date_to,
                departure_date_to__gte=departure_date_from
            ).first()

            if existing_request:
                return Response({
                    "error": "A request already exists for this route within the date range you selected.",
                    "existing_request": {
                        "id": existing_request.id,
                        "from_airport": existing_request.from_airport,
                        "to_airport": existing_request.to_airport,
                        "departure_date_from": existing_request.departure_date_from.isoformat(),
                        "departure_date_to": existing_request.departure_date_to.isoformat(),
                    }
                }, status=status.HTTP_400_BAD_REQUEST)

            
            # Create seeker request
            seeker_request = SeekerRequest.objects.create(
                user=request.user,
                title=f"Travel Request {from_airport} → {to_airport} ({departure_date_from} to {departure_date_to})",
                from_airport=from_airport,
                to_airport=to_airport,
                departure_date_from=departure_date_from,
                departure_date_to=departure_date_to,
                departure_time_from=departure_time_from,
                departure_time_to=departure_time_to,
                expires_at=timezone.now()  # Will be set automatically
            )
            
            # Set automatic expiration based on travel date
            seeker_request.set_automatic_expiration()
            seeker_request.save()
            
            # Perform matching synchronously to save matches to database
            from users.services.matching_service import MatchingService
            matches = MatchingService.find_matches_for_new_seeker_request(seeker_request, send_notifications=True)
            logger.info(f"Found and saved {len(matches)} matches for new seeker request {seeker_request.id}")
            
            # Get immediate matches for user feedback
            immediate_matches = []
            for match in matches:
                immediate_matches.append({
                    'match_type': 'immediate_match',
                    'provider': {
                        'id': match['provider_itinerary'].user.id,
                        'full_name': match['provider_itinerary'].user.full_name,
                        'email': match['provider_itinerary'].user.email,
                        'role': match['provider_itinerary'].user.role,
                        'profile_picture': (match['provider_itinerary'].user.profile_picture.url if match['provider_itinerary'].user.profile_picture else None),
                        'bio': match['provider_itinerary'].user.bio,
                    },
                    'matched_route': match['provider_segment'].route,
                    'departure_date_from': match['provider_segment'].departure_date_from.isoformat(),
                    'departure_date_to': match['provider_segment'].departure_date_to.isoformat(),
                    'departure_time_from': match['provider_segment'].departure_time_from.isoformat() if match['provider_segment'].departure_time_from else None,
                    'departure_time_to': match['provider_segment'].departure_time_to.isoformat() if match['provider_segment'].departure_time_to else None,
                    'chat_connection': {
                        'websocket_url': f"ws://localhost:8000/ws/chat/{match['provider_itinerary'].user.id}/",
                        'other_user_id': match['provider_itinerary'].user.id,
                        'requires_token': True,
                        'token_param': 'token'
                    }
                })
            
            return Response({
                'message': f'Seeker request created successfully! Found {len(immediate_matches)} immediate matches.',
                'immediate_matches': immediate_matches,
                'request': {
                    'id': seeker_request.id,
                    'title': seeker_request.title,
                    'is_active': seeker_request.is_active,
                    'is_expired': seeker_request.is_expired,
                    'from_airport': seeker_request.from_airport,
                    'to_airport': seeker_request.to_airport,
                    'departure_date_from': seeker_request.departure_date_from.isoformat(),
                    'departure_date_to': seeker_request.departure_date_to.isoformat(),
                    'departure_time_from': seeker_request.departure_time_from.isoformat() if seeker_request.departure_time_from else None,
                    'departure_time_to': seeker_request.departure_time_to.isoformat() if seeker_request.departure_time_to else None,
                    'expires_at': seeker_request.expires_at.isoformat(),
                    'created_at': seeker_request.created_at.isoformat(),
                    'updated_at': seeker_request.updated_at.isoformat(),
                }
            }, status=status.HTTP_201_CREATED)
            
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creating seeker request: {str(e)}")
            return Response({'error': 'Failed to create seeker request'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SeekerRequestDetailView(APIView):
    """Get, update, or delete a specific seeker request"""
    permission_classes = [IsAuthenticated]

    def get(self, request, request_id):
        """Get a specific seeker request"""
        try:
            seeker_request = SeekerRequest.objects.get(id=request_id, user=request.user)
            
            return Response({
                'id': seeker_request.id,
                'title': seeker_request.title,
                'is_active': seeker_request.is_active,
                'is_expired': seeker_request.is_expired,
                'from_airport': seeker_request.from_airport,
                'to_airport': seeker_request.to_airport,
                'departure_date_from': seeker_request.departure_date_from.isoformat(),
                'departure_date_to': seeker_request.departure_date_to.isoformat(),
                'departure_time_from': seeker_request.departure_time_from.isoformat() if seeker_request.departure_time_from else None,
                'departure_time_to': seeker_request.departure_time_to.isoformat() if seeker_request.departure_time_to else None,
                'expires_at': seeker_request.expires_at.isoformat(),
                'created_at': seeker_request.created_at.isoformat(),
                'updated_at': seeker_request.updated_at.isoformat(),
            }, status=status.HTTP_200_OK)
            
        except SeekerRequest.DoesNotExist:
            return Response({'error': 'Seeker request not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error getting seeker request: {str(e)}")
            return Response({'error': 'Failed to get seeker request'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def patch(self, request, request_id):
        """Update a seeker request"""
        try:
            seeker_request = SeekerRequest.objects.get(id=request_id, user=request.user)
            
            if seeker_request.is_expired:
                return Response({'error': 'Cannot update expired request'}, status=status.HTTP_400_BAD_REQUEST)
            
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            # Update fields
            if 'is_active' in data:
                seeker_request.is_active = bool(data['is_active'])
            
            seeker_request.save()
            
            return Response({'message': 'Seeker request updated successfully'}, status=status.HTTP_200_OK)
            
        except SeekerRequest.DoesNotExist:
            return Response({'error': 'Seeker request not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error updating seeker request: {str(e)}")
            return Response({'error': 'Failed to update seeker request'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, request_id):
        """Delete a seeker request"""
        try:
            seeker_request = SeekerRequest.objects.get(id=request_id, user=request.user)
            seeker_request.delete()
            
            return Response({'message': 'Seeker request deleted successfully'}, status=status.HTTP_200_OK)
            
        except SeekerRequest.DoesNotExist:
            return Response({'error': 'Seeker request not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error deleting seeker request: {str(e)}")
            return Response({'error': 'Failed to delete seeker request'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)