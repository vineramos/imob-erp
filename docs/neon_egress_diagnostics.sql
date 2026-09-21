-- Diagnóstico seguro e somente leitura para executar no SQL Editor do Neon.
-- O PostgreSQL não expõe bytes enviados por endpoint HTTP; estes indicadores
-- mostram os maiores candidatos por volume armazenado, chamadas e linhas.

-- 1. Confirma se arquivos estão sendo guardados no PostgreSQL e quanto ocupam.
SELECT
  count(*) AS stored_objects,
  pg_size_pretty(coalesce(sum(size_bytes), 0)::bigint) AS logical_file_size,
  pg_size_pretty(pg_total_relation_size('document_storage_objects')) AS table_size
FROM document_storage_objects;

-- 2. Maiores arquivos que geram egress integral a cada download.
SELECT object_name, content_type, size_bytes, updated_at
FROM document_storage_objects
ORDER BY size_bytes DESC
LIMIT 30;

-- 3. Maiores tabelas, incluindo índices e TOAST.
SELECT
  relname AS table_name,
  pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
  n_live_tup AS estimated_rows
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 30;

-- 4. Consultas mais frequentes e com mais linhas devolvidas.
-- Requer pg_stat_statements habilitado pelo Neon. Os textos são normalizados.
SELECT
  calls,
  rows,
  round(total_exec_time::numeric, 2) AS total_exec_ms,
  round(mean_exec_time::numeric, 2) AS mean_exec_ms,
  shared_blks_read,
  temp_blks_read,
  left(query, 500) AS normalized_query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY rows DESC, calls DESC
LIMIT 50;

