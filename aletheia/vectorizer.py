"""pgai vectorizer setup for document chunk embeddings.

Declares vectorizers that auto-generate and sync embeddings for the
document_chunks table. Uses OpenAI-compatible endpoint (llama.cpp on mini:8080).

Run once after pgai.install() and table creation:
    uv run python -m aletheia.vectorizer
"""

import os
import psycopg
from aletheia.db import DB_URL, install_pgai

# Embedding config -- override via environment
EMBEDDING_MODEL = os.environ.get("ALETHEIA_EMBED_MODEL", "text-embedding-ada-002")
EMBEDDING_DIMENSIONS = int(os.environ.get("ALETHEIA_EMBED_DIM", "1024"))
EMBEDDING_BASE_URL = os.environ.get("ALETHEIA_EMBED_URL", "http://mini:8080/v1")


def create_vectorizers():
    """Create pgai vectorizers for all tables that need embeddings.

    Idempotent -- uses if_not_exists.
    """
    install_pgai()

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            # Vectorizer for document_chunks: embeds the 'content' column.
            # pgai creates:
            #   - document_chunks_embedding_store (table with embeddings)
            #   - document_chunks_embedding (view joining chunks + embeddings)
            cur.execute(
                """
                SELECT ai.create_vectorizer(
                    'document_chunks'::regclass,
                    if_not_exists => true,
                    loading => ai.loading_column(column_name => 'content'),
                    embedding => ai.embedding_openai(
                        %s,
                        %s,
                        base_url => %s
                    ),
                    chunking => ai.chunking_none(),
                    formatting => ai.formatting_python_template(
                        '$chunk'
                    ),
                    destination => ai.destination_table(
                        target_table => 'document_chunks_embedding_store',
                        view_name => 'document_chunks_embedding'
                    )
                )
                """,
                (EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, EMBEDDING_BASE_URL),
            )

            # Vectorizer for methodology_changes: embeds description + impact.
            # This enables semantic search over methodology break descriptions
            # without needing them in document_chunks.
            cur.execute(
                """
                SELECT ai.create_vectorizer(
                    'methodology_changes'::regclass,
                    if_not_exists => true,
                    loading => ai.loading_column(column_name => 'description'),
                    embedding => ai.embedding_openai(
                        %s,
                        %s,
                        base_url => %s
                    ),
                    chunking => ai.chunking_none(),
                    formatting => ai.formatting_python_template(
                        'methodology change: $chunk'
                    ),
                    destination => ai.destination_table(
                        target_table => 'methodology_changes_embedding_store',
                        view_name => 'methodology_changes_embedding'
                    )
                )
                """,
                (EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, EMBEDDING_BASE_URL),
            )

        conn.commit()

    print(f"Vectorizers created (model={EMBEDDING_MODEL}, dim={EMBEDDING_DIMENSIONS})")
    print(f"Embedding endpoint: {EMBEDDING_BASE_URL}")
    print("Views available: document_chunks_embedding, methodology_changes_embedding")


if __name__ == "__main__":
    create_vectorizers()
