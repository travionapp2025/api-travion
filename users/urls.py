from django.urls import path
from .views import (
    SignupView, LoginView, LogoutView, RefreshTokenView,
    ForgotPasswordOTPView, VerifyOTPView, ResetPasswordOTPView,
    UserProfileView, UpdateUserProfileView, ChangePasswordView
)
from .views.delect_account_view import DeleteAccountView
from .views.report_block_view import BlockUserView, UnblockUserView, ReportUserView, BlockedUsersView
from .views.language_views import (
    LanguageOptionsView,
    SetUserLanguagesView,
)
from .views.itinerary_views import ItineraryListView, ItineraryDetailView, ItineraryMatchView, ItineraryAllView
from .views.seeker_request_views import SeekerRequestListView, SeekerRequestDetailView
from .views.matching_views import MatchingStatsView, CleanupExpiredView
from .views.match_display_views import MatchesView
from .views.my_trips_view import MyTripsView

from .views.pdf_parser_views import PDFItineraryParserView, CreateItineraryFromPDFView

from .views.chat_backend_views import (
    ChatConnectionView,
    ChatConversationsView,
    ChatMessageHistoryView,
    ChatUsersView
)
from .views.notification_views import (
    DeviceTokenView,
    NotificationListView,
    NotificationDetailView,
    MarkAllNotificationsReadView,
    NotificationPreferencesView,
    TestNotificationView,
    CleanupTokensView
)
from .views.airport_views import (
    ImportAirportsView,
    AirportListView,
    AirportDetailView,
    AirportSearchView
)
from .views.contact_views import ContactFeedbackView

app_name = 'users'

urlpatterns = [
    path('signup/', SignupView.as_view(), name='signup'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('token/refresh/', RefreshTokenView.as_view(), name='token_refresh'),
    
    # User Profile Management
    path('profile/me/', UserProfileView.as_view(), name='user_profile'),                   
    path('profile/update/', UpdateUserProfileView.as_view(), name='update_profile'),      
    path('profile/change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('profile/delete/', DeleteAccountView.as_view(), name='delete_account'),
    
    # Block and Report Management
    path('block/', BlockUserView.as_view(), name='block_user'),
    path('unblock/', UnblockUserView.as_view(), name='unblock_user'),
    path('report/', ReportUserView.as_view(), name='report_user'),
    path('blocked/', BlockedUsersView.as_view(), name='blocked_users'),
    
    path('forgot-password/', ForgotPasswordOTPView.as_view(), name='forgot_password_otp'),  
    path('verify-otp/', VerifyOTPView.as_view(), name='verify_otp'),                        
    path('reset-password/', ResetPasswordOTPView.as_view(), name='reset_password_otp'),
    
    # Languages management
    path('languages/options/', LanguageOptionsView.as_view(), name='language_options'),
    path('languages/set/', SetUserLanguagesView.as_view(), name='set_languages'),
    
    # Itinerary Management
    path('itineraries/', ItineraryListView.as_view(), name='itinerary_list'),              
    path('itineraries/<int:itinerary_id>/', ItineraryDetailView.as_view(), name='itinerary_detail'), 
    path('itineraries/match/', ItineraryMatchView.as_view(), name='itinerary_match'),
    path('itineraries/all/', ItineraryAllView.as_view(), name='itineraries_all'),
    
    # Seeker Request Management
    path('seeker-requests/', SeekerRequestListView.as_view(), name='seeker_request_list'),
    path('seeker-requests/<int:request_id>/', SeekerRequestDetailView.as_view(), name='seeker_request_detail'),
    
    # Matching System
    path('matching/stats/', MatchingStatsView.as_view(), name='matching_stats'),
    path('matching/cleanup/', CleanupExpiredView.as_view(), name='cleanup_expired'),
    
    # Unified matches endpoint
    path('matches/', MatchesView.as_view(), name='matches'),
    path('my-trips/', MyTripsView.as_view(), name='my_trips'),
    
    path('itineraries/parse-pdf/', PDFItineraryParserView.as_view(), name='parse_pdf_itinerary'),
    path('itineraries/create-from-pdf/', CreateItineraryFromPDFView.as_view(), name='create_itinerary_from_pdf'),
    
    path('chat/connect/', ChatConnectionView.as_view(), name='chat_connect'),                   
    path('chat/conversations/', ChatConversationsView.as_view(), name='chat_conversations'),      
    path('chat/conversations/<int:conversation_id>/messages/', ChatMessageHistoryView.as_view(), name='chat_message_history'),
    path('chat/users/', ChatUsersView.as_view(), name='chat_users'),  
                              
    # Notification Management
    path('notifications/device-token/', DeviceTokenView.as_view(), name='device_token'),
    path('notifications/', NotificationListView.as_view(), name='notification_list'),
    path('notifications/<int:notification_id>/', NotificationDetailView.as_view(), name='notification_detail'),
    path('notifications/mark-all-read/', MarkAllNotificationsReadView.as_view(), name='mark_all_notifications_read'),
    path('notifications/preferences/', NotificationPreferencesView.as_view(), name='notification_preferences'),
    path('notifications/test/', TestNotificationView.as_view(), name='test_notification'),
    path('notifications/cleanup-tokens/', CleanupTokensView.as_view(), name='cleanup_tokens'),
    
    # Airport Management
    path('airports/import/', ImportAirportsView.as_view(), name='import_airports'),
    path('airports/', AirportListView.as_view(), name='airport_list'),
    path('airports/search/', AirportSearchView.as_view(), name='airport_search'),
    path('airports/<str:iata_code>/', AirportDetailView.as_view(), name='airport_detail_by_iata'),
    path('airports/ident/<str:ident>/', AirportDetailView.as_view(), name='airport_detail_by_ident'),
    
    # Contact/Feedback
    path('contact/', ContactFeedbackView.as_view(), name='contact_feedback'),
]


