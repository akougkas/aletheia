# Knowledge Graph & DB Schema (AI Context)

**Target Audience**: AI coding assistants modifying SQL queries, database migrations, or `aletheia.db`.

## Relational Schema (`sql/init.sql`)

### 1. `datasets`
Represents a statistical survey or collection.
- `id`: Primary Key
- `code`: Unique, normalized acronym (e.g., `CPS`, `EU-LFS`).
- `name`: Full string name.
- `agency_id`: Foreign key to `agencies`.

### 2. `indicators`
Specific variables within a dataset.
- `dataset_id`: Foreign key to `datasets`.
- `code`: e.g., `LNS14000000`
- `name`: e.g., `Unemployment Rate`

### 3. `methodology_changes`
The core business entity. Represents a point in time where the definition or collection method of a dataset changed.
- `benchmark_case_id`: Optional string linking to a seeded benchmark case.
- `dataset_id`: Foreign Key.
- `change_type`: String enum (`questionnaire_redesign`, `classification_change`, `definition_change`, etc.).
- `effective_date`: Date the change applied to the time series.
- `description`: Text summary of what changed.
- `impact_estimate`: String describing the numeric impact (e.g., "-0.3 percentage points").
- `severity`: `minor`, `moderate`, `major`.
- `comparability`: `comparable`, `comparable_with_adjustments`, `not_comparable`.

### 4. `documents` & `document_chunks`
Stores unstructured methodology notes and academic papers.
- `documents`: Stores `title`, `url`, `publication_date`, and `hash`.
- `document_chunks`: Stores the text `content`, `chunk_index`, and arbitrary JSON `metadata`.

### 5. `methodology_changes_embedding` & `document_chunks_embedding`
Vector search tables created dynamically by the `vectorizer.py` script.
- *AI Note*: These tables use `pgvector`'s `vector` type. Do not query them using standard `LIKE` clauses; they require `<=>` (cosine distance) or `<#>` (inner product).

## Database Connection Lifecycle (`aletheia.db`)
- Uses `psycopg` (v3) in `AsyncConnection` mode.
- Context Manager: `async with get_connection() as conn:` handles checkouts and commits.
- **Note**: The system currently does not use an ORM (like SQLAlchemy) for read queries to maintain maximum performance and exact SQL control, especially for vector math. All `Archivist` queries are raw parameterized SQL.