# BVBMGuide

AI-powered All Inclusive Guide (AIG) generation system for **Bon Voyage by Marina**.

## Overview

This project documents and aims to improve the process of creating "All Inclusive Guides" (AIGs) - comprehensive travel documents prepared for clients based on their travel itineraries.

## Repository Structure

```
BVBMGuide/
├── aig-library/          # 91 reference AIGs covering 20+ destinations
├── sample/
│   ├── Divya-Mauritius-Itinerary.pdf           # Sample INPUT (client itinerary)
│   └── All Inclusive Guide - Peru-....pdf      # Sample OUTPUT (full AIG)
├── docs/
│   ├── INPUT_FORMAT.md           # Input itinerary format analysis
│   ├── AIG_STRUCTURE.md          # Output AIG format & conventions
│   ├── CUSTOMGPT_INSTRUCTIONS.md # GPT system prompt
│   ├── INSTRUCTION_ANALYSIS.md   # Key rules breakdown
│   ├── LIBRARY_INVENTORY.md      # Catalog of reference AIGs
│   └── PROJECT_CONTEXT.md        # Project status
└── README.md
```

## What is an AIG?

An All Inclusive Guide is a 30-40 page travel document that includes:
- Day-by-day itinerary with activities and logistics
- Restaurant recommendations with must-try dishes
- Practical information (packing lists, safety tips, local phrases)
- Cultural etiquette and health guidance

## Current Workflow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Client         │     │   Custom GPT     │     │  All Inclusive  │
│  Itinerary      │ ──▶ │  + Library       │ ──▶ │  Guide (AIG)    │
│  (16 pages)     │     │  + Instructions  │     │  (30-40 pages)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

- **Input**: High-level client itinerary with day-by-day activities
- **Processing**: Custom GPT enriches with restaurants, logistics, maps links
- **Output**: Comprehensive AIG with all supplementary sections

## Documentation

| Document | Description |
|----------|-------------|
| `docs/AIG_STRUCTURE.md` | Format & conventions from Peru sample |
| `docs/LIBRARY_INVENTORY.md` | Catalog of 91 reference AIGs by region |
| `docs/CUSTOMGPT_INSTRUCTIONS.md` | The actual GPT system prompt |
| `docs/INSTRUCTION_ANALYSIS.md` | Key rules breakdown & generation logic |
| `docs/PROJECT_CONTEXT.md` | Project status & next steps |

---

*Bon Voyage by Marina - Pune, India*
