from openai import OpenAI
from pydantic import BaseModel
from typing import List, Optional


class ItineraryValidation(BaseModel):
    is_itinerary: bool
    confidence: float
    reason: str


class Segment(BaseModel):
    from_airport: str
    to_airport: str
    departure_date_from: str
    departure_date_to: str
    departure_time_from: str
    departure_time_to: str
    airline: str
    flight_number: str
    layovers: List[str]

class TicketInfo(BaseModel):
    title: str
    travel_type: str
    is_available: bool
    segments: List[Segment]


def validate_itinerary_content(client: OpenAI, text: str) -> ItineraryValidation:
    """
    Validate if the extracted text contains itinerary/flight ticket information.
    Returns validation result with confidence score.
    """
    response = client.responses.parse(
        model="gpt-4o",
        input=[
            {
                "role": "system",
                "content": """
                    You are a travel document validator.
                    Determine if the provided text contains flight itinerary or ticket information.
                    
                    A valid itinerary should contain:
                    - Flight details (airline, flight number, or route information)
                    - Airport codes or city names for travel
                    - Dates related to travel
                    - Passenger or booking information
                    
                    Return:
                    - is_itinerary: true if it's a flight itinerary/ticket, false otherwise
                    - confidence: 0.0 to 1.0 (how confident you are)
                    - reason: brief explanation of your decision
                """
            },
            {
                "role": "user",
                "content": f"Does this text contain flight itinerary information?\n\n{text}"
            }
        ],
        text_format=ItineraryValidation,
    )
    
    return response.output_parsed


def convert_list_pairs_to_dict(data):
    """
    Converts OpenAI's fallback list-of-lists response into a proper dictionary.
    Handles nested structures like segments.
    """
    result = {}

    for key, value in data:
        # If segments → convert each segment
        if key == "segments":
            result[key] = [convert_list_pairs_to_dict(segment) for segment in value]
        else:
            result[key] = value

    return result

def get_ai_itenerary_response(client: OpenAI, ticket_text: str):
    """
    Parse itinerary information from text.
    First validates if the text contains itinerary information before parsing.
    
    Raises:
        ValueError: If the text does not contain itinerary information
    """
    # Step 1: Validate if the content is an itinerary
    validation = validate_itinerary_content(client, ticket_text)
    
    # Convert list-based response to dict if needed
    if isinstance(validation, list):
        validation_dict = convert_list_pairs_to_dict(validation)
        is_itinerary = validation_dict.get('is_itinerary', False)
        confidence = validation_dict.get('confidence', 0.0)
        reason = validation_dict.get('reason', 'Unknown')
    else:
        is_itinerary = validation.is_itinerary if hasattr(validation, 'is_itinerary') else validation.get('is_itinerary', False)
        confidence = validation.confidence if hasattr(validation, 'confidence') else validation.get('confidence', 0.0)
        reason = validation.reason if hasattr(validation, 'reason') else validation.get('reason', 'Unknown')
    
    # Reject if not an itinerary or confidence is too low
    if not is_itinerary or confidence < 0.6:
        raise ValueError(f"This content does not appear to contain flight itinerary information. Reason: {reason}")
    
    # Step 2: Parse the itinerary
    response = client.responses.parse(
        model="gpt-4o",
        input=[
        {
            "role": "system",
            "content": """
                You are a flight ticket parser. 
                Extract ONLY the flight segments from the provided ticket text.

                Rules:
                - Convert airport names into IATA 3-letter codes.
                - Return only segments in order.
                - travel_type: "one_way", "round_trip", or "multi_city"
                - is_available: always true
                - **CRITICAL: ALL dates MUST be in YYYY-MM-DD format regardless of input format.**
                  Examples: "26Feb2026" → "2026-02-26", "04Dec25" → "2025-12-04", "12/25/2024" → "2024-12-25"
                - departure_date_from & departure_date_to: same date (ticket date) in YYYY-MM-DD format
                - Extract airline and flight_number when available.
                - layovers: if a flight stops at an airport between two long-haul segments, add a layover entry.
                - Time should be 24-hr format (HH:MM) if possible; otherwise leave null.
                - If time is unclear → leave null.
            """
        },
            {
                "role": "user",
                "content": ticket_text
            },
        ],
        text_format=TicketInfo,
    )


    parsed = response.output_parsed
    return convert_list_pairs_to_dict(parsed)