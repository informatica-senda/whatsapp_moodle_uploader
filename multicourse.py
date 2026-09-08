"""Authenticated Moodle snapshots; no passwords or validation inputs in errors."""
from datetime import date, datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr, model_validator
from psycopg.types.json import Jsonb


class Window(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode='after')
    def valid_window(self):
        if self.end and self.end <= self.start:
            raise ValueError('Invalid access window')
        return self


class Enrolment(BaseModel):
    moodle_course_id: int = Field(gt=0)
    course_code: str
    course_name: str
    start_date: date | None = None
    end_date: date | None = None
    company: str = ''
    enabled: bool
    windows: list[Window]

    @model_validator(mode='after')
    def valid_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError('Invalid course period')
        return self


class Snapshot(BaseModel):
    platform: str = Field(min_length=1, max_length=255)
    moodle_user_id: int = Field(gt=0)
    username: str = Field(min_length=1, max_length=255)
    phone: str
    dni: str = ''
    firstname: str = ''
    lastname: str = ''
    email: str = ''
    access_url: str
    enabled: bool
    credential_version: str = Field(min_length=64, max_length=64)
    password: SecretStr | None = None
    observed_at: datetime
    courses: list[Enrolment]

    @model_validator(mode='after')
    def distinct_courses(self):
        ids = [c.moodle_course_id for c in self.courses]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate course')
        if self.observed_at.tzinfo is None:
            raise ValueError('Timezone required')
        return self


class Lookup(BaseModel):
    platform: str
    moodle_user_id: int
    moodle_course_id: int
    include_upcoming: bool = False


class Welcome(BaseModel):
    message_id: str = Field(min_length=1, max_length=512)
    access_id: int
    phone: str


class CredentialCandidates(BaseModel):
    platform: str
    username: str
    phone: str


def create_router(database, require_token, canonical_course, normalize_phone):
    router = APIRouter(prefix='/v2', dependencies=[Depends(require_token)])

    @router.get('/health')
    def health():
        with database() as conn:
            conn.execute('SELECT access_id FROM public.current_course_access LIMIT 0')
        return {'status': 'ok', 'version': 2}

    @router.post('/accounts/snapshot')
    def snapshot(p: Snapshot):
        phone = normalize_phone(p.phone) if p.phone else ''
        for course in p.courses:
            canonical_course(course.course_code, course.course_name)
        if p.observed_at > datetime.now(timezone.utc):
            # Allow ordinary clock skew, but never allow a far-future snapshot to freeze updates.
            if (p.observed_at - datetime.now(timezone.utc)).total_seconds() > 300:
                raise HTTPException(422, 'Snapshot clock is ahead')
        password = p.password.get_secret_value() if p.password else None
        if password == '':
            raise HTTPException(422, 'Empty credential')
        with database() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                         (f'{p.platform}:{p.moodle_user_id}',))
            previous = conn.execute('SELECT * FROM public.campus_accounts WHERE platform=%s AND moodle_user_id=%s FOR UPDATE',
                                    (p.platform, p.moodle_user_id)).fetchone()
            if previous and previous['observed_at'] > p.observed_at:
                raise HTTPException(409, 'Stale snapshot; retry with current Moodle state')
            if password is None and previous and previous['credential_version'] == p.credential_version:
                password = previous['password']
            if not p.enabled:
                password = None
            account = conn.execute('''INSERT INTO public.campus_accounts
                (platform,moodle_user_id,username,phone,dni,password,credential_version,enabled,synced_at,observed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now(),%s)
                ON CONFLICT(platform,moodle_user_id) DO UPDATE SET
                username=excluded.username,phone=excluded.phone,dni=excluded.dni,password=excluded.password,
                credential_version=excluded.credential_version,enabled=excluded.enabled,
                synced_at=now(),observed_at=excluded.observed_at RETURNING id''',
                (p.platform,p.moodle_user_id,p.username,phone,p.dni,password,p.credential_version,p.enabled,p.observed_at)).fetchone()
            aid = account['id']
            # Snapshot is complete for this account, never a CSV delta.
            conn.execute('UPDATE public.course_access SET enrolment_enabled=false, password=%s, updated_at=now() WHERE account_id=%s',
                         (password or '', aid))
            inserted = updated = 0
            for c in p.courses:
                old = conn.execute('SELECT access_id FROM public.course_access WHERE account_id=%s AND moodle_course_id=%s',
                                   (aid,c.moodle_course_id)).fetchone()
                conn.execute('''INSERT INTO public.course_access
                    (external_id,phone,username,password,firstname,lastname,email,dni,course_name,start_date,end_date,
                     access_url,platform,account_id,moodle_course_id,course_code,company,enrolment_enabled,access_windows)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(account_id,moodle_course_id) DO UPDATE SET
                    phone=excluded.phone,username=excluded.username,password=excluded.password,
                    firstname=excluded.firstname,lastname=excluded.lastname,email=excluded.email,dni=excluded.dni,
                    course_name=excluded.course_name,start_date=excluded.start_date,end_date=excluded.end_date,
                    access_url=excluded.access_url,course_code=excluded.course_code,company=excluded.company,
                    enrolment_enabled=excluded.enrolment_enabled,access_windows=excluded.access_windows,updated_at=now()''',
                    (str(uuid4()),phone,p.username,password or '',p.firstname,p.lastname,p.email,p.dni,c.course_name,
                     c.start_date,c.end_date,p.access_url,p.platform,aid,c.moodle_course_id,c.course_code.upper(),
                     c.company,c.enabled,Jsonb([w.model_dump() for w in c.windows])))
                updated += bool(old)
                inserted += not bool(old)
        return {'inserted': inserted, 'updated': updated, 'credentials_available': bool(password)}

    @router.post('/accounts/credential-candidates')
    def credential_candidates(p: CredentialCandidates):
        # This private endpoint is ONLY for Moodle to validate against its current hash.
        # It never establishes validity and is not used by n8n to send credentials.
        phone = normalize_phone(p.phone) if p.phone else ''
        with database() as conn:
            rows = conn.execute('''SELECT DISTINCT password FROM public.course_access
                WHERE platform=%s AND username=%s AND phone=%s AND password <> '' LIMIT 20''',
                (p.platform,p.username,phone)).fetchall()
        return {'candidates': [r['password'] for r in rows]}

    @router.post('/course-access/lookup')
    def lookup(p: Lookup):
        states = ['active', 'upcoming'] if p.include_upcoming else ['active']
        with database() as conn:
            row = conn.execute('''SELECT c.* FROM public.current_course_access c
                JOIN public.campus_accounts a ON a.id=c.account_id
                WHERE a.platform=%s AND a.moodle_user_id=%s AND c.moodle_course_id=%s
                AND c.access_state=ANY(%s)''',
                (p.platform,p.moodle_user_id,p.moodle_course_id,states)).fetchone()
        if not row:
            raise HTTPException(404, 'No current enrolment')
        # Never return the compatibility copy if the account no longer has a verified credential.
        if not row['credentials_available']:
            row['password'] = ''
        return row

    @router.post('/welcome-links')
    def welcome(p: Welcome):
        phone = normalize_phone(p.phone)
        with database() as conn:
            exists = conn.execute('SELECT 1 FROM public.current_course_access WHERE access_id=%s AND phone=%s AND access_state IN (\'active\',\'upcoming\')',
                                  (p.access_id,phone)).fetchone()
            if not exists:
                raise HTTPException(404, 'No current enrolment')
            conn.execute('INSERT INTO public.wa_welcome_links(message_id,access_id,phone) VALUES (%s,%s,%s) ON CONFLICT(message_id) DO NOTHING',
                         (p.message_id,p.access_id,phone))
        return {'status': 'ok'}

    return router
