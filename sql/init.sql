-- Enable pgvector extension (required by pgai vectorizer)
CREATE EXTENSION IF NOT EXISTS vector;

-- Knowledge Graph Schema: Methodology breaks and their relationships
-- Design: Relational tables with foreign keys model the graph structure
-- Embeddings: Managed by pgai vectorizer (not manual columns)

-- Statistical agencies (BLS, Census, Eurostat, etc.)
CREATE TABLE agencies (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) UNIQUE NOT NULL,
    name TEXT NOT NULL,
    country VARCHAR(8),
    url TEXT
);

-- Datasets (CPS, NHIS, EU-LFS, etc.)
CREATE TABLE datasets (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) UNIQUE NOT NULL,
    name TEXT NOT NULL,
    agency_id INTEGER REFERENCES agencies(id),
    description TEXT,
    frequency VARCHAR(32)
);

-- Dataset versions (time-bounded releases)
CREATE TABLE dataset_versions (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(id) NOT NULL,
    version_code VARCHAR(64) NOT NULL,
    effective_start DATE,
    effective_end DATE,
    notes TEXT,
    UNIQUE(dataset_id, version_code)
);

-- Indicators within datasets (unemployment rate, CPI, etc.)
CREATE TABLE indicators (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(id) NOT NULL,
    code VARCHAR(128) NOT NULL,
    name TEXT NOT NULL,
    unit VARCHAR(64),
    description TEXT,
    UNIQUE(dataset_id, code)
);

-- Methodology changes (the core entity)
CREATE TABLE methodology_changes (
    id SERIAL PRIMARY KEY,
    benchmark_case_id VARCHAR(32) UNIQUE,
    dataset_id INTEGER REFERENCES datasets(id) NOT NULL,
    change_type VARCHAR(64) NOT NULL,
    effective_date DATE,
    description TEXT NOT NULL,
    impact_estimate TEXT,
    severity VARCHAR(16),
    comparability VARCHAR(48),
    is_documented BOOLEAN DEFAULT TRUE,
    source_url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Which indicators are affected by which methodology changes (many-to-many)
CREATE TABLE change_indicator_impacts (
    change_id INTEGER REFERENCES methodology_changes(id) NOT NULL,
    indicator_id INTEGER REFERENCES indicators(id) NOT NULL,
    impact_direction VARCHAR(16),
    impact_magnitude TEXT,
    PRIMARY KEY (change_id, indicator_id)
);

-- Source documents (methodology PDFs, release notes, working papers)
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type VARCHAR(64),
    agency_id INTEGER REFERENCES agencies(id),
    url TEXT,
    publication_date DATE,
    content_hash VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Document chunks for semantic search (embeddings managed by pgai vectorizer)
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,
    UNIQUE(document_id, chunk_index)
);

-- Link documents to methodology changes they describe
CREATE TABLE change_documents (
    change_id INTEGER REFERENCES methodology_changes(id) NOT NULL,
    document_id INTEGER REFERENCES documents(id) NOT NULL,
    relevance_score FLOAT,
    PRIMARY KEY (change_id, document_id)
);

-- Retrieval memory for source runs and discovered evidence indexing.
CREATE TABLE retrieval_runs (
    id BIGSERIAL PRIMARY KEY,
    query_hash VARCHAR(64) NOT NULL,
    claim_text TEXT NOT NULL,
    claim_dataset VARCHAR(64),
    claim_indicator TEXT,
    claim_type VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    metadata JSONB,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    error_text TEXT
);

CREATE TABLE retrieval_run_documents (
    retrieval_run_id BIGINT REFERENCES retrieval_runs(id) ON DELETE CASCADE NOT NULL,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    relevance_score FLOAT,
    confidence_score FLOAT,
    is_cached BOOLEAN DEFAULT FALSE,
    rank INTEGER,
    retrieved_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (retrieval_run_id, document_id)
);

-- Indexes for common queries
CREATE INDEX idx_changes_dataset ON methodology_changes(dataset_id);
CREATE INDEX idx_changes_date ON methodology_changes(effective_date);
CREATE INDEX idx_changes_case_id ON methodology_changes(benchmark_case_id);
CREATE INDEX idx_indicators_dataset ON indicators(dataset_id);
CREATE INDEX idx_documents_url ON documents(url) WHERE url IS NOT NULL;
CREATE UNIQUE INDEX uq_documents_content_hash
    ON documents(content_hash)
    WHERE content_hash IS NOT NULL;
CREATE INDEX idx_retrieval_runs_query_hash ON retrieval_runs(query_hash);
CREATE INDEX idx_retrieval_runs_started_at ON retrieval_runs(started_at DESC);
CREATE INDEX idx_retrieval_docs_source ON retrieval_run_documents(source_id);
CREATE INDEX idx_retrieval_docs_document ON retrieval_run_documents(document_id);
CREATE INDEX idx_retrieval_docs_cached ON retrieval_run_documents(is_cached);
