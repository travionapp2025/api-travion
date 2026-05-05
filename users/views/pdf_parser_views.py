import base64
import json
import re
import logging
import os
from datetime import datetime, date, time
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.files.base import ContentFile
from users.models import Itinerary, TravelSegment
import PyPDF2
import pdfplumber
import openai
from typing import List, Dict, Any
from users.views.ai_itenerary import get_ai_itenerary_response

logger = logging.getLogger(__name__)


class PDFItineraryParserView(APIView):
    """
    OpenAI-powered parser for extracting itinerary information from PDFs or images.
    """
    permission_classes = [IsAuthenticated]

    def __init__(self):
        super().__init__()
        self.openai_client = openai.OpenAI(
            api_key=os.getenv('OPENAI_API_KEY')
        )
        self.openai_model = os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo')
        self.openai_vision_model = os.getenv('OPENAI_VISION_MODEL', 'gpt-4o-mini')

    def post(self, request):
        """Upload and parse a PDF or image file to extract itinerary information using OpenAI"""
        try:
            upload = (
                request.FILES.get('file')
                or request.FILES.get('pdf_file')
                or request.FILES.get('image_file')
            )

            if not upload:
                return Response({'error': 'No file provided. Upload a PDF or image.'}, status=status.HTTP_400_BAD_REQUEST)

            filename = upload.name.lower()
            content_type = (upload.content_type or '').lower()
            is_pdf = filename.endswith('.pdf') or content_type == 'application/pdf'
            is_image = content_type.startswith('image/') or filename.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'))

            if not is_pdf and not is_image:
                return Response({'error': 'Unsupported file type. Provide a PDF or image (png/jpg/jpeg/webp/bmp/tiff).'}, status=status.HTTP_400_BAD_REQUEST)

            if upload.size > 10 * 1024 * 1024:
                return Response({'error': 'File size too large. Maximum 10MB allowed'}, status=status.HTTP_400_BAD_REQUEST)

            extracted_text = ""

            if is_pdf:
                extracted_text = self.extract_pdf_text(upload)
                failure_msg = 'Could not extract text from PDF'
            else:
                extracted_text = self.extract_image_text(upload)
                failure_msg = 'Could not extract text from image'

            if not extracted_text.strip():
                return Response({'error': failure_msg}, status=status.HTTP_400_BAD_REQUEST)

            try:
                parsed_data = get_ai_itenerary_response(self.openai_client, extracted_text)
            except ValueError as e:
                # Validation failed - content is not an itinerary
                logger.warning(f"Validation failed for user {getattr(request.user, 'id', 'unknown')}: {str(e)}")
                return Response({
                    'error': 'The uploaded file does not contain flight itinerary information',
                    'details': str(e)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            return Response({
                'message': 'File parsed successfully using OpenAI',
                'extracted_text': extracted_text[:500] + '...' if len(extracted_text) > 500 else extracted_text,
                'parsed_itinerary': parsed_data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error parsing file for user {getattr(request.user, 'id', 'unknown')}: {str(e)}")
            return Response({'error': f'Failed to parse file: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def extract_pdf_text(self, pdf_file):
        """Extract text from PDF using pdfplumber and PyPDF2 as fallback"""
        text_content = ""
        
        try:
            pdf_file.seek(0)
            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_content += page_text + "\n"
            
            if len(text_content.strip()) < 100:
                pdf_file.seek(0)
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_content += page_text + "\n"
                        
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {str(e)}")
            raise e
            
        return text_content

    def extract_image_text(self, image_file):
        """Extract text from an image using OpenAI vision models"""
        if not os.getenv('OPENAI_API_KEY'):
            raise ValueError("OPENAI_API_KEY is required for image parsing")

        try:
            image_file.seek(0)
            image_bytes = image_file.read()
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            mime_type = (image_file.content_type or 'image/png').lower()

            prompt = (
                "You are a travel document OCR. Extract all visible text from this ticket or itinerary "
                "image. Preserve line breaks when helpful, and only return plain text."
            )

            response = self.openai_client.chat.completions.create(
                model=self.openai_vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
                        ],
                    }
                ],
                max_tokens=800,
                temperature=0,
            )

            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Error extracting text from image: {str(e)}")
            raise e

    def parse_itinerary_with_openai(self, text: str) -> Dict[str, Any]:
        """Parse itinerary data using OpenAI GPT"""
        try:
            # Check if OpenAI API key is configured
            if not os.getenv('OPENAI_API_KEY'):
                logger.warning("OpenAI API key not configured in environment variables, falling back to regex parsing")
                return self.parse_itinerary_data_fallback(text)
            
            if len(text) > 15000: 
                return self.parse_long_itinerary_with_openai(text)
            
            prompt = self.create_itinerary_extraction_prompt(text)
            
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": "You are an expert at extracting travel itinerary information from PDF text. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=2000
            )
            
            extracted_data = json.loads(response.choices[0].message.content)
            validated_data = self.validate_and_clean_extracted_data(extracted_data)
            
            return validated_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {str(e)}")
            return self.parse_itinerary_data_fallback(text)
        except openai.NotFoundError as e:
            logger.error(f"OpenAI model not found or no access: {str(e)}")
            logger.info("Falling back to regex parsing. Consider using gpt-3.5-turbo or checking your OpenAI account access.")
            return self.parse_itinerary_data_fallback(text)
        except openai.AuthenticationError as e:
            logger.error(f"OpenAI authentication failed: {str(e)}")
            logger.info("Check your OPENAI_API_KEY in environment variables.")
            return self.parse_itinerary_data_fallback(text)
        except openai.RateLimitError as e:
            logger.error(f"OpenAI rate limit exceeded: {str(e)}")
            logger.info("Rate limit exceeded, falling back to regex parsing.")
            return self.parse_itinerary_data_fallback(text)
        except Exception as e:
            logger.error(f"OpenAI parsing failed: {str(e)}")
            return self.parse_itinerary_data_fallback(text)
    
    def parse_long_itinerary_with_openai(self, text: str) -> Dict[str, Any]:
        """Parse long itineraries by segmenting the text"""
        try:
            # Split text into chunks
            chunks = self.split_text_into_chunks(text, max_chunk_size=12000)
            
            all_segments = []
            passenger_name = None
            pnr = None
            booking_reference = None
            total_amount = None
            currency = None
            
            # Process each chunk
            for i, chunk in enumerate(chunks):
                logger.info(f"Processing chunk {i+1}/{len(chunks)}")
                
                prompt = self.create_itinerary_extraction_prompt(chunk, chunk_index=i, total_chunks=len(chunks))
                
                response = self.openai_client.chat.completions.create(
                    model=self.openai_model,
                    messages=[
                        {"role": "system", "content": "You are an expert at extracting travel itinerary information from PDF text. Always respond with valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=2000
                )
                
                chunk_data = json.loads(response.choices[0].message.content)
                
                if chunk_data.get('segments'):
                    all_segments.extend(chunk_data['segments'])
                
                if not passenger_name and chunk_data.get('passenger_name'):
                    passenger_name = chunk_data['passenger_name']
                if not pnr and chunk_data.get('pnr'):
                    pnr = chunk_data['pnr']
                if not booking_reference and chunk_data.get('booking_reference'):
                    booking_reference = chunk_data['booking_reference']
                if not total_amount and chunk_data.get('total_amount'):
                    total_amount = chunk_data['total_amount']
                if not currency and chunk_data.get('currency'):
                    currency = chunk_data['currency']
            
            combined_data = {
                'pnr': pnr,
                'booking_reference': booking_reference,
                'passenger_name': passenger_name,
                'segments': all_segments,
                'total_amount': total_amount,
                'currency': currency
            }
            
            return self.validate_and_clean_extracted_data(combined_data)
            
        except openai.NotFoundError as e:
            logger.error(f"OpenAI model not found or no access: {str(e)}")
            logger.info("Falling back to regex parsing. Consider using gpt-3.5-turbo or checking your OpenAI account access.")
            return self.parse_itinerary_data_fallback(text)
        except openai.AuthenticationError as e:
            logger.error(f"OpenAI authentication failed: {str(e)}")
            logger.info("Check your OPENAI_API_KEY in environment variables.")
            return self.parse_itinerary_data_fallback(text)
        except openai.RateLimitError as e:
            logger.error(f"OpenAI rate limit exceeded: {str(e)}")
            logger.info("Rate limit exceeded, falling back to regex parsing.")
            return self.parse_itinerary_data_fallback(text)
        except Exception as e:
            logger.error(f"Failed to parse long itinerary: {str(e)}")
            return self.parse_itinerary_data_fallback(text)
    
    def create_itinerary_extraction_prompt(self, text: str, chunk_index: int = 0, total_chunks: int = 1) -> str:
        """Create a detailed prompt for OpenAI to extract itinerary information"""
        chunk_info = f" (Chunk {chunk_index + 1} of {total_chunks})" if total_chunks > 1 else ""
        
        prompt = f"""
            Extract travel itinerary information from the following PDF text{chunk_info}. 

            Return ONLY a valid JSON object with this exact structure:

            {{
                "pnr": "string or null",
                "booking_reference": "string or null", 
                "passenger_name": "string or null",
                "segments": [
                    {{
                        "airline": "string",
                        "flight_number": "string",
                        "from_airport": "3-letter IATA code",
                        "to_airport": "3-letter IATA code", 
                        "departure_date_from": "YYYY-MM-DD",
                        "departure_date_to": "YYYY-MM-DD",
                        "departure_time_from": "HH:MM or null",
                        "departure_time_to": "HH:MM or null",
                        "arrival_date_from": "YYYY-MM-DD",
                        "arrival_date_to": "YYYY-MM-DD", 
                        "arrival_time_from": "HH:MM or null",
                        "arrival_time_to": "HH:MM or null"
                    }}
                ],
                "total_amount": "string or null",
                "currency": "string or null"
            }}

            IMPORTANT RULES:
            1. Extract ALL flight segments found in the text
            2. Use 3-letter IATA airport codes (e.g., "LAX", "JFK", "SFO")
            3. Dates must be returned in strict YYYY-MM-DD format. If the source date is in another format (e.g., 26Feb2006, 26/02/2006, 02-26-06), normalize and convert it to YYYY-MM-DD (e.g., 26Feb2006 -> 2006-02-26).
            4. For times, use HH:MM format (24-hour) or null if not specified
            5. If departure/arrival dates are the same, set both "from" and "to" to the same date
            6. If times are not specified, use null
            7. Extract airline codes (e.g., "AA", "DL", "UA") and flight numbers
            8. Look for PNR, booking reference, passenger name, and total amount
            9. If information is not found, use null
            10. Return ONLY the JSON object, no other text

            PDF Text:
            {text}
            """
        return prompt
    
    def split_text_into_chunks(self, text: str, max_chunk_size: int = 12000) -> List[str]:
        """Split long text into manageable chunks"""
        chunks = []
        sentences = text.split('. ')
        
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk + sentence) > max_chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                current_chunk += sentence + ". "
        
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def validate_and_clean_extracted_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and clean the extracted data"""
        try:
            # Ensure required structure
            validated_data = {
                'pnr': data.get('pnr'),
                'booking_reference': data.get('booking_reference'),
                'passenger_name': data.get('passenger_name'),
                'segments': data.get('segments', []),
                'total_amount': data.get('total_amount'),
                'currency': data.get('currency')
            }
            
            # Validate segments
            validated_segments = []
            for segment in validated_data['segments']:
                if isinstance(segment, dict):
                    validated_segment = {
                        'airline': segment.get('airline', ''),
                        'flight_number': segment.get('flight_number', ''),
                        'from_airport': segment.get('from_airport', '').upper()[:3] if segment.get('from_airport') else '',
                        'to_airport': segment.get('to_airport', '').upper()[:3] if segment.get('to_airport') else '',
                        'departure_date_from': segment.get('departure_date_from'),
                        'departure_date_to': segment.get('departure_date_to'),
                        'departure_time_from': segment.get('departure_time_from'),
                        'departure_time_to': segment.get('departure_time_to'),
                        'arrival_date_from': segment.get('arrival_date_from'),
                        'arrival_date_to': segment.get('arrival_date_to'),
                        'arrival_time_from': segment.get('arrival_time_from'),
                        'arrival_time_to': segment.get('arrival_time_to')
                    }
                    
                    # Only add segment if it has required fields
                    if validated_segment['from_airport'] and validated_segment['to_airport']:
                        validated_segments.append(validated_segment)
            
            validated_data['segments'] = validated_segments
            
            return validated_data
            
        except Exception as e:
            logger.error(f"Error validating extracted data: {str(e)}")
            return data
    
    def parse_itinerary_data_fallback(self, text):
        """Fallback parsing using regex patterns (original implementation)"""
        # Clean the text
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Initialize result
        result = {
            'pnr': None,
            'booking_reference': None,
            'passenger_name': None,
            'segments': [],
            'total_amount': None,
            'currency': None
        }
        
        # Extract each field using original methods
        result['pnr'] = self.extract_pnr(text)
        result['booking_reference'] = self.extract_booking_reference(text)
        result['passenger_name'] = self.extract_passenger_name(text)
        result['segments'] = self.extract_flight_segments(text)
        result['total_amount'] = self.extract_total_amount(text)
        result['currency'] = self.extract_currency(text)
        
        return result

    def extract_pnr(self, text):
        """Extract PNR from text - generic for any airline"""
        # Patterns in order of preference
        patterns = [
            # Pattern: PNR: CODE or PNR CODE
            r'PNR[:\s]*([A-Z0-9]{5,8})',
            # Pattern: Booking Reference: CODE
            r'(?:Booking|Reference|Record Locator)[:\s]*([A-Z0-9]{5,8})',
            # Pattern: Confirmation: CODE
            r'Confirmation[:\s]*([A-Z0-9]{5,8})',
            # Pattern: Generic alphanumeric codes (6-10 chars)
            r'\b([A-Z0-9]{6,10})\b(?=.*(?:PNR|Booking|Reference))',
            # Pattern: Common PNR formats (Letter-Number-Letter patterns)
            r'\b([A-Z][0-9][A-Z][0-9][A-Z][0-9])\b',
            r'\b([A-Z]{2,3}[0-9]{3,6})\b',
            # Pattern: Duration followed by PNR (for some formats)
            r'(\d+hr\s+\d+min)\s+([A-Z0-9]{5,8})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    pnr = match[1] if len(match) > 1 else match[0]
                else:
                    pnr = match
                
                if len(pnr) >= 5:
                    return pnr.upper()
        
        return None

    def extract_booking_reference(self, text):
        """Extract booking reference from text - generic for any airline"""
        patterns = [
            # Pattern: Booking Reference: NUMBER
            r'Booking Reference[:\s]*([A-Z0-9]+)',
            # Pattern: Reference Number: NUMBER
            r'Reference Number[:\s]*([A-Z0-9]+)',
            # Pattern: Confirmation Number: NUMBER
            r'Confirmation Number[:\s]*([A-Z0-9]+)',
            # Pattern: Reservation Number: NUMBER
            r'Reservation Number[:\s]*([A-Z0-9]+)',
            # Pattern: Ticket Number: NUMBER
            r'Ticket Number[:\s]*([A-Z0-9]+)',
            # Pattern: Generic reference patterns
            r'(?:YATRA|EXPEDIA|BOOKING|TRAVEL|AGENT)\s+REF\s+NUMBER[:\s]*([0-9]+)',
            # Pattern: Long numeric references (10+ digits)
            r'\b(\d{10,})\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None

    def extract_passenger_name(self, text):
        """Extract passenger name from text"""
        patterns = [
            r'(?:Mr|Ms|Mrs|Dr|Miss)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*\(Adult\)',
            r'PASSENGERS?\s+DETAILS.*?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                name = match.group(1).strip()
                # Filter out false positives
                if not any(word in name.lower() for word in ['download', 'app', 'android', 'ios', 'yatra', 'flight', 'ticket']):
                    return name
        
        return None

    def extract_flight_segments(self, text):
        """Extract flight segments from text - generic for any airline"""
        segments = []
        
        # Extract airports first (most reliable)
        airports = re.findall(r'\b([A-Z]{3})\b', text)
        valid_airports = [airport for airport in airports if airport not in 
                        ['REF', 'NA', 'APP', 'AND', 'ER', 'NO', 'KG', 'FREE', 'TKT', 'PNR', 'FLT']]
        
        if len(valid_airports) < 2:
            return segments
        
        # Extract dates
        dates = self.extract_dates(text)
        if not dates:
            return segments
        
        # Extract flight numbers and airlines
        flight_info = self.extract_flight_info(text)
        
        # Extract times
        times = self.extract_times(text)
        
        # Create segments
        for i, flight_data in enumerate(flight_info):
            if i < len(dates) and i < len(valid_airports) - 1:
                segment = {
                    'airline': flight_data.get('airline', ''),
                    'flight_number': flight_data.get('flight_number', ''),
                    'from_airport': valid_airports[i],
                    'to_airport': valid_airports[i + 1],
                    'departure_date': dates[i].strftime('%Y-%m-%d') if dates[i] else None,
                    'arrival_date': dates[i].strftime('%Y-%m-%d') if dates[i] else None,
                    'departure_time': times[i * 2].strftime('%H:%M') if len(times) > i * 2 else None,
                    'arrival_time': times[i * 2 + 1].strftime('%H:%M') if len(times) > i * 2 + 1 else None
                }
                segments.append(segment)
        
        return segments

    def extract_flight_info(self, text):
        """Extract airline and flight number combinations"""
        flight_info = []
        
        # Multiple patterns for different ticket formats
        patterns = [
            # Pattern: Airline Code + Flight Number (e.g., "AA 1234", "DL 5678")
            r'\b([A-Z]{2,3})\s+(\d{2,4})\b',
            # Pattern: Airline Code - Flight Number (e.g., "AA-1234", "DL-5678") 
            r'\b([A-Z]{2,3})\s*-\s*(\d{2,4})\b',
            # Pattern: Flight Number + Airline (e.g., "1234 AA", "5678 DL")
            r'\b(\d{2,4})\s+([A-Z]{2,3})\b',
            # Pattern with airline name (e.g., "American Airlines AA 1234")
            r'(?:American|Delta|United|Southwest|JetBlue|Alaska|Hawaiian|Frontier|Spirit|Vistara|IndiGo|SpiceJet|Air India)\s+([A-Z]{2,3})\s+(\d{2,4})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match) == 2:
                    # Determine which is airline code and which is flight number
                    if match[0].isalpha() and match[1].isdigit():
                        airline, flight_num = match
                    elif match[0].isdigit() and match[1].isalpha():
                        flight_num, airline = match
                    else:
                        continue
                    
                    flight_info.append({
                        'airline': airline.upper(),
                        'flight_number': flight_num
                    })
        
        return flight_info

    def extract_dates(self, text):
        """Extract dates from text"""
        dates = []
        
        # Multiple date patterns
        patterns = [
            # Pattern: "Wed, Nov 18 2020"
            r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}),?\s+(\d{4})',
            # Pattern: "11/18/2020" or "18/11/2020"
            r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})',
            # Pattern: "2020-11-18"
            r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
            # Pattern: "November 18, 2020"
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}),?\s+(\d{4})',
        ]
        
        month_map = {
            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
        }
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    if len(match) == 4 and match[0] in month_map:
                        # "Wed, Nov 18 2020" format
                        day_name, month_name, day, year = match
                        flight_date = date(int(year), month_map[month_name], int(day))
                        dates.append(flight_date)
                    elif len(match) == 3:
                        if match[0].isdigit() and match[1].isdigit() and match[2].isdigit():
                            # "11/18/2020" or "18/11/2020" format
                            if len(match[2]) == 4:  # Full year
                                year = int(match[2])
                                if int(match[0]) > 12:  # DD/MM/YYYY
                                    day, month, year = int(match[0]), int(match[1]), year
                                else:  # MM/DD/YYYY
                                    month, day, year = int(match[0]), int(match[1]), year
                                flight_date = date(year, month, day)
                                dates.append(flight_date)
                        elif match[0] in month_map:
                            # "November 18, 2020" format
                            month_name, day, year = match
                            flight_date = date(int(year), month_map[month_name], int(day))
                            dates.append(flight_date)
                except (ValueError, TypeError):
                    continue
        
        return dates

    def extract_times(self, text):
        """Extract times from text"""
        times = []
        
        # Multiple time patterns
        patterns = [
            # Pattern: "13:25 Hrs" or "1:25 PM"
            r'(\d{1,2}):(\d{2})\s*(?:Hrs|hrs|AM|PM)?',
            # Pattern: "1325" (24-hour format)
            r'\b(\d{4})\b(?=.*(?:hrs|hours|AM|PM|departure|arrival))',
            # Pattern: "1:25" (12-hour format)
            r'(\d{1,2}):(\d{2})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    if len(match) == 2:
                        hour, minute = int(match[0]), int(match[1])
                        # Handle 12-hour format
                        if 'PM' in text and hour != 12:
                            hour += 12
                        elif 'AM' in text and hour == 12:
                            hour = 0
                        
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            times.append(time(hour, minute))
                    elif len(match) == 1 and len(match[0]) == 4:
                        # 24-hour format "1325"
                        hour, minute = int(match[0][:2]), int(match[0][2:])
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            times.append(time(hour, minute))
                except (ValueError, TypeError):
                    continue
        
        return times

    def extract_total_amount(self, text):
        """Extract total amount from text"""
        patterns = [
            r'(?:Total|Amount|Price|Fare)[:\s]*(?:[A-Z]{3})?\s*([0-9,]+\.?[0-9]*)',
            r'([0-9,]+\.?[0-9]*)\s*(?:USD|EUR|GBP|INR|CAD|AUD)',
            r'₹\s*([0-9,]+\.?[0-9]*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).replace(',', '')
        
        return None

    def extract_currency(self, text):
        """Extract currency from text"""
        currency_match = re.search(r'(?:₹|INR|USD|EUR|GBP|CAD|AUD)', text, re.IGNORECASE)
        if currency_match:
            currency = currency_match.group(0).upper()
            return 'INR' if currency == '₹' else currency
        
        return None


class CreateItineraryFromPDFView(APIView):
    """
    Create itinerary from parsed PDF data - clean structure
    """
    permission_classes = [IsAuthenticated]

    def _check_duplicate_itinerary(self, user, segments_data):
        """
        Check if an identical itinerary already exists for the user.
        Returns the existing itinerary if found, None otherwise.
        """
        # Get all itineraries for this user
        user_itineraries = Itinerary.objects.filter(user=user).prefetch_related('segments')
        
        # Normalize the new segments data for comparison
        new_segments_normalized = []
        for seg in segments_data:
            try:
                from_airport = seg.get('from_airport', '').upper()
                to_airport = seg.get('to_airport', '').upper()
                departure_date_from = datetime.strptime(seg['departure_date_from'], '%Y-%m-%d').date()
                airline = (seg.get('airline', '') or '').upper()
                flight_number = (seg.get('flight_number', '') or '').upper()
                
                new_segments_normalized.append({
                    'from_airport': from_airport,
                    'to_airport': to_airport,
                    'departure_date_from': departure_date_from,
                    'airline': airline,
                    'flight_number': flight_number
                })
            except (ValueError, KeyError) as e:
                logger.error(f"Error normalizing segment for duplicate check: {str(e)}")
                continue
        
        if not new_segments_normalized:
            return None
        
        # Check each existing itinerary
        for existing_itinerary in user_itineraries:
            existing_segments = list(existing_itinerary.segments.all().order_by('segment_order'))
            
            # Must have same number of segments
            if len(existing_segments) != len(new_segments_normalized):
                continue
            
            # Check if all segments match
            is_duplicate = True
            for i, new_seg in enumerate(new_segments_normalized):
                if i >= len(existing_segments):
                    is_duplicate = False
                    break
                
                existing_seg = existing_segments[i]
                
                # Check airports
                if (existing_seg.from_airport.upper() != new_seg['from_airport'] or 
                    existing_seg.to_airport.upper() != new_seg['to_airport']):
                    is_duplicate = False
                    break
                
                # Check departure date (within 1 day tolerance)
                date_diff = abs((existing_seg.departure_date_from - new_seg['departure_date_from']).days)
                if date_diff > 1:
                    is_duplicate = False
                    break
                
                # If airline/flight number is provided, check it matches
                if new_seg['airline'] and existing_seg.airline:
                    if existing_seg.airline.upper() != new_seg['airline']:
                        is_duplicate = False
                        break
                
                if new_seg['flight_number'] and existing_seg.flight_number:
                    if existing_seg.flight_number.upper() != new_seg['flight_number']:
                        is_duplicate = False
                        break
            
            if is_duplicate:
                logger.info(f"🔍 Duplicate itinerary found for user {user.id}: existing itinerary {existing_itinerary.id}")
                return existing_itinerary
        
        return None

    def post(self, request):
        """Create itinerary from parsed PDF data"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            # Validate required fields
            if not data.get('title'):
                return Response({'error': 'Title is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            segments_data = data.get('segments', [])
            if not segments_data:
                return Response({'error': 'At least one flight segment is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Check for duplicate itinerary before creating
            existing_itinerary = self._check_duplicate_itinerary(request.user, segments_data)
            if existing_itinerary:
                logger.warning(f"⚠️ Duplicate itinerary detected for user {request.user.id}. Existing itinerary {existing_itinerary.id}")
                return Response({
                    'error': 'A duplicate itinerary already exists. Please use the existing itinerary or modify the details.',
                    'existing_itinerary_id': existing_itinerary.id
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Create itinerary
            itinerary = Itinerary.objects.create(
                user=request.user,
                title=data['title'],
                travel_type=data.get('travel_type', 'one_way'),
                is_available=data.get('is_available', True)
            )
            
            # Create segments
            created_segments = []
            for i, segment_data in enumerate(segments_data):
                try:
                    # Handle date ranges - use departure_date_from/to and arrival_date_from/to
                    departure_date_from = datetime.strptime(segment_data['departure_date_from'], '%Y-%m-%d').date()
                    departure_date_to = datetime.strptime(segment_data.get('departure_date_to', segment_data['departure_date_from']), '%Y-%m-%d').date()
                    
                    arrival_date_from = datetime.strptime(segment_data.get('arrival_date_from', segment_data['departure_date_from']), '%Y-%m-%d').date()
                    arrival_date_to = datetime.strptime(segment_data.get('arrival_date_to', segment_data.get('arrival_date_from', segment_data['departure_date_from'])), '%Y-%m-%d').date()
                    
                    # Handle time ranges
                    departure_time_from = None
                    departure_time_to = None
                    if segment_data.get('departure_time_from'):
                        departure_time_from = datetime.strptime(segment_data['departure_time_from'], '%H:%M').time()
                    if segment_data.get('departure_time_to'):
                        departure_time_to = datetime.strptime(segment_data['departure_time_to'], '%H:%M').time()
                    
                    segment = TravelSegment.objects.create(
                        itinerary=itinerary,
                        from_airport=segment_data['from_airport'].upper(),
                        to_airport=segment_data['to_airport'].upper(),
                        departure_date_from=departure_date_from,
                        departure_date_to=departure_date_to,
                        departure_time_from=departure_time_from,
                        departure_time_to=departure_time_to,
                        airline=segment_data.get('airline', ''),
                        flight_number=segment_data.get('flight_number', ''),
                        segment_order=i + 1
                    )
                    created_segments.append(segment)
                except (ValueError, KeyError) as e:
                    logger.error(f"Error creating segment {i}: {str(e)}")
                    continue
            
            return Response({
                'message': 'Itinerary created successfully from PDF',
                'itinerary_id': itinerary.id,
                'segments_created': len(created_segments),
                'total_segments': len(segments_data)
            }, status=status.HTTP_201_CREATED)
            
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON data'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creating itinerary from PDF for user {request.user.id}: {str(e)}")
            return Response({'error': 'Failed to create itinerary from PDF'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)