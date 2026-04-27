# BVBMGuide Project Context

> Reference documentation for building an AI-powered All Inclusive Guide (AIG) generation system for Bon Voyage by Marina.

## Project Purpose

This project aims to understand and document the process of creating "All Inclusive Guides" (AIGs) - comprehensive travel documents prepared for clients based on their travel itineraries.

## Current State

The current workflow involves:
1. A **Custom GPT** that generates AIGs
2. A **Library** of reference materials provided to the GPT
3. An **Instruction Set** that guides the GPT's output

## Reference Materials

### Collected So Far:
- [x] **Sample AIG (Output)**: Peru guide for Neha and Mayur (34-page PDF)
  - Location: `/sample/All Inclusive Guide - Peru- Neha and Mayur (1).pdf`
  - Analysis: See `/docs/AIG_STRUCTURE.md`

- [x] **Sample Input**: Divya Mauritius Itinerary (16-page PDF)
  - Location: `/sample/Divya-Mauritius-Itinerary.pdf`
  - Analysis: See `/docs/INPUT_FORMAT.md`

- [x] **Library** - 91 reference AIGs covering multiple destinations
  - Location: `/aig-library/`
  - See `/docs/LIBRARY_INVENTORY.md` for full listing

- [x] **Instruction Set** - Custom GPT system prompt
  - Location: `/docs/CUSTOMGPT_INSTRUCTIONS.md`
  - See `/docs/INSTRUCTION_ANALYSIS.md` for breakdown

### Pending:
- [x] Define program requirements → See `/docs/REQUIREMENTS.md`
- [ ] Build the AIG generator program

## Documentation Index

| Document | Description |
|----------|-------------|
| `REQUIREMENTS.md` | **Program requirements and user flow** |
| `INPUT_FORMAT.md` | Analysis of the input itinerary format |
| `AIG_STRUCTURE.md` | Detailed breakdown of AIG output format and conventions |
| `LIBRARY_INVENTORY.md` | Complete catalog of all 91 reference AIGs by destination |
| `CUSTOMGPT_INSTRUCTIONS.md` | The actual instruction set used by the Custom GPT |
| `INSTRUCTION_ANALYSIS.md` | Analysis of key rules and generation logic |
| `PROJECT_CONTEXT.md` | This file - project overview and status |

## Next Steps

1. Review the library materials when provided
2. Analyze the instruction set for the Custom GPT
3. Understand the full workflow for AIG generation
4. [Future] Build improved tooling for AIG creation

---

*Last Updated: December 22, 2025*

