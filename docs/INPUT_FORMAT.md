# AIG Input Format

> This document describes the input format that the AIG generation system receives - a client itinerary that needs to be expanded into a full All Inclusive Guide.

---

## Sample Input: Divya-Mauritius-Itinerary.pdf

A 16-page presentation-style PDF containing:

### Page Structure

| Page | Content |
|------|---------|
| 1 | Cover page with destination title and branding |
| 2 | Itinerary highlights (day-by-day summary) |
| 3-14 | Day sections (title page + "Day at a Glance" details) |
| 15 | "What's next" - promises the full AIG |
| 16 | Thank you / contact page |

### Day Format (Input)

Each day has:
1. **Title page**: "Day N: [Activity/Theme]"
2. **Details page**: "Day at a Glance" with bullet points

Example (Day 2):
```
Day 2: South Island Tour

Day at a Glance
• Visit Grand Bassin (Ganga Talao) & Shiva Temple
• Stop at the massive Mangal Mahadev (108 ft statue)
• Scenic viewpoint on the South Coast overlooking the Indian Ocean
• Explore 23 Coloured Earth & waterfalls
• Enjoy optional activities (extra cost): Zipline, Quad Biking, Mountain Luge, Nepalese Bridge
• Return to hotel
```

---

## Key Information Extracted from Input

### Trip Details
- **Destination**: Mauritius
- **Duration**: 6 days
- **Client**: Divya
- **Theme**: "Magical Mauritius - A Week of Beaches & Island Escapes"

### Daily Activities
| Day | Theme | Key Activities |
|-----|-------|----------------|
| 1 | Arrival | Airport → Hotel, relax |
| 2 | South Island Tour | Grand Bassin, Shiva Temple, Mangal Mahadev, 23 Coloured Earth, waterfalls |
| 3 | Île aux Cerfs Tour | Belle Mare water activities, speedboat, island beach time |
| 4 | Leisure Day | Resort day, optional activities |
| 5 | North Island Tour | Trou aux Cerfs, Floreal, Port Louis, tea tasting, UNESCO site, shopping |
| 6 | Departure | Breakfast, checkout, airport |

### Missing from Input (AIG Must Add)
- ❌ Hotel name/location
- ❌ Restaurant recommendations
- ❌ Google Maps links
- ❌ Timing details (opening hours, duration)
- ❌ Entry fees
- ❌ Travel times between locations
- ❌ All supplementary sections

---

## Input vs. Output Comparison

| Aspect | Input (Itinerary) | Output (AIG) |
|--------|-------------------|--------------|
| **Pages** | 16 | 30-40 |
| **Style** | Presentation slides | Document format |
| **Detail Level** | High-level bullets | Rich descriptions with logistics |
| **Links** | None | Google Maps for every venue |
| **Restaurants** | Not included | 2 options per meal per day |
| **Supplementary** | Promised only | Full sections included |

---

## "What's Next" Promise (Page 15)

The input explicitly promises the AIG will include:

> - Detailed itinerary with map links, entrance timings and fees and recommended no. of hours to be spent
> - Booking links for activities
> - An eating out guide
> - Getting around guide
> - Details of shops/pharmacies around your stay, recommended things to buy/carry, useful tips
> - A souvenir buying guide

---

## Generation Requirements

To transform this input into an AIG, the system needs to:

### 1. Gather Missing Information (Interactive)

The program must **prompt the user** for information not in the itinerary:

| Required Input | Source | Notes |
|----------------|--------|-------|
| **Hotel Name** | Ask user | Not included in itinerary PDF |
| **Food Preferences** | Ask user | Free-text input, AI interprets |
| **Trip Dates** | Ask user (if not in PDF) | For seasonal recommendations |

#### Food Preferences Handling
The program should:
1. Accept **free-text food preferences** from the user
   - Examples: "vegetarian", "no seafood", "loves spicy food", "allergic to nuts", "prefers local cuisine over touristy places", "fine dining for anniversary dinner"
2. Use **AI to interpret** the preferences and extract:
   - Dietary restrictions (vegetarian, vegan, allergies)
   - Cuisine preferences (local, international, fusion)
   - Dining style (casual, fine dining, street food)
   - Special occasions (romantic dinner, family-friendly)
3. **Filter and rank** restaurant recommendations accordingly

### 2. Identify Context
- [ ] Extract destination (Mauritius)
- [ ] Extract trip dates (if provided, else ask)
- [ ] Get hotel from user input
- [ ] Count days and activities

### 2. Enrich Each Day
- [ ] Add Google Maps links for each attraction
- [ ] Add opening hours and entry fees
- [ ] Add travel times from hotel
- [ ] Add 2 lunch + 2 dinner restaurant options
- [ ] Add vivid descriptions (2-3 sentences per attraction)

### 3. Generate Supplementary Sections
- [ ] Must-Try Local Dishes
- [ ] Important Places Around Hotel
- [ ] Souvenir Shopping Guide
- [ ] Cultural Etiquette & Local Phrases
- [ ] Packing List (season-appropriate)
- [ ] Personal Safety & Emergency Contacts
- [ ] Mobile Connectivity & SIM Guide
- [ ] Health & Vaccination Guidance

### 4. Apply Formatting
- [ ] Add header to each page
- [ ] Embed all Google Maps links
- [ ] Use consistent emoji system
- [ ] Follow day structure (Morning/Afternoon/Evening/Meals)

---

## Data Sources Needed

| Data Type | Source |
|-----------|--------|
| Attraction details | Google Maps, destination knowledge |
| Restaurant recommendations | BVBM library (Mauritius guides) |
| Opening hours/fees | Google Maps, official websites |
| Local dishes | Destination research, library |
| Emergency contacts | Embassy websites, local info |
| Packing/health | Seasonal data, travel advisories |

---

*Last Updated: December 22, 2025*
*Based on: Divya-Mauritius-Itinerary.pdf*

