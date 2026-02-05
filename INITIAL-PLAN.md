# ALETHEIA — Project Plan

> *Aletheia (ἀλήθεια): Greek for "truth" or "unconcealment" — the act of revealing what is hidden.*

| | |
|--|--|
| **Team** | Marina (Public Policy), Harry (Econometrics/Mathematics), Anthony (AI/Infrastructure) |
| **Status** | Initial planning — architecture & scope definition |
| **Created** | 2025-02-05 |

---

## Table of Contents

1. [The Problem We're Solving](#1-the-problem-were-solving)
2. [Why This Matters](#2-why-this-matters-the-gap)
3. [Our Approach: A Team of AI Specialists](#3-our-approach-a-team-of-ai-specialists)
4. [How the System Works (Technical Overview)](#4-how-the-system-works-technical-overview)
5. [Evaluation: MethodBench](#5-evaluation-methodbench)
6. [Beyond Government Statistics](#6-beyond-government-statistics)
7. [Publication Strategy](#7-publication-strategy)
8. [Project Timeline](#8-project-timeline)
9. [Design Principles](#9-design-principles)
10. [Open Decisions for the Team](#10-open-decisions-for-the-team)

---

## 1. The Problem We're Solving

Policy analysts often rely on data pipelines to produce indicators and trends under time pressure. But here's the catch: **official datasets frequently change how they measure things** — questionnaires get redesigned, definitions shift, weighting methods evolve, classification rules change — while the output still looks like a clean, continuous time series.

This creates a dangerous situation: **an analysis can be technically correct but substantively misleading**, because the underlying data is no longer comparable across time periods.

### Our Core Questions

1. **Main research question:** Can an AI system reliably detect methodology changes (documented or not) and prevent unsafe policy conclusions? Can it do this across *any* domain that produces longitudinal data?

2. **Behavioral research angle (Harry's focus):** Can an AI system, acting as a "nudge," help policy analysts make better interpretations when analyzing data with known methodology breaks?

---

## 2. Why This Matters (The Gap)

After extensive research (Feb 2025), we found that **no existing system bridges these two disconnected worlds**:

### The Two Camps Today

| Camp | What It Does | What It Misses |
|------|--------------|----------------|
| **Statistical Anomaly Detection** (TimeSeriesScientist, HyperTS, Prophet) | Detects unusual patterns in data | Has no idea *why* the data changed — would flag a CPS unemployment dip but can't know it was a classification error |
| **Policy/Compliance AI** (GraphCompliance, DocPolicyKG) | Reasons about regulatory and policy text | Never touches actual numerical data — can answer "what does this regulation require?" but can't connect it to real indicators |

### What ALETHEIA Does Differently

**ALETHEIA bridges both worlds** — it reads methodology documentation AND analyzes the actual data simultaneously, then reasons about whether the data is trustworthy given what the documentation says.

### Related Work We're Building On

- **GraphCompliance:** Uses knowledge graphs + AI for regulatory reasoning — we adapt this architecture
- **RAGulating Compliance:** Multi-agent approach for regulatory Q&A — pipeline patterns we'll use
- **TimeSeriesScientist:** AI-driven time series analysis — complements our statistical work
- **DocPolicyKG:** AI-built policy knowledge graphs — informs our knowledge base construction

---

## 3. Our Approach: A Team of AI Specialists

Think of ALETHEIA as an AI "organization" where specialized team members collaborate. The human policymaker is the CEO — they set objectives, review outputs, and make final decisions. Each AI component is like a specialized department.

### 3.1 The Team Structure

```
┌─────────────────────────────────────────────────────────┐
│                    HUMAN (The Decision-Maker)           │
│          Sets goals, reviews findings, decides          │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              CHIEF ANALYST (The Coordinator)            │
│     Breaks down tasks, assigns work, synthesizes        │
└──┬──────────┬──────────┬──────────┬──────────┬──────────┘
   │          │          │          │          │
┌──▼────┐ ┌──▼────┐ ┌──▼────┐ ┌──▼────┐ ┌──▼──────────┐
│PARSER │ │ARCHI- │ │ANALYST│ │EDITOR │ │  WATCHDOG   │
│       │ │VIST   │ │       │ │       │ │             │
│Reads  │ │Tracks │ │Runs   │ │Writes │ │ Monitors    │
│claims │ │method │ │stats  │ │final  │ │ for new     │
│       │ │changes│ │tests  │ │report │ │ changes     │
└───────┘ └───────┘ └───────┘ └───────┘ └─────────────┘
```

### 3.2 What Each Team Member Does

#### Chief Analyst (The Coordinator)
- Receives policy claims or analysis requests from the human
- Breaks work into subtasks and assigns to the right specialist
- Combines all findings into a final structured output
- Adjusts the workflow based on how complex the claim is

#### Claim Parser (The Auditor)
- **Input:** A policy claim in plain English (e.g., "unemployment dropped sharply in 2021")
- **Output:** A structured breakdown: what indicator, what direction, what time period, what dataset, what region
- Figures out implicit references — when someone says "vaping increased," it knows to look at NHIS e-cigarette data
- Handles ambiguous or multi-dataset claims

#### Data Provenance Agent (The Archivist) — *This is our key innovation*
- Maintains a knowledge base of dataset metadata and methodology changes
- Tracks relationships between: datasets, versions, indicators, methodology changes, agencies, and source documents
- Ingests: methodology PDFs, release notes, working papers, metadata from official APIs
- **What makes this special:** It connects methodology documentation to specific data points and time periods — something no existing system does

#### Data Retrieval & Analysis Agent (The Analyst) — *Harry's domain*
- Pulls actual data from official sources (BLS, Eurostat, FRED, Census, ECB)
- Runs statistical tests to detect structural breaks:
  - Changepoint detection
  - Structural break tests (Chow test, Bai-Perron, CUSUM)
- Answers the key question: **How much of an observed change is due to methodology vs. a real phenomenon?**

#### Verdict & Synthesis Agent (The Editor)
- Combines inputs from all other team members
- Produces a verdict: Is the claim **supported**, **partially supported**, or **misleading**?
- Includes caveats, confidence levels, and full source attribution
- Can show multiple scenarios (e.g., "with original methodology" vs. "with revised methodology")

#### Continuous Monitoring Agent (The Watchdog)
- Crawls statistical agency websites, RSS feeds, and release calendars
- Detects new methodology notes, questionnaire redesigns, weighting updates
- Automatically updates the knowledge base
- Keeps the system current without needing human curation

### 3.3 How Team Members Communicate

All communication between components is:
- **Structured:** Using consistent message formats
- **Logged:** Every interaction is recorded for reproducibility and auditing
- **Traceable:** Any finding can be traced back to its sources

---

## 4. How the System Works (Technical Overview)

### 4.1 Two Ways to Store Knowledge

We use a dual approach because neither alone is sufficient:

```
┌─────────────────────────────────────────────┐
│         Methodology Knowledge Base           │
│                                              │
│  ┌───────────────┐    ┌──────────────────┐  │
│  │  Structured   │    │    Searchable    │  │
│  │   Database    │    │    Text Store    │  │
│  │               │    │                  │  │
│  │ • Datasets    │    │ • Methodology    │  │
│  │ • Versions    │    │   documents      │  │
│  │ • Changes     │    │ • Release notes  │  │
│  │ • Indicators  │    │ • Working papers │  │
│  │               │    │                  │  │
│  │ For precise   │    │ For finding      │  │
│  │ lookups       │    │ related content  │  │
│  └───────┬───────┘    └────────┬─────────┘  │
│          │                     │            │
│          └──────────┬──────────┘            │
│                     │                       │
│    Combined Search: Structure first,        │
│    then semantic refinement                 │
└─────────────────────────────────────────────┘
```

#### Why We Need Both

Standard text search works by finding similar-sounding phrases. But "2019 questionnaire redesign" and "adult e-cigarette use increased" don't sound similar at all — yet they're critically related.

The structured database knows that: *NHIS 2019 redesign → affects → e-cigarette indicator → during → 2019*

**Our approach:** Use structure to narrow down relevant items, then use text search to refine within that set.

### 4.2 Technology Choices (For Anthony)

| Component | Choice | Why |
|-----------|--------|-----|
| **Language** | Python (uv package manager) | Standard for data science |
| **AI Framework** | Custom-built (no LangChain/LangGraph) | Full control, easier to publish and modify |
| **AI Models** | Mix of cloud (Claude/GPT-4) and local (Llama/Mistral via Ollama) | Powerful reasoning + runs on laptops |
| **Structured Database** | SQLite or NetworkX + DuckDB | No external servers needed, portable |
| **Text Search** | ChromaDB or LanceDB | Local-first, no external dependencies |
| **Data APIs** | BLS, Census, FRED, Eurostat, ECB | Official statistical sources |

### 4.3 Development Approach

**Phase 1:** Build the structure, prove it works with basic retrieval  
**Phase 2:** Train specialized models on methodology documents to improve accuracy  
**Phase 3:** Add continuous monitoring to keep everything up to date

---

## 5. Evaluation: MethodBench

Marina's 10 cases are the foundation for our evaluation benchmark, which we'll extend into a publishable dataset.

### 5.1 Core Test Cases

| # | Dataset | Indicator | What Changed | Region |
|---|---------|-----------|--------------|--------|
| 1 | NHIS | Adult e-cigarette use | Questionnaire redesign + new weights | USA |
| 2 | NHIS | Unable to afford medical care | Same 2019 redesign | USA |
| 3 | CPS | Unemployment rate | COVID misclassification | USA |
| 4 | ACS | Real median household income | COVID nonresponse bias | USA |
| 5 | CPI | Inflation | Collection mode suspension | USA |
| 6 | EU-LFS | Unemployment rate | Definitional change 2021 | EU |
| 7 | HICP | Inflation | Lockdown price imputation | EU |
| 8 | Eurostat Mortality | Excess deaths | Revision/late registration | EU |
| 9 | ESA 2010 | GDP level | Accounting reclassification | EU |
| 10 | EU-SILC Ireland | At-risk-of-poverty rate | Explicit series break | Ireland |

### 5.2 How We'll Test

#### Testing Claim Variations
The same case rephrased in different ways:
- **Direct:** "NHIS e-cigarette use increased from 3.2% to 4.4% in 2019"
- **Implicit:** "Vaping surged in 2019 according to government data"
- **Misleading:** "CDC data proves the vaping epidemic accelerated in 2019"

#### Comparing Against Baselines
1. Plain AI with no context — what does GPT-4/Claude know already?
2. AI with document search but no structured relationships
3. AI with our knowledge base but no specialized team members
4. Full ALETHEIA system
5. Human experts (Marina + Harry as gold standard)

### 5.3 Scoring Criteria

| Metric | What We Measure |
|--------|-----------------|
| **Detection** | Did the system identify a methodology break? (Yes/No) |
| **Characterization** | Did it correctly identify the type of break? |
| **Magnitude** | Did it estimate the impact size correctly? |
| **Verdict Quality** | How useful and accurate is the recommendation? (1-5) |
| **False Positive Rate** | When there's no break, does it correctly say so? |

---

## 6. Beyond Government Statistics

The system is designed for a broader principle:

> **Any data source where how you measure can change independently of what you're measuring.**

| Domain | What's Measured | What Could Change | Misleading Conclusion |
|--------|-----------------|-------------------|----------------------|
| Government stats | Unemployment, inflation | Survey redesigns | "Policy worked" |
| Corporate finance | Revenue, earnings | Accounting methods | "Company grew" |
| Clinical research | Drug efficacy | Trial protocols | "Drug improved" |
| ESG reporting | Sustainability metrics | Reporting frameworks | "Company got greener" |
| Education | Test scores | Testing standards | "Students got smarter" |
| Credit ratings | Risk distributions | Rating models | "Credit quality shifted" |

The core technology is the same across all domains — only the data sources and terminology change.

---

## 7. Publication Strategy

We're planning a **three-paper arc**:

### Paper 1: Systems/AI Venue (Primary)
- **Title direction:** "ALETHEIA: Multi-Agent Methodology-Aware Intelligence for Trustworthy Data Analysis"
- **Contribution:** Architecture, knowledge base design, evaluation framework
- **Targets:** AAAI, AAMAS, KDD, SIGMOD demo track, VLDB

### Paper 2: Policy/Applied Venue
- **Title direction:** "Can AI Detect What Analysts Miss? Evaluating Methodology-Aware AI on Official Statistics"
- **Contribution:** The 10-case evaluation, policy implications, human-AI comparison
- **Targets:** Government information journals, policy analysis venues, JASA
- **Lead:** Marina + Harry, with system support from Anthony

### Paper 3: Benchmark/Data Venue
- **Title direction:** "MethodBench: A Benchmark for Evaluating Methodology-Aware AI Systems"
- **Contribution:** Published benchmark, extended cases, scoring rubric, baseline results
- **Targets:** NeurIPS Datasets & Benchmarks, or a data science venue

---

## 8. Project Timeline

### Phase 0: Foundation (Weeks 1-2)
- [ ] Set up project structure and development environment
- [ ] Define how team members communicate (message formats)
- [ ] Build the knowledge base structure
- [ ] Load Marina's 10 cases and reference documents
- [ ] Set up local AI infrastructure

### Phase 1: Core Pipeline (Weeks 3-6)
- [ ] Build the Claim Parser
- [ ] Build the Archivist with document search
- [ ] Build the basic Analyst (data retrieval from APIs)
- [ ] Build the Editor (verdict generation)
- [ ] Build the Coordinator to connect everything
- [ ] Test on 10 cases — establish baseline performance

### Phase 2: Intelligence Layer (Weeks 7-10)
- [ ] Add Harry's statistical break detection tools to the Analyst
- [ ] Train specialized models on methodology documents
- [ ] Test with rephrased claims (adversarial testing)
- [ ] Build automated testing system
- [ ] Compare all baselines

### Phase 3: Generalization & Polish (Weeks 11-14)
- [ ] Add cross-domain cases (corporate, clinical, ESG)
- [ ] Build the Watchdog for continuous monitoring
- [ ] Build demo interface
- [ ] Write Paper 1 draft
- [ ] Package MethodBench for public release

---

## 9. Design Principles

1. **Runs locally:** Everything works on a researcher's laptop. No mandatory cloud services.

2. **Full control:** We build our own components rather than depending on complex frameworks. Easier to understand, modify, and publish.

3. **Domain-neutral core:** The AI architecture doesn't know about BLS or Eurostat specifically. Domain knowledge lives in the knowledge base and templates.

4. **Reproducible:** Every interaction is logged. Every verdict has a source trail. Any result can be re-derived.

5. **Build in layers:** Start simple, add complexity. Each layer is valuable on its own.

---

## 10. Open Decisions for the Team

We need to decide together on:

| Decision | Options | Who Needs to Weigh In |
|----------|---------|----------------------|
| Text search database | ChromaDB vs LanceDB vs custom | Anthony |
| Structured database | SQLite+custom vs NetworkX+DuckDB | Anthony |
| Text embedding model | Standard vs specialized vs fine-tuned | Anthony + Harry |
| Local AI model | Llama 3 8B vs Mistral 7B vs Qwen | Anthony |
| Paper 1 venue and deadline | Multiple options | Everyone |
| Watchdog scope for v1 | Full vs limited vs deferred | Everyone |
| Statistical tests for Analyst | Which specific methods? | Harry |
| Case priority | All 10 for v1, or start with subset? | Marina |

---

*This document is our shared project plan. Update it as we make decisions together.*
