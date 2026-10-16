CREATE TABLE IF NOT EXISTS public.documents (
    id text NOT NULL,
    content text,
    metadata jsonb,
    embedding vector (1536),
    CONSTRAINT documents_pkey PRIMARY KEY (id)
);

-- Definition taken from the live database on 2026-10-16 (no repo copy existed).
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

-- Definition taken from the live database on 2026-10-16 (no repo copy existed).
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
