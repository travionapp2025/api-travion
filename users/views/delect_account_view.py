from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from users.models import User
import logging

logger = logging.getLogger(__name__)


class DeleteAccountView(APIView):
    """
    Soft delete user account - only authenticated users can delete their own account.
    Marks the user as deleted using the is_deleted flag.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            
            # Check if account is already deleted
            if user.is_deleted:
                return Response(
                    {'error': 'Account is already deleted'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Soft delete: mark the account inactive and prevent future access
            user.is_deleted = True
            user.is_active = False
            user.save(update_fields=['is_deleted', 'is_active', 'updated_at'])
            
            return Response({
                'message': 'Account successfully deleted',
                'status': 'account_deleted'
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Error deleting account for user {request.user.id}: {str(e)}")
            return Response(
                {'error': f'An error occurred: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
