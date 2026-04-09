CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE public.embeddings (
    node_label  TEXT                     NOT NULL,
    node_id     TEXT                     NOT NULL,
    attribute   TEXT                     NOT NULL,
    chunk_index INTEGER                  NOT NULL DEFAULT 0,
    model_name  TEXT                     NOT NULL DEFAULT 'text',
    chunk_text  TEXT                     NOT NULL,
    embedding   VECTOR                   NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (node_label, node_id, attribute,
                 chunk_index, model_name)
);

-- vector(384) matches the default 'text' model (BAAI/bge-small-en-v1.5).
-- Models with different dimensions need their own partial index.
-- Update the dimension and model_name if the default model changes.
CREATE INDEX IF NOT EXISTS embeddings_text_hnsw_idx
    ON public.embeddings
 USING hnsw ((embedding::vector(384)) vector_cosine_ops)
 WHERE model_name = 'text';

CREATE INDEX IF NOT EXISTS embeddings_node_idx
    ON public.embeddings (node_label, node_id);

-- ag_catalog is needed so the AGTYPE type resolves.
SET search_path = ag_catalog, "$user", public;

-- Scalar UDF callable from Cypher via SQL-in-Cypher bridge.
-- Returns the minimum cosine distance between a node's
-- embeddings and a query vector, or 1.0 when no embedding
-- exists for the node.
CREATE FUNCTION public.embedding_distance(
    p_node_label AGTYPE,
    p_node_id    AGTYPE,
    p_query_vec  AGTYPE,
    p_model      AGTYPE
) RETURNS AGTYPE
    AS $$
 SELECT COALESCE(
            MIN(e.embedding <=> p_query_vec::text::vector),
            1.0
        )::float8::agtype
   FROM public.embeddings e
  WHERE e.node_label = p_node_label::text
    AND e.node_id = p_node_id::text
    AND e.model_name = p_model::text;
$$
    LANGUAGE sql;
