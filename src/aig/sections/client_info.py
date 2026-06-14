from src.aig.context import AIGContext
from src.common.maps import maps_url


def build(context: AIGContext) -> dict:
    f = context.facts
    rows = []
    for hotel in f.hotels:
        dates = ""
        if hotel.check_in and hotel.check_out:
            dates = f"{hotel.check_in} – {hotel.check_out}"
        rows.append({
            "city": hotel.city,
            "dates": dates,
            "hotel": hotel.hotel_name,
            "hotel_maps_link": maps_url(hotel.hotel_name, hotel.city),
            "transport": f.local_transport or "As per itinerary",
        })
    dietary_parts = list(f.dietary_restrictions)
    if f.food_allergies:
        dietary_parts.append(f"Allergies: {', '.join(f.food_allergies)}")
    return {
        "client_names": f.client_names,
        "num_guests": f.num_guests,
        "departure_city": f.departure_city,
        "dietary_preferences": ", ".join(dietary_parts) if dietary_parts else None,
        "trip_summary": rows,
    }
