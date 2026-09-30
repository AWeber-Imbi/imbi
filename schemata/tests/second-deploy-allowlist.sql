-- The statements that a second deploy prints (README Known problems,
-- item 2). root:schema-check compares the second deploy with this file,
-- without comment lines and blank lines, line by line. Remove these
-- statements when a pglifecycle build fixes the problem.
DROP INDEX IF EXISTS public.embeddings_text_hnsw_idx;
CREATE INDEX embeddings_text_hnsw_idx ON public.embeddings USING hnsw ( ((embedding)::vector(384)) vector_cosine_ops ) WHERE (model_name = 'text'::text);
COMMENT ON INDEX public.embeddings_text_hnsw_idx IS $$BAAI/bge-small-en-v1.5, 384 dimensions.$$;
