# ALETHEIA

> *Aletheia (ἀλήθεια): Greek for "truth" or "unconcealment" — the act of revealing what is hidden.*

**ALETHEIA** is an autonomous AI platform that validates claims against evidence. Give it any claim — about economics, health, policy, or science — and it will search for supporting or contradicting evidence, flag methodology concerns, and explain its reasoning with full source citations.

## The Vision

Today, misinformation spreads faster than verification. Policy analysts, researchers, and journalists face an impossible task: manually checking every claim against primary sources, methodology notes, and academic literature.

ALETHEIA automates this process with a team of AI agents that:
1. **Parse** any claim into structured components
2. **Search** a knowledge base of trusted sources and academic papers
3. **Retrieve** relevant data from official APIs
4. **Validate** the claim against evidence
5. **Explain** the verdict with full provenance

```
┌─────────────────────────────────────────────────────────────────┐
│                         YOUR CLAIM                               │
│        "EU unemployment fell sharply in 2021, showing           │
│              strong labor market recovery"                       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                     ALETHEIA AGENT TEAM                           │
│                                                                   │
│   ┌────────┐   ┌──────────┐   ┌─────────┐   ┌─────────┐         │
│   │ PARSER │──▶│ ARCHIVIST│──▶│ ANALYST │──▶│ EDITOR  │         │
│   │        │   │          │   │         │   │         │         │
│   │ What's │   │ What     │   │ What do │   │ What's  │         │
│   │ being  │   │ evidence │   │ the     │   │ the     │         │
│   │ claimed│   │ exists?  │   │ numbers │   │ verdict?│         │
│   │   ?    │   │          │   │ show?   │   │         │         │
│   └────────┘   └────┬─────┘   └─────────┘   └─────────┘         │
│                     │                                            │
│              ┌──────▼──────┐                                     │
│              │  KNOWLEDGE  │                                     │
│              │    BASE     │                                     │
│              │             │                                     │
│              │ • Papers    │                                     │
│              │ • Data APIs │                                     │
│              │ • Method    │                                     │
│              │   notes     │                                     │
│              └─────────────┘                                     │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  VERDICT: PARTIALLY_SUPPORTED                                     │
│                                                                   │
│  The decline is real but overstated. Eurostat's 2021 definition  │
│  change reduced the measured rate by ~0.3-0.4 percentage points. │
│                                                                   │
│  Sources: Eurostat LFS Methodology (2021), ECB Working Paper     │
└───────────────────────────────────────────────────────────────────┘
```

## Why Methodology Awareness Matters

ALETHEIA starts with a unique capability: **methodology awareness**. Official statistics frequently change how they measure things — questionnaire redesigns, definitional shifts, classification updates — while the output still looks like a continuous time series.

Example: "E-cigarette use surged from 3.2% to 4.4% in 2019" sounds alarming. But ~half of that increase came from the CDC changing *how they asked the question*, not from more people vaping.

ALETHEIA catches these breaks because it reads methodology documentation AND connects it to specific time periods and data points.

## Current Status

We're in early development. The current version demonstrates:
- Claim parsing (natural language → structured query)
- Knowledge graph search (10 seeded methodology break cases)
- Verdict synthesis (supported / partially supported / misleading)

See [ROADMAP.md](ROADMAP.md) for the development plan.

## Quick Demo

```bash
# Prerequisites: Docker, Python 3.11+, uv, access to mini:8080 (llama.cpp)

docker compose up -d              # Start PostgreSQL
uv sync                           # Install dependencies
uv run python demo.py --quick     # Run the demo
```

The demo walks through three validated cases showing methodology breaks in official statistics.

## Team

| Member | Role | Focus |
|--------|------|-------|
| **Marina** | Public Policy | Domain expertise, test cases, validation |
| **Harry** | Econometrics | Statistical methods, evaluation design |
| **Anthony** | AI/Infrastructure | Architecture, implementation |

See individual contribution docs: [MARINA.md](MARINA.md) | [HARRY.md](HARRY.md)

## Contributing

This is an open research project targeting publication in JEBO (Journal of Economic Behavior and Organization). We welcome:
- High-value data source suggestions
- Domain-specific test cases
- Methodology documentation contributions

See [ROADMAP.md](ROADMAP.md) for current priorities.

## Links

- [ROADMAP.md](ROADMAP.md) — Development phases and milestones
- [MEETINGS.md](MEETINGS.md) — Team decisions and notes
- [INITIAL-PLAN.md](INITIAL-PLAN.md) — Original project conception
