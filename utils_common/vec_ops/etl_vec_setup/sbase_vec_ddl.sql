create table
  documents (
    id text primary key,
    content text, -- corresponds to Document.pageContent
    metadata jsonb, -- corresponds to Document.metadata
    embedding vector (1536) -- 1536 works for OpenAI embeddings, change if needed
  );


  -- Create a function to search for documents
  CREATE OR REPLACE FUNCTION search_documents(
  query_embedding VECTOR(1536),
  match_threshold FLOAT,
  match_count INT,
  metadata_filter JSONB DEFAULT '{}'
) RETURNS TABLE (
  id TEXT,  -- Changed from BIGINT to TEXT
  content TEXT,
  metadata JSONB,
  similarity FLOAT
) LANGUAGE SQL STABLE AS $$
SELECT
  id,
  content,
  metadata,
  1 - (embedding <=> query_embedding) AS similarity
FROM
  documents
WHERE
  (embedding <=> query_embedding) < (1 - match_threshold)
  AND metadata @> metadata_filter
ORDER BY
  embedding <=> query_embedding
LIMIT
  match_count;
$$;