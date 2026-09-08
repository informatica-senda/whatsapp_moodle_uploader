-- Synthetic baseline from supplied CSV headers; no customer records.
CREATE TABLE public.course_access (
 external_id text NOT NULL,phone text NOT NULL,username text NOT NULL,password text NOT NULL,
 firstname text,lastname text,email text,dni text,course_name text NOT NULL,start_date date,end_date date,
 platform text NOT NULL DEFAULT 'moodle_senda',access_url text,source_file text,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.wa_conversations(id bigserial PRIMARY KEY,phone text,channel text,user_name text,status text,last_message_at timestamptz,
 created_at timestamptz DEFAULT now(),updated_at timestamptz DEFAULT now(), UNIQUE(phone,channel));
CREATE TABLE public.wa_messages(id bigserial PRIMARY KEY,conversation_id bigint REFERENCES public.wa_conversations(id),message_id text UNIQUE,
 direction text,role text,content_type text,content text,media_id text,mime_type text,raw_payload jsonb,created_at timestamptz DEFAULT now());
CREATE TABLE public.wa_contact_state(id bigserial PRIMARY KEY,phone text UNIQUE,current_step text,last_intent text,
 last_course_name text,course_access_external_id text,human_takeover boolean DEFAULT false,bot_enabled boolean DEFAULT true,
 last_seen_at timestamptz,created_at timestamptz DEFAULT now(),updated_at timestamptz DEFAULT now());
CREATE TABLE public.wa_conversation_memory(id bigserial PRIMARY KEY,conversation_id bigint UNIQUE,short_summary text,long_summary text,
 user_intent text,course_name text,course_access_id text,last_detected_issue text,sentiment text,needs_human boolean,last_ai_update_at timestamptz,
 created_at timestamptz DEFAULT now(),updated_at timestamptz DEFAULT now());
