# AIG Generator - Requirements

> Functional requirements for the All Inclusive Guide generation program.

---

## Overview

Build a program that transforms a **client itinerary PDF** into a complete **All Inclusive Guide (AIG)**, using AI to enrich content and personalize recommendations.

---

## Input Requirements

### 1. Primary Input: Client Itinerary PDF
- Presentation-style PDF (like `Divya-Mauritius-Itinerary.pdf`)
- Contains: destination, trip duration, daily activities
- May be missing: hotel, dates, client preferences

### 2. Required User Prompts

The program must ask the user for:

| Prompt | Required | Example Input |
|--------|----------|---------------|
| **Hotel Name** | Yes | "Le Méridien Île Maurice" |
| **Food Preferences** | Yes | Free-text (see below) |
| **Trip Dates** | If not in PDF | "Dec 28 - Jan 2" |
| **Client Name(s)** | If not in PDF | "Divya and Rahul" |

### 3. Food Preferences (Free-Text Input)

Users should be able to express preferences naturally:

```
Examples:
- "Vegetarian, no eggs"
- "We love seafood and local cuisine"
- "One person is allergic to nuts"
- "Looking for romantic dinner spots for our anniversary"
- "Prefer casual dining, not too expensive"
- "Adventurous eaters, want to try street food"
- "Kids friendly places needed"
```

---

## AI Processing Requirements

### 1. Food Preference Interpretation

Use AI to parse free-text preferences into structured data:

```json
{
  "dietary_restrictions": ["vegetarian", "no eggs"],
  "allergies": ["nuts"],
  "cuisine_preferences": ["local", "seafood"],
  "dining_style": ["casual", "mid-range"],
  "special_requirements": ["romantic", "anniversary"],
  "party_composition": ["couple", "with kids"]
}
```

### 2. Restaurant Matching

For each meal slot, AI should:
1. Pull restaurants from the **BVBM library** for the destination
2. Filter by dietary restrictions and allergies
3. Rank by preference match (cuisine, style, occasion)
4. Apply **proximity filter** (≤20 min from hotel)
5. Apply **rotation rules** (avoid repeating >2x in 3 days)
6. Return **2 options per meal** (lunch + dinner)

### 3. Content Enrichment

For each attraction in the itinerary:
- Generate 2-3 vivid, immersive sentences
- Add practical details (hours, fees, duration)
- Generate Google Maps links
- Calculate travel time from hotel

---

## Output Requirements

### 1. AIG Document Structure

Follow the format defined in `AIG_STRUCTURE.md`:

- Header on every page (BVBM branding)
- Day-by-day sections with Morning/Afternoon/Evening/Meals
- All 9 mandatory supplementary sections
- Google Maps links on all venue names

### 2. Personalization

The output should reflect:
- Client name(s) in title
- Food preferences in restaurant selections
- Hotel-specific proximity calculations
- Seasonal packing recommendations (based on dates)

### 3. Output Format

- Primary: Google Docs (editable)
- Secondary: PDF export

---

## Technical Requirements

### Data Sources

| Data Type | Source |
|-----------|--------|
| Restaurant database | `/aig-library/` (91 guides, extract restaurants) |
| Attraction details | AI + Google Maps API |
| Opening hours/fees | Google Places API or AI knowledge |
| Emergency contacts | Destination-specific database |
| Health/visa info | Travel advisory APIs or AI knowledge |

### AI Capabilities Needed

1. **PDF Parsing**: Extract structured data from itinerary PDFs
2. **NLP**: Interpret free-text food preferences
3. **Content Generation**: Write vivid descriptions, transitions
4. **Reasoning**: Match restaurants to preferences, apply rules

### APIs (Potential)

| API | Purpose |
|-----|---------|
| Google Maps / Places | Links, hours, ratings, proximity |
| OpenAI / Claude | Content generation, preference parsing |
| PDF parsing library | PyMuPDF, pdfplumber |

---

## User Flow

```
1. Upload itinerary PDF
         ↓
2. Program extracts: destination, days, activities
         ↓
3. Program prompts for:
   - Hotel name
   - Food preferences (free text)
   - Trip dates (if missing)
   - Client name(s) (if missing)
         ↓
4. AI processes:
   - Parses food preferences
   - Matches restaurants from library
   - Generates attraction descriptions
   - Calculates logistics (times, distances)
         ↓
5. Program generates:
   - Day-by-day sections with meals
   - All supplementary sections
         ↓
6. Output: Complete AIG document
```

---

## Quality Rules (from Instructions)

### Restaurant Selection
- ✅ Primary: Use BVBM library restaurants only
- ✅ Fallback: Curate additions if <3 in zone (rating ≥4.3)
- ✅ Rotation: 2 options per meal, no repeat >2x in 3 days
- ✅ Proximity: ≤20 min from hotel

### Content Quality
- ✅ 2-3 vivid sentences per attraction
- ✅ Sensory details (light, scent, mood)
- ✅ Seamless transitions between time blocks
- ✅ Avoid generic filler

### Link Requirements
- ✅ Google Maps link on every venue name
- ✅ Acceptable formats: `g.co/kgs/`, `maps.app.goo.gl/`, or full URL

---

## Future Enhancements

- [ ] Integration with booking systems
- [ ] Real-time availability checking
- [ ] Multi-language support
- [ ] Client feedback loop to improve recommendations

---

*Last Updated: December 22, 2025*

