-- Read-only preflight. Save the result with the deployment record.
SELECT current_setting('server_version') AS postgres_version;
SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public'
 AND tablename IN ('course_access','wa_conversations','wa_messages','wa_contact_state','wa_conversation_memory')
 ORDER BY tablename,indexname;
SELECT conrelid::regclass AS table_name,conname,pg_get_constraintdef(oid) AS definition
 FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conrelid::regclass::text,conname;
SELECT column_name,data_type,is_nullable,column_default FROM information_schema.columns
 WHERE table_schema='public' AND table_name='course_access' ORDER BY ordinal_position;