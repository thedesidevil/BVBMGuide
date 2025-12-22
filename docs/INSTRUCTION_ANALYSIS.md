# Custom GPT Instruction Set Analysis

> Breakdown of the key rules, constraints, and generation logic from `CUSTOMGPT_INSTRUCTIONS.md`.

---

## Core Role

The GPT acts as a **travel guide creation assistant** for Bon Voyage by Marina, generating AIGs that:
- Use verified content from the internal library
- Match the stylistic quality of BVBM's best sample guides
- Follow strict formatting and accuracy rules

---

## Key Rules Summary

### 1. 📍 Google Maps Integration (Critical)

**Every venue must have an embedded Google Maps link.**

#### Instruction Specifies:
```
https://www.google.com/maps/search/?api=1&query=PLACE_NAME
```

#### Actual Practice (Peru Sample):
The sample uses **three different link formats**:

| Format | Count | Example | Used For |
|--------|-------|---------|----------|
| **Google Knowledge Graph** | 23 | `https://g.co/kgs/LbZmEMa` | Hotels, well-known venues |
| **Google Maps Short** | 21 | `https://maps.app.goo.gl/2zPQXUBdypTJiAkU8` | Restaurants |
| **Google Maps Full** | 1 | `https://www.google.com/maps/search/?api=1&query=...` | Rare |

> **Note**: The short formats (`g.co/kgs/` and `maps.app.goo.gl/`) are more practical for manual creation and work just as well.

Applies to:
- ✅ Restaurants (even if repeated across days)
- ✅ Attractions
- ✅ Hotels
- ✅ Pharmacies
- ✅ Grocery stores

**Total venue links in Peru sample**: 45 (excluding email links)

---

### 2. 🏨 Hotel Zoning System

#### Rules:
| Rule | Description |
|------|-------------|
| **Hotel Lock-In** | Only reference client's listed hotel(s) |
| **Single Hotel** | Never mention mid-trip hotel transfers if only one hotel |
| **Proximity Filter** | Attractions/restaurants ≤20 min drive from hotel |
| **Essentials** | Pharmacies/groceries ≤10 min walk |
| **Zone Tagging** | Internally tag venues by hotel zone (e.g., "Le Méridien zone") |

---

### 3. 🍽️ Restaurant Rules

#### Source Priority:
1. **Primary**: Use ONLY restaurants from the internal BVBM library
2. **Fallback**: If zone has <3 verified restaurants, curate 1-2 additions

#### Curated Addition Criteria:
- ≤20 mins from hotel
- Strong ambience (Instagrammable or local charm)
- Menu variety + clear Google presence
- Google rating ≥4.3 with recent positive reviews
- **Must be marked** as "curated additions (not in core library)"

#### Rotation Protocol:
- Provide **2 distinct options** for lunch AND dinner each day
- Avoid same restaurant >2x across 3 consecutive days unless:
  - Different dishes or mealtimes
  - Framed as "return for a new experience"

#### Restaurant Entry Format:
```
[Restaurant Name](Google Maps Link)
• Ambience: [label]
• Must-Try: [1-3 dishes]
• Hours: [times]
• Price: ₹[XX] per person
• Travel: [X] min from hotel
• Parking: [availability]
• Best for: [brunch/sunset/romantic/etc.]
```

---

### 4. 📝 Content Style

#### Daily Structure:
- **Bold day headings** with date and title
- Organize into: Morning → Afternoon → Evening → Meals

#### Writing Standards:
| Element | Requirement |
|---------|-------------|
| Tone | Friendly, polished, storytelling (like a local guide) |
| Descriptions | 2-3 vivid, immersive sentences per attraction |
| Sensory Cues | Include light, scent, mood, energy |
| Transitions | Seamless flow between time blocks |
| Avoid | Generic filler, list-only formats |

---

### 5. 🚗 Logistics Defaults

| Assumption | Default |
|------------|---------|
| Transport | Taxi |
| Currency | INR (Indian Rupees) |
| Recommendations | Based on confirmed hotel zones |

---

### 6. 📚 Mandatory Final Sections

Every AIG **must include** these sections:

| Section | Requirements |
|---------|--------------|
| **📸 Instagrammable Cafés** | 3-4 per hotel zone, from library or marked as curated |
| **🍛 Must-Try Local Dishes** | Grouped by type (Street Food, Main, Drinks) + where to try |
| **🏪 Places Near Hotels** | 2 pharmacies + 2 groceries per hotel, ≤10 min walk, with maps/hours/phone |
| **🎁 Souvenir Shopping** | What to buy, where to buy, haggling tips |
| **🎎 Cultural Etiquette** | 4-5 local phrases, tipping customs, greetings |
| **🧳 Packing List** | Season/weather/terrain-specific, special items noted |
| **🚨 Safety & Emergency** | Indian Embassy, police, hospital, safety tips |
| **📶 Mobile/SIM Guide** | Local SIM + eSIM providers, where to buy, documents needed |
| **💉 Health & Vaccinations** | Relevant vaccines, mosquito protection, first-aid |

---

## Comparison: Instructions vs. Sample AIG

| Aspect | Instructions Say | Peru Sample Shows |
|--------|------------------|-------------------|
| **Maps Links** | Required for every venue | ✅ Present as hyperlinks (e.g., "Holiday Inn Lima Airport" links to Google Maps) |
| **Price Format** | INR per person | Mixed: ₹₹ symbols OR PEN (local currency) - destination-appropriate |
| **Parking Info** | Required | Not always present (may be less relevant for certain destinations) |
| **"Best For" Tags** | Required for restaurants | Not consistently present |
| **Zone Tagging** | Internal tagging system | Not visible in final output (internal processing) |
| **Curated Marking** | Mark non-library additions | Not visible in final output (backend notes) |

### Notes:
1. Google Maps links ARE embedded—they appear as hyperlinks on venue names in the PDF
2. Currency is destination-appropriate (PEN for Peru, not INR)
3. Some optional elements (parking, "Best For" tags) may be context-dependent

---

## Generation Workflow (Inferred)

```
1. INPUT: Client itinerary + hotel(s) + dates + preferences
                    ↓
2. ZONE MAPPING: Tag hotel location, define proximity zones
                    ↓
3. LIBRARY SEARCH: Pull verified restaurants/attractions from library
                    ↓
4. GAP FILLING: If <3 restaurants in zone, curate additions
                    ↓
5. DAILY PLANNING: Structure activities by Morning/Afternoon/Evening
                    ↓
6. RESTAURANT ASSIGNMENT: Rotate 2 options per meal, avoid repeats
                    ↓
7. LOGISTICS: Add travel times, hours, prices, maps links
                    ↓
8. SUPPLEMENTARY: Generate all mandatory final sections
                    ↓
9. OUTPUT: Complete AIG document
```

---

## Key Takeaways for Future Development

1. **Library is Central**: The system heavily relies on the internal library as the source of truth
2. **Hotel-Centric**: Everything is organized around hotel proximity zones
3. **Strict Formatting**: Consistent structure with specific required elements per venue
4. **Quality Gates**: Google rating ≥4.3 for curated additions, rotation limits for variety
5. **Immersive Writing**: Not just logistics—storytelling and sensory details required

---

*Last Updated: December 22, 2025*

