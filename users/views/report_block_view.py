from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from users.models import User, BlockedUser, ReportedUser, Notification
from users.services.firebase_admin_service import firebase_admin_service
import logging

logger = logging.getLogger(__name__)


class BlockUserView(APIView):
    """
    Block a user
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Block a user
        POST /api/users/block/
        Body: {"user_id": 123}
        """
        try:
            user_id = request.data.get('user_id')

            if not user_id:
                return Response(
                    {'error': 'user_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if str(user_id) == str(request.user.id):
                return Response(
                    {'error': 'Cannot block yourself'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                user_to_block = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check if already blocked
            if BlockedUser.objects.filter(blocker=request.user, blocked=user_to_block).exists():
                return Response(
                    {'error': 'User is already blocked'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create block record
            BlockedUser.objects.create(
                blocker=request.user,
                blocked=user_to_block
            )

            return Response({
                'message': 'User blocked successfully',
                'blocked_user': {
                    'id': user_to_block.id,
                    'email': user_to_block.email,
                    'full_name': user_to_block.full_name
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error blocking user: {str(e)}")
            return Response(
                {'error': 'Failed to block user'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UnblockUserView(APIView):
    """
    Unblock a previously blocked user
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Unblock a user
        POST /api/users/unblock/
        Body: {"user_id": 123}
        """
        try:
            user_id = request.data.get('user_id')

            if not user_id:
                return Response(
                    {'error': 'user_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                user_to_unblock = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Find and delete block record
            block_record = BlockedUser.objects.filter(
                blocker=request.user,
                blocked=user_to_unblock
            ).first()

            if not block_record:
                return Response(
                    {'error': 'User is not blocked'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            block_record.delete()

            return Response({
                'message': 'User unblocked successfully',
                'unblocked_user': {
                    'id': user_to_unblock.id,
                    'email': user_to_unblock.email,
                    'full_name': user_to_unblock.full_name
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error unblocking user: {str(e)}")
            return Response(
                {'error': 'Failed to unblock user'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReportUserView(APIView):
    """
    Report a user for inappropriate behavior
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Report a user
        POST /api/users/report/
        Body: {"user_id": 123, "reason": "harassment", "additional_details": "optional details"}
        """
        try:
            user_id = request.data.get('user_id')
            reason = request.data.get('reason')
            additional_details = request.data.get('additional_details', '')

            if not user_id:
                return Response(
                    {'error': 'user_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not reason:
                return Response(
                    {'error': 'reason is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate reason
            valid_reasons = [choice[0] for choice in ReportedUser.REPORT_REASONS]
            if reason not in valid_reasons:
                return Response(
                    {'error': f'Invalid reason. Valid options: {", ".join(valid_reasons)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if str(user_id) == str(request.user.id):
                return Response(
                    {'error': 'Cannot report yourself'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                user_to_report = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check if recently reported (within 24 hours)
            if ReportedUser.is_recently_reported(request.user, user_to_report):
                return Response(
                    {'error': 'You have already reported this user recently'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create report record
            report = ReportedUser.objects.create(
                reporter=request.user,
                reported=user_to_report,
                reason=reason,
                additional_details=additional_details
            )

            # Create notification for the reported user
            notification = Notification.objects.create(
                user=user_to_report,
                notification_type='system',
                title='Account Reported',
                message=f'Your profile has been reported for {report.get_reason_display()}. Please be aware — repeated violations may result in account suspension or deletion.',
                data={
                    'report_id': report.id,
                    'reporter_id': request.user.id,
                    'reason': reason
                }
            )

            # Send push notification to reported user
            try:
                firebase_admin_service.send_notification_to_user(
                    user=user_to_report,
                    title=notification.title,
                    body=notification.message,
                    data=notification.data
                )
            except Exception as e:
                logger.warning(f"Failed to send push notification for report: {str(e)}")

            return Response({
                'message': 'User reported successfully',
                'report': {
                    'id': report.id,
                    'reason': report.get_reason_display(),
                    'created_at': report.created_at.isoformat(),
                    'expires_at': report.expires_at.isoformat()
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error reporting user: {str(e)}")
            return Response(
                {'error': 'Failed to report user'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BlockedUsersView(APIView):
    """
    Get list of blocked users
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Get blocked users list
        GET /api/users/blocked/
        """
        try:
            blocked_users = BlockedUser.objects.filter(
                blocker=request.user
            ).select_related('blocked').order_by('-created_at')

            blocked_data = []
            for block in blocked_users:
                blocked_data.append({
                    'id': block.id,
                    'blocked_user': {
                        'id': block.blocked.id,
                        'email': block.blocked.email,
                        'full_name': block.blocked.full_name,
                        'role': block.blocked.role
                    },
                    'blocked_at': block.created_at.isoformat()
                })

            return Response({
                'blocked_users': blocked_data,
                'count': len(blocked_data)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error getting blocked users: {str(e)}")
            return Response(
                {'error': 'Failed to get blocked users'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
