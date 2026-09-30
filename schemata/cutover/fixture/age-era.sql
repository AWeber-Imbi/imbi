-- The state of a database where the AGE-era apps have run, for
-- root:cutover-check. The DDL copies the production dump of 2026-08-17
-- (meta:backups/imbi.sql):
--
-- * age and vector are both in the schema ag_catalog. The graph
--   initializer runs CREATE EXTENSION with search_path = ag_catalog
--   first, so vector goes into ag_catalog, not into public.
-- * public.embeddings has an ag_catalog.vector column, its primary key,
--   embeddings_node_idx, and the 384-dimension HNSW index.
-- * public.embedding_distance(agtype, ...) exists.
--
-- * pg_cron is in pg_catalog, with its schema cron. pg_cron can be
--   created only in the database that cron.database_name names, so the
--   fixture creates it only there. In other databases, pg_cron is
--   missing, and this is the one difference from production apart from
--   the size of the graph.
DO $$
BEGIN
    IF current_setting('cron.database_name', true) = current_database()
    THEN
        CREATE EXTENSION pg_cron WITH SCHEMA pg_catalog;
    END IF;
END
$$;
CREATE EXTENSION age;
CREATE EXTENSION vector WITH SCHEMA ag_catalog;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT ag_catalog.create_graph('imbi');
SELECT ag_catalog.create_vlabel('imbi', 'Organization');
SELECT ag_catalog.create_vlabel('imbi', 'Project');
SELECT * FROM ag_catalog.cypher('imbi', $$
    CREATE (:Organization {id: 'o1', slug: 'aweber'}),
           (:Project {id: 'p1', slug: 'imbi'}),
           (:Project {id: 'p2', slug: 'imbi-ui'})
$$) AS (v ag_catalog.agtype);
RESET search_path;

-- The scheduler app creates its own tables in the schema scheduler.
CREATE SCHEMA scheduler;
CREATE TABLE scheduler.jobs (id text PRIMARY KEY);

CREATE TABLE public.embeddings (
    node_label text NOT NULL,
    node_id text NOT NULL,
    attribute text NOT NULL,
    chunk_index integer DEFAULT 0 NOT NULL,
    model_name text DEFAULT 'text'::text NOT NULL,
    chunk_text text NOT NULL,
    embedding ag_catalog.vector NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_pkey
        PRIMARY KEY (node_label, node_id, attribute, chunk_index,
                     model_name);
CREATE INDEX embeddings_node_idx
    ON public.embeddings USING btree (node_label, node_id);
CREATE INDEX embeddings_text_hnsw_idx
    ON public.embeddings
    USING hnsw (((embedding)::ag_catalog.vector(384))
                ag_catalog.vector_cosine_ops)
    WHERE (model_name = 'text'::text);

INSERT INTO public.embeddings (node_label, node_id, attribute,
                               chunk_text, embedding)
     SELECT 'Project', 'p' || n, 'description', 'text ' || n,
            array_fill(n::real / 10, ARRAY[384])::ag_catalog.vector
       FROM generate_series(1, 2) AS n;

-- The initializer creates the function with this search_path.
SET search_path = ag_catalog, "$user", public;
CREATE FUNCTION public.embedding_distance(
    p_node_label ag_catalog.agtype, p_node_id ag_catalog.agtype,
    p_query_vec ag_catalog.agtype, p_model ag_catalog.agtype)
    RETURNS ag_catalog.agtype
    LANGUAGE sql
    AS $$ SELECT COALESCE(
            MIN(e.embedding <=> p_query_vec::text::vector),
            1.0
        )::float8::agtype
   FROM public.embeddings e
  WHERE e.node_label = p_node_label::text
    AND e.node_id = p_node_id::text
    AND e.model_name = p_model::text;
$$;
