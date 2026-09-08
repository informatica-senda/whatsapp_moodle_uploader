-- Apply once, in staging first. No historical rows are deleted or guessed.
BEGIN;
-- CSV headers do not describe unique constraints. Refuse incompatible legacy
-- uniqueness instead of silently dropping constraints or deleting history.
DO $$
DECLARE blocker text;
BEGIN
    SELECT i.indexrelid::regclass::text INTO blocker
    FROM pg_index i WHERE i.indrelid='public.course_access'::regclass AND i.indisunique
      AND NOT EXISTS (SELECT 1 FROM unnest(i.indkey) k
          JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k
          WHERE a.attname IN ('external_id','access_id','account_id'))
    LIMIT 1;
    IF blocker IS NOT NULL THEN
        RAISE EXCEPTION 'Review legacy unique index % before multicourse migration; do not delete historical rows', blocker;
    END IF;
END $$;
CREATE TABLE IF NOT EXISTS public.campus_accounts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    platform text NOT NULL,
    moodle_user_id bigint NOT NULL,
    username text NOT NULL,
    phone text NOT NULL,
    dni text,
    password text,
    credential_version text NOT NULL,
    enabled boolean NOT NULL,
    synced_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    UNIQUE (platform, moodle_user_id),
    UNIQUE (platform, username)
);
ALTER TABLE public.course_access
    ADD COLUMN IF NOT EXISTS access_id bigint GENERATED ALWAYS AS IDENTITY,
    ADD COLUMN IF NOT EXISTS account_id bigint REFERENCES public.campus_accounts(id),
    ADD COLUMN IF NOT EXISTS moodle_course_id bigint,
    ADD COLUMN IF NOT EXISTS course_code text,
    ADD COLUMN IF NOT EXISTS company text,
    ADD COLUMN IF NOT EXISTS enrolment_enabled boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS access_windows jsonb NOT NULL DEFAULT '[]'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS course_access_access_id ON public.course_access(access_id);
CREATE UNIQUE INDEX IF NOT EXISTS course_access_moodle_identity
    ON public.course_access(account_id, moodle_course_id);
CREATE INDEX IF NOT EXISTS campus_accounts_phone ON public.campus_accounts(phone);

-- A credential belongs to the campus account. Legacy password column remains
-- for compatibility, but only the account's verified copy is used by v2 readers.
CREATE OR REPLACE VIEW public.current_course_access AS
SELECT c.*, a.enabled AS account_enabled,
       CASE WHEN a.enabled AND a.synced_at > now() - interval '2 hours'
                 AND c.enrolment_enabled AND c.start_date IS NOT NULL AND c.end_date IS NOT NULL
                 AND c.start_date <= (now() AT TIME ZONE 'Europe/Madrid')::date
                 AND c.end_date >= (now() AT TIME ZONE 'Europe/Madrid')::date
                 AND EXISTS (SELECT 1 FROM jsonb_array_elements(c.access_windows) w
                     WHERE ((w->>'start')::bigint = 0 OR (w->>'start')::bigint <= extract(epoch FROM now()))
                       AND ((w->>'end')::bigint = 0 OR (w->>'end')::bigint > extract(epoch FROM now())))
            THEN 'active'
            WHEN a.enabled AND a.synced_at > now() - interval '2 hours'
                 AND c.enrolment_enabled AND c.start_date > (now() AT TIME ZONE 'Europe/Madrid')::date
                 AND c.end_date >= c.start_date
                 AND EXISTS (SELECT 1 FROM jsonb_array_elements(c.access_windows) w
                     WHERE ((w->>'end')::bigint = 0 OR (w->>'end')::bigint > extract(epoch FROM now()))
                       AND ((w->>'start')::bigint = 0 OR (w->>'start')::bigint <
                           extract(epoch FROM ((c.end_date + 1)::timestamp AT TIME ZONE 'Europe/Madrid')))
                       AND ((w->>'end')::bigint = 0 OR (w->>'end')::bigint >
                           extract(epoch FROM (c.start_date::timestamp AT TIME ZONE 'Europe/Madrid')))) THEN 'upcoming'
            ELSE 'inactive' END AS access_state,
       (a.password IS NOT NULL AND a.password <> '') AS credentials_available
FROM public.course_access c JOIN public.campus_accounts a ON a.id = c.account_id;

-- Preserve the old memory table as history. New context reads scoped wa_messages.
ALTER TABLE public.wa_contact_state ADD COLUMN IF NOT EXISTS selected_access_id bigint,
    ADD COLUMN IF NOT EXISTS selected_at timestamptz;
ALTER TABLE public.wa_messages ADD COLUMN IF NOT EXISTS access_id bigint,
    ADD COLUMN IF NOT EXISTS context_scope text,
    ADD COLUMN IF NOT EXISTS reply_to_message_id text;
CREATE TABLE IF NOT EXISTS public.wa_welcome_links (
    message_id text PRIMARY KEY,
    access_id bigint NOT NULL REFERENCES public.course_access(access_id),
    phone text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMIT;
