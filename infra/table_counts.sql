-- Every application table's exact row count, one "table<TAB>count" line each, sorted by name.
-- Used by infra/backup.sh (manifest) and infra/restore_check.sh (comparison).
SELECT format('SELECT %L, count(*) FROM public.%I', table_name, table_name)
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name
\gexec
