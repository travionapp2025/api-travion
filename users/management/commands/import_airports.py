from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Airport
import csv
import os
from decimal import Decimal, InvalidOperation
from urllib.request import urlopen
import tempfile


class Command(BaseCommand):
    help = 'Import airports from CSV file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='users/airports.csv',
            help='Path to the CSV file'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing airports before import'
        )
        parser.add_argument(
            '--ourairports',
            action='store_true',
            help='Download and import latest OurAirports airports.csv'
        )
        parser.add_argument(
            '--only-medium-large',
            action='store_true',
            help='Import only medium_airport and large_airport rows'
        )
        parser.add_argument(
            '--upsert',
            action='store_true',
            help='Update existing airports by IATA code instead of skipping when table not empty'
        )
        parser.add_argument(
            '--no-count',
            action='store_true',
            help='Skip initial total row counting for speed on very large files'
        )
        parser.add_argument(
            '--progress-interval',
            type=int,
            default=10,
            help='Print progress every N rows (default: 10)'
        )

    def handle(self, *args, **options):
        csv_file = options['file']
        clear_existing = options['clear']
        use_ourairports = options['ourairports']
        only_medium_large = options['only_medium_large']
        do_upsert = options['upsert']
        no_count = options['no_count']
        progress_interval = max(1, int(options.get('progress_interval') or 10))
        
        if use_ourairports:
            self.stdout.write('Downloading OurAirports airports.csv ...')
            ourairports_url = 'https://ourairports.com/data/airports.csv'
            try:
                with urlopen(ourairports_url, timeout=30) as resp:
                    data = resp.read()
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
                tmp.write(data)
                tmp.flush()
                tmp.close()
                csv_file = tmp.name
                self.stdout.write(self.style.SUCCESS('Download complete.'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to download OurAirports data: {str(e)}'))
                return
        else:
            if not os.path.isabs(csv_file):
                from django.conf import settings
                csv_file = os.path.join(settings.BASE_DIR, csv_file)
        
        if not os.path.exists(csv_file):
            self.stdout.write(
                self.style.ERROR(f'CSV file not found: {csv_file}')
            )
            return
        
        # Clear existing data if requested
        if clear_existing:
            self.stdout.write('Clearing existing airports...')
            Airport.objects.all().delete()
        
        # Check if airports already exist
        if Airport.objects.exists() and not (do_upsert or clear_existing):
            self.stdout.write(
                self.style.WARNING('Airports already exist. Use --clear to replace or --upsert to update.')
            )
            return
        
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

        airports_to_create = []
        imported_count = 0
        skipped_count = 0
        updated_count = 0
        
        self.stdout.write(f'Reading CSV file: {csv_file}')
        
        with open(csv_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            total_rows = None
            if not no_count:
                total_rows = sum(1 for _ in reader)
                file.seek(0)
                reader = csv.DictReader(file)
                self.stdout.write(f'Total rows in CSV: {total_rows}')
            
            for i, row in enumerate(reader, 1):
                try:
                    raw_iata = (row.get('iata_code') or '').strip()
                    iata_code = raw_iata or None

                    row_type = (row.get('type') or '').strip()
                    if only_medium_large and row_type not in ('medium_airport', 'large_airport'):
                        continue

                    if do_upsert and not clear_existing:
                        # Update or create by IATA code
                        values = {
                            'ident': (row.get('ident') or '').strip() or iata_code,
                            'icao_code': (row.get('icao_code') or '').strip() or None,
                            'name': (row.get('name') or '').strip(),
                            'latitude_deg': safe_decimal(row.get('latitude_deg')),
                            'longitude_deg': safe_decimal(row.get('longitude_deg')),
                            'elevation_ft': safe_int(row.get('elevation_ft')),
                            'continent': (row.get('continent') or '').strip(),
                            'iso_country': (row.get('iso_country') or '').strip(),
                            'iso_region': (row.get('iso_region') or '').strip(),
                            'municipality': (row.get('municipality') or '').strip(),
                            'type': row_type,
                            'scheduled_service': (row.get('scheduled_service') or '').strip(),
                            'gps_code': (row.get('gps_code') or '').strip(),
                            'local_code': (row.get('local_code') or '').strip(),
                            'home_link': (row.get('home_link') or '').strip() or None,
                            'wikipedia_link': (row.get('wikipedia_link') or '').strip() or None,
                            'keywords': (row.get('keywords') or '').strip(),
                            'iata_code': iata_code,
                        }
                        # Prefer IATA code for upsert if present, otherwise use ident
                        if iata_code:
                            obj, created = Airport.objects.update_or_create(
                                iata_code=iata_code,
                                defaults=values
                            )
                        else:
                            ident_key = (row.get('ident') or '').strip()
                            obj, created = Airport.objects.update_or_create(
                                ident=ident_key,
                                defaults=values
                            )
                        if created:
                            imported_count += 1
                        else:
                            updated_count += 1
                        if i % progress_interval == 0:
                            if total_rows:
                                self.stdout.write(f'Upserted {i}/{total_rows} rows... (imported: {imported_count}, updated: {updated_count})')
                            else:
                                self.stdout.write(f'Upserted {i} rows... (imported: {imported_count}, updated: {updated_count})')
                    else:
                        airport = Airport(
                            ident=(row.get('ident') or '').strip() or iata_code,
                            iata_code=iata_code,
                            icao_code=(row.get('icao_code') or '').strip() or None,
                            name=(row.get('name') or '').strip(),
                            latitude_deg=safe_decimal(row.get('latitude_deg')),
                            longitude_deg=safe_decimal(row.get('longitude_deg')),
                            elevation_ft=safe_int(row.get('elevation_ft')),
                            continent=(row.get('continent') or '').strip(),
                            iso_country=(row.get('iso_country') or '').strip(),
                            iso_region=(row.get('iso_region') or '').strip(),
                            municipality=(row.get('municipality') or '').strip(),
                            type=row_type,
                            scheduled_service=(row.get('scheduled_service') or '').strip(),
                            gps_code=(row.get('gps_code') or '').strip(),
                            local_code=(row.get('local_code') or '').strip(),
                            home_link=(row.get('home_link') or '').strip() or None,
                            wikipedia_link=(row.get('wikipedia_link') or '').strip() or None,
                            keywords=(row.get('keywords') or '').strip(),
                        )
                        airports_to_create.append(airport)
                        imported_count += 1

                    # Bulk create in batches
                    if len(airports_to_create) >= 1000:
                        with transaction.atomic():
                            Airport.objects.bulk_create(airports_to_create, ignore_conflicts=True)
                        airports_to_create = []
                        if i % progress_interval == 0:
                            if total_rows:
                                self.stdout.write(f'Processed {i}/{total_rows} rows... (created so far: {imported_count})')
                            else:
                                self.stdout.write(f'Processed {i} rows... (created so far: {imported_count})')

                except Exception as e:
                    skipped_count += 1
                    self.stdout.write(f'Error processing row {i}: {str(e)}')
                    continue

            # Create remaining airports
            if airports_to_create:
                with transaction.atomic():
                    Airport.objects.bulk_create(airports_to_create, ignore_conflicts=True)

        self.stdout.write(
            self.style.SUCCESS(
                f'Import completed!\n'
                f'Imported: {imported_count}\n'
                f'Updated: {updated_count}\n'
                f'Skipped (no IATA): {skipped_count}\n'
                f'Total in database: {Airport.objects.count()}'
            )
        )
