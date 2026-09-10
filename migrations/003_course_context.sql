-- Knowledge base for the WhatsApp course assistant. Moodle is authoritative.
BEGIN;

CREATE TABLE IF NOT EXISTS public.course_contexts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    platform text NOT NULL,
    moodle_course_id bigint NOT NULL,
    course_code text NOT NULL,
    course_name text NOT NULL,
    summary text NOT NULL DEFAULT '',
    objectives text NOT NULL DEFAULT '',
    methodology text NOT NULL DEFAULT '',
    audience text NOT NULL DEFAULT '',
    completion_info text NOT NULL DEFAULT '',
    assessment_info text NOT NULL DEFAULT '',
    support_notes text NOT NULL DEFAULT '',
    hours text NOT NULL DEFAULT '',
    source_url text NOT NULL DEFAULT '',
    content_hash text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    observed_at timestamptz NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, moodle_course_id)
);

CREATE TABLE IF NOT EXISTS public.course_context_sections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    course_context_id bigint NOT NULL REFERENCES public.course_contexts(id) ON DELETE CASCADE,
    moodle_section_id bigint NOT NULL,
    section_number integer NOT NULL,
    section_name text NOT NULL,
    summary text NOT NULL DEFAULT '',
    activities jsonb NOT NULL DEFAULT '[]'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    UNIQUE (course_context_id, moodle_section_id)
);

CREATE INDEX IF NOT EXISTS course_contexts_code
    ON public.course_contexts(platform, course_code);
CREATE INDEX IF NOT EXISTS course_context_sections_order
    ON public.course_context_sections(course_context_id, section_number);

CREATE OR REPLACE VIEW public.current_course_context AS
SELECT c.id AS course_context_id, c.platform, c.moodle_course_id, c.course_code,
       c.course_name, c.summary, c.objectives, c.methodology, c.audience,
       c.completion_info, c.assessment_info, c.support_notes, c.hours,
       c.source_url, c.content_hash, c.observed_at, c.synced_at,
       coalesce((
           SELECT jsonb_agg(jsonb_build_object(
               'section_number', s.section_number,
               'section_name', s.section_name,
               'summary', s.summary,
               'activities', s.activities
           ) ORDER BY s.section_number, s.moodle_section_id)
           FROM public.course_context_sections s
           WHERE s.course_context_id = c.id AND s.enabled
       ), '[]'::jsonb) AS sections
FROM public.course_contexts c
WHERE c.enabled;

COMMIT;
