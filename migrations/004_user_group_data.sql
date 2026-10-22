-- Additive mirror for Moodle's current per-user, per-group metadata.
-- Existing course_access and n8n contracts are intentionally untouched.
CREATE TABLE IF NOT EXISTS public.user_group_data (
    id bigserial PRIMARY KEY,
    platform varchar(255) NOT NULL,
    moodle_user_id bigint NOT NULL CHECK (moodle_user_id > 0),
    group_key varchar(100) NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    username varchar(255) NOT NULL DEFAULT '',
    dni varchar(100) NOT NULL DEFAULT '',
    empresa varchar(255) NOT NULL DEFAULT '',
    cif varchar(100) NOT NULL DEFAULT '',
    inicio varchar(40) NOT NULL DEFAULT '',
    fin varchar(40) NOT NULL DEFAULT '',
    nombrecompleto varchar(255) NOT NULL DEFAULT '',
    group_id bigint NULL,
    course_id bigint NULL,
    observed_at timestamptz NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, moodle_user_id, group_key)
);

CREATE INDEX IF NOT EXISTS user_group_data_group_idx
    ON public.user_group_data (platform, group_key);
