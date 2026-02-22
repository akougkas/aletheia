-- =============================================
-- ALETHEIA SurrealDB Schema
-- Apply: surreal import --conn ws://localhost:8000 --user root --pass root --ns aletheia --db main surql/init.surql
-- =============================================

-- =============================================
-- TABLES (Structured Data)
-- =============================================

-- Statistical agencies (BLS, Census, Eurostat, etc.)
DEFINE TABLE agency SCHEMAFULL;
DEFINE FIELD code ON agency TYPE string ASSERT $value != NONE;
DEFINE FIELD name ON agency TYPE string ASSERT $value != NONE;
DEFINE FIELD country ON agency TYPE option<string>;
DEFINE FIELD url ON agency TYPE option<string>;
DEFINE INDEX idx_agency_code ON agency FIELDS code UNIQUE;

-- Datasets (CPS, NHIS, EU-LFS, etc.)
DEFINE TABLE dataset SCHEMAFULL;
DEFINE FIELD code ON dataset TYPE string ASSERT $value != NONE;
DEFINE FIELD name ON dataset TYPE string ASSERT $value != NONE;
DEFINE FIELD description ON dataset TYPE option<string>;
DEFINE FIELD frequency ON dataset TYPE option<string>;
DEFINE INDEX idx_dataset_code ON dataset FIELDS code UNIQUE;

-- Dataset versions (time-bounded releases)
DEFINE TABLE dataset_version SCHEMAFULL;
DEFINE FIELD version_code ON dataset_version TYPE string;
DEFINE FIELD effective_start ON dataset_version TYPE option<datetime>;
DEFINE FIELD effective_end ON dataset_version TYPE option<datetime>;
DEFINE FIELD notes ON dataset_version TYPE option<string>;

-- Indicators within datasets
DEFINE TABLE indicator SCHEMAFULL;
DEFINE FIELD code ON indicator TYPE string ASSERT $value != NONE;
DEFINE FIELD name ON indicator TYPE string ASSERT $value != NONE;
DEFINE FIELD unit ON indicator TYPE option<string>;
DEFINE FIELD description ON indicator TYPE option<string>;

-- Methodology changes (the core knowledge entity)
DEFINE TABLE methodology_change SCHEMAFULL;
DEFINE FIELD benchmark_case_id ON methodology_change TYPE option<string>;
DEFINE FIELD change_type ON methodology_change TYPE string ASSERT $value != NONE;
DEFINE FIELD effective_date ON methodology_change TYPE option<datetime>;
DEFINE FIELD description ON methodology_change TYPE string ASSERT $value != NONE;
DEFINE FIELD impact_estimate ON methodology_change TYPE option<string>;
DEFINE FIELD severity ON methodology_change TYPE option<string>;
DEFINE FIELD comparability ON methodology_change TYPE option<string>;
DEFINE FIELD is_documented ON methodology_change TYPE bool DEFAULT true;
DEFINE FIELD source_url ON methodology_change TYPE option<string>;
DEFINE FIELD created_at ON methodology_change TYPE datetime DEFAULT time::now();
DEFINE FIELD embedding ON methodology_change TYPE option<array<float>>;
DEFINE INDEX idx_change_case ON methodology_change FIELDS benchmark_case_id UNIQUE;
DEFINE INDEX idx_change_date ON methodology_change FIELDS effective_date;
DEFINE INDEX idx_change_type ON methodology_change FIELDS change_type;
-- HNSW vector index for semantic search over methodology change descriptions.
-- DIMENSION must match ALETHEIA_EMBED_DIM (default 4096).
DEFINE INDEX idx_change_embedding ON methodology_change
  FIELDS embedding HNSW DIMENSION 4096 DIST COSINE TYPE F32;

-- Source documents (methodology PDFs, release notes, papers)
DEFINE TABLE document SCHEMAFULL;
DEFINE FIELD title ON document TYPE string ASSERT $value != NONE;
DEFINE FIELD doc_type ON document TYPE option<string>;
DEFINE FIELD url ON document TYPE option<string>;
DEFINE FIELD publication_date ON document TYPE option<datetime>;
DEFINE FIELD content_hash ON document TYPE option<string>;
DEFINE FIELD summary ON document TYPE option<string>;
DEFINE FIELD agency_code ON document TYPE option<string>;
DEFINE FIELD created_at ON document TYPE datetime DEFAULT time::now();
DEFINE INDEX idx_doc_hash ON document FIELDS content_hash UNIQUE;
DEFINE INDEX idx_doc_url ON document FIELDS url;

-- Document chunks for semantic search
DEFINE TABLE chunk SCHEMAFULL;
DEFINE FIELD chunk_index ON chunk TYPE int;
DEFINE FIELD content ON chunk TYPE string ASSERT $value != NONE;
DEFINE FIELD metadata ON chunk TYPE option<object>;
DEFINE FIELD embedding ON chunk TYPE option<array<float>>;
-- HNSW vector index for semantic search over document chunks.
DEFINE INDEX idx_chunk_embedding ON chunk
  FIELDS embedding HNSW DIMENSION 4096 DIST COSINE TYPE F32;
-- Full-text search index for lexical fallback
DEFINE ANALYZER chunk_analyzer TOKENIZERS blank, class FILTERS lowercase, snowball(english);
DEFINE INDEX idx_chunk_fulltext ON chunk FIELDS content
  SEARCH ANALYZER chunk_analyzer BM25;

-- Analysis sessions (replaces retrieval_runs)
DEFINE TABLE session SCHEMAFULL;
DEFINE FIELD query_hash ON session TYPE string;
DEFINE FIELD claim_text ON session TYPE string;
DEFINE FIELD claim_dataset ON session TYPE option<string>;
DEFINE FIELD claim_indicator ON session TYPE option<string>;
DEFINE FIELD claim_type ON session TYPE option<string>;
DEFINE FIELD status ON session TYPE string DEFAULT 'running';
DEFINE FIELD verdict ON session TYPE option<object>;
DEFINE FIELD metadata ON session TYPE option<object>;
DEFINE FIELD started_at ON session TYPE datetime DEFAULT time::now();
DEFINE FIELD completed_at ON session TYPE option<datetime>;
DEFINE FIELD error_text ON session TYPE option<string>;
DEFINE INDEX idx_session_hash ON session FIELDS query_hash;
DEFINE INDEX idx_session_time ON session FIELDS started_at;

-- Batch runs (for MethodBench evaluation)
DEFINE TABLE batch SCHEMAFULL;
DEFINE FIELD name ON batch TYPE string;
DEFINE FIELD status ON batch TYPE string DEFAULT 'pending';
DEFINE FIELD total_claims ON batch TYPE int DEFAULT 0;
DEFINE FIELD completed_claims ON batch TYPE int DEFAULT 0;
DEFINE FIELD started_at ON batch TYPE datetime DEFAULT time::now();
DEFINE FIELD completed_at ON batch TYPE option<datetime>;
DEFINE FIELD results ON batch TYPE option<object>;

-- =============================================
-- GRAPH EDGES (Relationships)
-- =============================================

-- agency --publishes--> dataset
DEFINE TABLE publishes SCHEMAFULL TYPE RELATION IN agency OUT dataset;

-- dataset --has_version--> dataset_version
DEFINE TABLE has_version SCHEMAFULL TYPE RELATION IN dataset OUT dataset_version;

-- dataset --has_indicator--> indicator
DEFINE TABLE has_indicator SCHEMAFULL TYPE RELATION IN dataset OUT indicator;

-- methodology_change --affects--> indicator
DEFINE TABLE affects SCHEMAFULL TYPE RELATION
  IN methodology_change OUT indicator;
DEFINE FIELD impact_direction ON affects TYPE option<string>;
DEFINE FIELD impact_magnitude ON affects TYPE option<string>;

-- methodology_change --belongs_to--> dataset
DEFINE TABLE belongs_to SCHEMAFULL TYPE RELATION
  IN methodology_change OUT dataset;

-- document --describes--> methodology_change
DEFINE TABLE describes SCHEMAFULL TYPE RELATION
  IN document OUT methodology_change;
DEFINE FIELD relevance_score ON describes TYPE option<float>;

-- chunk --part_of--> document
DEFINE TABLE part_of SCHEMAFULL TYPE RELATION IN chunk OUT document;

-- session --found--> document (evidence discovered during analysis)
DEFINE TABLE found SCHEMAFULL TYPE RELATION IN session OUT document;
DEFINE FIELD source_id ON found TYPE option<string>;
DEFINE FIELD relevance_score ON found TYPE option<float>;
DEFINE FIELD confidence_score ON found TYPE option<float>;
DEFINE FIELD is_cached ON found TYPE bool DEFAULT false;
DEFINE FIELD rank ON found TYPE option<int>;

-- session --part_of_batch--> batch
DEFINE TABLE part_of_batch SCHEMAFULL TYPE RELATION IN session OUT batch;
