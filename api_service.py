import hmac
import os
import re
from contextlib import contextmanager
from datetime import date

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, status
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from course_catalog import COURSE_MAP
from multicourse import create_router
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


app = FastAPI(title="Senda Moodle Integration", version="2.1.1")


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # FastAPI's default error body can echo a password supplied in the request.
    safe = []
    for error in exc.errors():
        location = '.'.join(str(part) for part in error.get('loc', ()) if part != 'body')
        safe.append({'field': location or 'request', 'message': error.get('msg', 'Invalid value'),
                     'type': error.get('type', 'validation_error')})
    return JSONResponse(status_code=422, content={'detail': safe or 'Invalid integration payload'})


class CourseAccessUpsert(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    external_id: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=9, max_length=20)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    firstname: str = Field(min_length=1, max_length=255)
    lastname: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    dni: str = Field(min_length=1, max_length=255)
    course_code: str = Field(min_length=1, max_length=255)
    course_name: str = Field(min_length=1, max_length=255)
    start_date: date
    end_date: date
    access_url: str = Field(min_length=1, max_length=2048)
    platform: str = Field(min_length=1, max_length=255)


class CourseAccessLookup(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=255)
    course_name: str = Field(min_length=1, max_length=255)


class SyncResult(BaseModel):
    action: str
    course_name: str


class AccessResult(BaseModel):
    external_id: str
    phone: str
    username: str
    password: str
    firstname: str | None
    lastname: str | None
    email: str | None
    dni: str | None
    course_name: str
    start_date: date | None
    end_date: date | None
    access_url: str | None
    platform: str


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("SENDA_INTEGRATION_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SENDA_INTEGRATION_TOKEN is not configured",
        )
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@contextmanager
def database():
    url = os.getenv("SENDA_POSTGRES_URL", "")
    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SENDA_POSTGRES_URL is not configured",
        )
    try:
        with psycopg.connect(url, connect_timeout=10, row_factory=dict_row) as conn:
            yield conn
    except HTTPException:
        raise
    except psycopg.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable",
        ) from exc


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0034"):
        digits = digits[4:]
    elif digits.startswith("34") and len(digits) == 11:
        digits = digits[2:]
    if len(digits) != 9:
        raise HTTPException(status_code=422, detail="Phone must contain 9 national digits")
    return digits


def canonical_course(code: str, supplied_name: str) -> str:
    course = COURSE_MAP.get(code.upper())
    if not course:
        raise HTTPException(status_code=422, detail=f"Unknown course code: {code}")
    if supplied_name != course["name"]:
        raise HTTPException(status_code=422, detail="Course name does not match the catalogue")
    return course["name"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/health", dependencies=[Depends(require_token)])
def authenticated_health():
    with database() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return {"status": "ok"}


@app.post(
    "/v1/course-access/upsert",
    response_model=SyncResult,
    dependencies=[Depends(require_token)],
)
def upsert_course_access(payload: CourseAccessUpsert):
    raise HTTPException(status_code=409, detail="Upgrade Moodle: use /v2/accounts/snapshot")


@app.post(
    "/v1/course-access/lookup",
    response_model=AccessResult,
    dependencies=[Depends(require_token)],
)
def lookup_course_access(payload: CourseAccessLookup):
    if payload.course_name not in {course["name"] for course in COURSE_MAP.values()}:
        raise HTTPException(status_code=422, detail="Unknown canonical course name")

    with database() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT external_id, phone, username, password, firstname, lastname,
                       email, dni, course_name, start_date, end_date, access_url, platform
                  FROM public.current_course_access
                 WHERE username = %s AND course_name = %s
                   AND access_state = 'active' AND credentials_available
                 LIMIT 2
                """,
                (payload.username, payload.course_name),
            )
            records = cur.fetchall()
            if len(records) > 1:
                raise HTTPException(status_code=409, detail="Ambiguous course; use v2 lookup")
            record = records[0] if records else None

    if not record:
        raise HTTPException(status_code=404, detail="Course access not found")
    return AccessResult(**record)


app.include_router(create_router(database, require_token, canonical_course, normalize_phone))
