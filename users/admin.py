from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User
from .models.chat import Conversation, Message
from .models.match import Match
from .models.itinerary import Itinerary, TravelSegment, SeekerRequest
from .models.itinerary_payment import ItineraryPayment
from .models import Airport

@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'iata_code', 'icao_code', 'municipality', 'iso_country', 'type', 'created_at')
    search_fields = ('name', 'iata_code', 'icao_code', 'municipality', 'iso_country')
    list_filter = ('type', 'continent', 'iso_country', 'created_at')
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'email',
        'firstname',
        'lastname',
        'full_name',
        'phonenumber',
        'role',
        'gender',
        'subscription_type',
        'subscription_status',
        'stripe_customer_id',
        'has_used_free_seek',
        'is_active',
        'is_staff',
        'date_joined',
        'updated_at'
    )
    
    list_filter = (
        'role', 
        'subscription_type',
        'subscription_status',
        'is_active', 
        'is_staff', 
        'date_joined',
        'updated_at'
    )
    
    search_fields = (
        'email', 
        'firstname', 
        'lastname', 
        'phonenumber',
        'stripe_customer_id',
        'stripe_subscription_id'
    )
    
    ordering = ('-date_joined',)
    fieldsets = (
        ('Personal Information', {
            'fields': ('email', 'firstname', 'lastname', 'phonenumber', 'gender')
        }),
        ('Subscription Information', {
            'fields': ('subscription_type', 'subscription_status', 'stripe_customer_id', 'stripe_subscription_id', 'subscription_current_period_end'),
            'classes': ('collapse',)
        }),
        ('Role & Permissions', {
            'fields': ('role', 'is_active', 'is_staff', 'is_superuser')
        }),
        ('Groups & Permissions', {
            'fields': ('groups', 'user_permissions'),
            'classes': ('collapse',)
        }),
        ('Important Dates', {
            'fields': ('last_login', 'date_joined', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    # Fields to display when adding a new user
    add_fieldsets = (
        ('Personal Information', {
            'fields': ('email', 'firstname', 'lastname', 'phonenumber', 'password1', 'password2')
        }),
        ('Role & Permissions', {
            'fields': ('role', 'is_active', 'is_staff', 'is_superuser')
        }),
    )
    
    # Read-only fields
    readonly_fields = ('date_joined', 'updated_at', 'last_login', 'stripe_customer_id', 'stripe_subscription_id')
    
    # Fields to use for the raw_id_fields (for performance with large datasets)
    filter_horizontal = ('groups', 'user_permissions')
    
    # Number of items per page
    list_per_page = 25
    
    # Enable date hierarchy navigation
    date_hierarchy = 'date_joined'


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user1', 'user2', 'itinerary', 'created_at', 'updated_at')
    search_fields = ('user1__email', 'user2__email', 'itinerary__title')
    list_filter = ('itinerary', 'created_at', 'updated_at')
    ordering = ('-updated_at',)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'created_at', 'is_read')
    search_fields = ('sender__email', 'content')
    list_filter = ('is_read', 'created_at')
    ordering = ('-created_at',)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'match_type', 'match_quality', 'user1', 'user2', 'route', 'status', 'created_at', 'expires_at')
    search_fields = ('user1__email', 'user2__email', 'route')
    list_filter = ('match_type', 'match_quality', 'status', 'created_at', 'expires_at')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Match Information', {
            'fields': ('match_type', 'match_quality', 'status', 'route', 'user1', 'user2')
        }),
        ('Provider-Seeker Match', {
            'fields': ('provider_itinerary', 'provider_segment', 'seeker_request'),
            'classes': ('collapse',)
        }),
        ('Provider-Provider Match', {
            'fields': ('matched_provider_itinerary', 'matched_provider_segment'),
            'classes': ('collapse',)
        }),
        ('Seeker-Seeker Match', {
            'fields': ('matched_seeker_request',),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('departure_date_from', 'departure_date_to', 'expires_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class TravelSegmentInline(admin.TabularInline):
    model = TravelSegment
    extra = 0
    fields = ('segment_order', 'from_airport', 'to_airport', 'departure_date_from', 'departure_date_to', 'departure_time_from', 'departure_time_to', 'airline', 'flight_number', 'layovers')
    readonly_fields = ('created_at',)


@admin.register(Itinerary)
class ItineraryAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title', 'travel_type', 'is_available', 'is_first_trip', 'created_at', 'updated_at')
    search_fields = ('user__email', 'title')
    list_filter = ('travel_type', 'is_available', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [TravelSegmentInline]

    fieldsets = (
        ('Itinerary Information', {
            'fields': ('user', 'title', 'travel_type', 'is_available')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TravelSegment)
class TravelSegmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'itinerary', 'from_airport', 'to_airport', 'departure_date_from', 'departure_date_to', 'departure_time_from', 'departure_time_to', 'airline', 'flight_number', 'segment_order', 'route', 'layovers', 'created_at')
    search_fields = ('itinerary__user__email', 'from_airport', 'to_airport', 'airline', 'flight_number')
    list_filter = ('airline', 'flight_number', 'segment_order', 'created_at')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)


@admin.register(SeekerRequest)
class SeekerRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title', 'is_active', 'from_airport', 'to_airport', 'departure_date_from', 'departure_date_to', 'departure_time_from', 'departure_time_to', 'expires_at', 'created_at', 'updated_at')
    search_fields = ('user__email', 'title', 'from_airport', 'to_airport')
    list_filter = ('is_active', 'created_at', 'updated_at')


@admin.register(ItineraryPayment)
class ItineraryPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'itinerary', 'role', 'status', 'platform', 'purchase_id', 'paid_at', 'created_at')
    search_fields = ('user__email', 'user__phonenumber', 'purchase_id', 'itinerary__id')
    list_filter = ('status', 'role', 'platform', 'created_at')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
