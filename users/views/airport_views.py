from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import PageNumberPagination
from django.core.paginator import Paginator
from django.db import transaction
from django.conf import settings
import csv
import os
from users.models import Airport
from decimal import Decimal, InvalidOperation


class AirportPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class ImportAirportsView(APIView):
    """
    POST endpoint to import airport data from CSV file into the database
    """
    permission_classes = [AllowAny]  # Temporarily for testing

    def post(self, request):
        try:
            # Check if airports are already imported
            if Airport.objects.exists():
                return Response({
                    'message': 'Airports data already exists in database',
                    'count': Airport.objects.count()
                }, status=status.HTTP_200_OK)

            csv_file_path = os.path.join(settings.BASE_DIR, 'users', 'airports.csv')
            
            if not os.path.exists(csv_file_path):
                return Response({
                    'error': f'CSV file not found at: {csv_file_path}',
                    'base_dir': str(settings.BASE_DIR),
                    'expected_path': csv_file_path
                }, status=status.HTTP_404_NOT_FOUND)

            # Clear existing data
            Airport.objects.all().delete()
            
            # Read CSV and create airports in batches
            airports_to_create = []
            imported_count = 0
            skipped_count = 0
            
            def safe_decimal(value):
                if not value or value.strip() == '':
                    return None
                try:
                    return Decimal(value.strip())
                except (InvalidOperation, ValueError):
                    return None

            def safe_int(value):
                if not value or value.strip() == '':
                    return None
                try:
                    return int(float(value.strip()))
                except (ValueError, TypeError):
                    return None

            with open(csv_file_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                
                for row in reader:
                    try:
                        iata_code = row.get('iata_code', '').strip()
                        if not iata_code:
                            skipped_count += 1
                            continue

                        airport = Airport(
                            ident=row.get('ident', '').strip(),
                            iata_code=iata_code,
                            icao_code=row.get('icao_code', '').strip() or None,
                            name=row.get('name', '').strip(),
                            latitude_deg=safe_decimal(row.get('latitude_deg')),
                            longitude_deg=safe_decimal(row.get('longitude_deg')),
                            elevation_ft=safe_int(row.get('elevation_ft')),
                            continent=row.get('continent', '').strip(),
                            iso_country=row.get('iso_country', '').strip(),
                            iso_region=row.get('iso_region', '').strip(),
                            municipality=row.get('municipality', '').strip(),
                            type=row.get('type', '').strip(),
                            scheduled_service=row.get('scheduled_service', '').strip(),
                            gps_code=row.get('gps_code', '').strip(),
                            local_code=row.get('local_code', '').strip(),
                            home_link=row.get('home_link', '').strip() or None,
                            wikipedia_link=row.get('wikipedia_link', '').strip() or None,
                            keywords=row.get('keywords', '').strip(),
                        )
                        
                        airports_to_create.append(airport)
                        imported_count += 1

                        # Bulk create in smaller batches for reliability
                        if len(airports_to_create) >= 200:
                            Airport.objects.bulk_create(airports_to_create, ignore_conflicts=True)
                            airports_to_create = []

                    except Exception as e:
                        skipped_count += 1
                        continue

                # Create remaining airports
                if airports_to_create:
                    Airport.objects.bulk_create(airports_to_create, ignore_conflicts=True)

            return Response({
                'message': 'Airports imported successfully',
                'imported_count': imported_count,
                'skipped_count': skipped_count,
                'total_airports': Airport.objects.count()
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                'error': f'Failed to import airports: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AirportListView(APIView):
    """
    GET endpoint to retrieve list of airports with filtering and pagination
    """
    permission_classes = [AllowAny]
    pagination_class = AirportPagination

    def get(self, request):
        try:
            queryset = Airport.objects.all()
            
            # Filtering parameters
            search = request.query_params.get('search', '').strip()
            country = request.query_params.get('country', '').strip()
            continent = request.query_params.get('continent', '').strip()
            airport_type = request.query_params.get('type', '').strip()
            
            if search:
                from django.db.models import Q, Case, When, IntegerField
                queryset = queryset.filter(
                    Q(name__icontains=search)
                    | Q(municipality__icontains=search)
                    | Q(iata_code__icontains=search)
                    | Q(icao_code__icontains=search)
                    | Q(ident__icontains=search)
                    | Q(keywords__icontains=search)
                ).distinct()


                relevance = Case(
                    When(iata_code__iexact=search, then=0),
                    When(iata_code__istartswith=search, then=1),
                    When(icao_code__iexact=search, then=2),
                    When(icao_code__istartswith=search, then=3),
                    When(name__iexact=search, then=4),
                    When(name__istartswith=search, then=5),
                    When(municipality__iexact=search, then=6),
                    When(municipality__istartswith=search, then=7),
                    default=8,
                    output_field=IntegerField(),
                )
                
                queryset = queryset.order_by(relevance, 'name')
            
            if country:
                queryset = queryset.filter(iso_country__iexact=country)
            
            if continent:
                queryset = queryset.filter(continent__iexact=continent)
            
            if airport_type:
                queryset = queryset.filter(type__iexact=airport_type)

            # Pagination
            page_size = int(request.query_params.get('page_size', 50))
            page = int(request.query_params.get('page', 1))
            
            paginator = Paginator(queryset, page_size)
            page_obj = paginator.get_page(page)
            
            airports_data = []
            for airport in page_obj:
                airports_data.append({
                    'id': airport.id,
                    'iata_code': airport.iata_code,
                    'icao_code': airport.icao_code,
                    'name': airport.name,
                    'ident': airport.ident,
                    'location': airport.full_location,
                    'coordinates': airport.coordinates,
                    'continent': airport.continent,
                    'country': airport.iso_country,
                    'municipality': airport.municipality,
                    'type': airport.type,
                    'scheduled_service': airport.scheduled_service,
                    'elevation_ft': airport.elevation_ft,
                })

            return Response({
                'airports': airports_data,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total_pages': paginator.num_pages,
                    'total_count': paginator.count,
                    'has_next': page_obj.has_next(),
                    'has_previous': page_obj.has_previous(),
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'error': f'Failed to retrieve airports: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AirportDetailView(APIView):
    """
    GET endpoint to retrieve detailed information about a specific airport
    """
    permission_classes = [AllowAny]

    def get(self, request, iata_code=None, ident=None):
        try:
            if iata_code:
                airport = Airport.objects.get(iata_code__iexact=iata_code)
            elif ident:
                airport = Airport.objects.get(ident__iexact=ident)
            else:
                return Response({
                    'error': 'Either iata_code or ident parameter is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            airport_data = {
                'id': airport.id,
                'iata_code': airport.iata_code,
                'icao_code': airport.icao_code,
                'name': airport.name,
                'ident': airport.ident,
                'location': airport.full_location,
                'coordinates': airport.coordinates,
                'latitude_deg': float(airport.latitude_deg) if airport.latitude_deg else None,
                'longitude_deg': float(airport.longitude_deg) if airport.longitude_deg else None,
                'elevation_ft': airport.elevation_ft,
                'continent': airport.continent,
                'country': airport.iso_country,
                'region': airport.iso_region,
                'municipality': airport.municipality,
                'type': airport.type,
                'scheduled_service': airport.scheduled_service,
                'gps_code': airport.gps_code,
                'local_code': airport.local_code,
                'home_link': airport.home_link,
                'wikipedia_link': airport.wikipedia_link,
                'keywords': airport.keywords,
                'created_at': airport.created_at,
                'updated_at': airport.updated_at,
            }

            return Response({
                'airport': airport_data
            }, status=status.HTTP_200_OK)

        except Airport.DoesNotExist:
            return Response({
                'error': 'Airport not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({
                'error': f'Failed to retrieve airport details: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AirportSearchView(APIView):
    """
    GET endpoint for searching airports by IATA code, ICAO code, or name
    """
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            query = request.query_params.get('q', '').strip()
            limit = int(request.query_params.get('limit', 20))
            
            if not query or len(query) < 2:
                return Response({
                    'error': 'Search query must be at least 2 characters long'
                }, status=status.HTTP_400_BAD_REQUEST)

            from django.db.models import Q, Case, When, IntegerField

            base_qs = Airport.objects.filter(
                Q(iata_code__icontains=query)
                | Q(icao_code__icontains=query)
                | Q(name__icontains=query)
                | Q(municipality__icontains=query)
                | Q(ident__icontains=query)
                | Q(keywords__icontains=query)
            ).distinct()

            # Simple relevance ordering: exact IATA first, then prefix matches, then others
            relevance = Case(
                When(municipality__iexact=query, then=0),
                When(name__iexact=query, then=1),
                When(municipality__istartswith=query, then=2),
                When(name__istartswith=query, then=3),
                When(iata_code__istartswith=query, then=4),
                When(icao_code__istartswith=query, then=5),
                default=6,
                output_field=IntegerField(),
            )

            queryset = base_qs.order_by(relevance, 'name')[:limit]

            airports_data = []
            for airport in queryset:
                airports_data.append({
                    'id': airport.id,
                    'iata_code': airport.iata_code,
                    'icao_code': airport.icao_code,
                    'name': airport.name,
                    'location': airport.full_location,
                    'country': airport.iso_country,
                })

            return Response({
                'airports': airports_data,
                'query': query,
                'count': len(airports_data)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'error': f'Search failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
