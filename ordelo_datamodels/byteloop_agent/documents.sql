-- =============================================================================================
-- ordelo_datamodels/byteloop_agent/documents.sql
-- Vector-search documents (pgvector) and the two similarity-search functions over them.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  documents
--                   Text chunk with metadata and a 1536-dimension embedding.
--               fn     match_documents(query_embedding vector, filter jsonb) -> TABLE(id uuid, content text, metadata jsonb, similarity double precision)
--                   Return documents matching a metadata filter, ordered by cosine distance to the query embedding.
--               fn     search_documents(query_embedding vector, match_threshold double precision, match_count integer, metadata_filter jsonb) -> TABLE(id text, content text, metadata jsonb, similarity double precision)
--                   Return up to match_count documents whose similarity to the query embedding is above match_threshold.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   documents holds text chunks with 1536-dimension embeddings. search_documents() (SQL) and match_documents()
--                 (plpgsql) return the closest documents to a query embedding. config/pg_setting.py configures the vector store.
-- LIFECYCLE     none
-- CALLED BY     documents:
--                 sql       match_documents(), search_documents()
--               match_documents:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               search_documents:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      documents: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               match_documents(): executable by PUBLIC (default)
--               search_documents(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       match_documents() declares id uuid in its result but documents.id is text: calling it raises a type error.
--               Captured from live on 2026-10-16; it had no file in the repo.
-- SEE ALSO      byteloop_agent/businesses.sql
--               _orphans/byteloop_agent.sql (elaivec, unused)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table documents
--   Text chunk with metadata and a 1536-dimension embedding.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.documents (
    id text NOT NULL,
    content text,
    metadata jsonb,
    embedding vector (1536),
    CONSTRAINT documents_pkey PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------------------------
-- function match_documents(query_embedding vector, filter jsonb) -> TABLE(id uuid, content text, metadata jsonb, similarity double precision)
--   Return documents matching a metadata filter, ordered by cosine distance to the query embedding.
--   Data: reads documents.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.match_documents (query_embedding vector, FILTER jsonb DEFAULT '{}' ::jsonb)
    RETURNS TABLE (
        id uuid,
        content text,
        metadata jsonb,
        similarity double precision)
    LANGUAGE plpgsql
    AS $function$
    # variable_conflict use_column
BEGIN
    RETURN query
    SELECT
        id,
        content,
        metadata,
        1 - (documents.embedding <=> query_embedding) AS similarity
    FROM
        documents
    WHERE
        metadata @> FILTER
    ORDER BY
        documents.embedding <=> query_embedding;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- function search_documents(query_embedding vector, match_threshold double precision, match_count integer, metadata_filter jsonb) -> TABLE(id text, content text, metadata jsonb, similarity double precision)
--   Return up to match_count documents whose similarity to the query embedding is above match_threshold.
--   Data: reads documents.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.search_documents (query_embedding vector, match_threshold double precision, match_count integer, metadata_filter jsonb DEFAULT '{}' ::jsonb)
    RETURNS TABLE (
        id text,
        content text,
        metadata jsonb,
        similarity double precision)
    LANGUAGE sql
    STABLE
    AS $function$
    SELECT
        id,
        content,
        metadata,
        1 - (embedding <=> query_embedding) AS similarity
    FROM
        documents
    WHERE (embedding <=> query_embedding) < (1 - match_threshold)
    AND metadata @> metadata_filter
ORDER BY
    embedding <=> query_embedding
LIMIT match_count;
$function$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.documents IS 'Text chunk with metadata and a 1536-dimension embedding.';

COMMENT ON FUNCTION public.match_documents (query_embedding vector, FILTER jsonb) IS 'Return documents matching a metadata filter, ordered by cosine distance to the query embedding.';

COMMENT ON FUNCTION public.search_documents (query_embedding vector, match_threshold double precision, match_count integer, metadata_filter jsonb) IS 'Return up to match_count documents whose similarity to the query embedding is above match_threshold.';
