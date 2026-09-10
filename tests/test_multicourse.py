"""API business logic against PostgreSQL (PGlite), without production services.

PGLITE_MODULE must point to an installed @electric-sql/pglite package directory.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api_service import canonical_course, normalize_phone, require_token
from multicourse import (create_router, Snapshot, Lookup, CredentialCandidates,
                         CourseContextSnapshot)
from fastapi import HTTPException


class PG:
    def __init__(self):
        self.proc = subprocess.Popen(['node',str(ROOT/'tests/pg_bridge.cjs'),os.environ['PGLITE_MODULE']],
                                     stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8')

    def run(self, sql, params=(), script=False):
        def convert(v):
            if hasattr(v,'obj'): return json.dumps(v.obj)
            if hasattr(v,'isoformat'): return v.isoformat()
            return v
        number=iter(range(1,100))
        import re
        sql=re.sub(r'%s',lambda _: '$'+str(next(number)),sql)
        self.proc.stdin.write(json.dumps({'sql':sql,'params':[convert(p) for p in params],'exec':script})+'\n')
        self.proc.stdin.flush()
        result=json.loads(self.proc.stdout.readline())
        if 'error' in result: raise AssertionError(result['error'])
        rows=[] if script else result['result']['rows']
        for row in rows:
            for key,value in list(row.items()):
                if key.endswith('_at') and isinstance(value,str):
                    row[key]=datetime.fromisoformat(value.replace('Z','+00:00'))
        return rows

    def execute(self, sql, params=()):
        rows=self.run(sql,params)
        class Result:
            def fetchone(self): return rows[0] if rows else None
            def fetchall(self): return rows
        return Result()

    @contextmanager
    def transaction(self):
        self.run('BEGIN')
        try:
            yield self
            self.run('COMMIT')
        except BaseException:
            self.run('ROLLBACK')
            raise

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=15)
        self.proc.stdout.close()


class MulticourseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pg=PG()
        cls.pg.run((ROOT/'tests/legacy_schema.sql').read_text(),script=True)
        migration=(ROOT/'migrations/002_multicourse.sql').read_text()
        cls.pg.run(migration,script=True)
        cls.pg.run(migration,script=True)
        contextmigration=(ROOT/'migrations/003_course_context.sql').read_text()
        cls.pg.run(contextmigration,script=True)
        cls.pg.run(contextmigration,script=True)
        router=create_router(cls.pg.transaction,lambda:None,canonical_course,normalize_phone)
        cls.endpoints={r.path:r.endpoint for r in router.routes}

    @classmethod
    def tearDownClass(cls): cls.pg.close()

    def setUp(self):
        self.pg.run('TRUNCATE public.wa_welcome_links,public.course_access,public.campus_accounts RESTART IDENTITY CASCADE')
        now=datetime.now(timezone.utc)
        self.payload={'platform':'moodle_senda','moodle_user_id':123,'username':'synthetic-user','phone':'612000000',
            'dni':'SYNTHETIC','firstname':'Test','lastname':'User','email':'test@example.invalid','enabled':True,
            'credential_version':'a'*64,'password':'Synthetic-only-99','access_url':'https://example.invalid',
            'observed_at':now,'courses':[self.course(344),self.course(376)]}

    def course(self,cid,offset=0):
        today=datetime.now(timezone.utc).date()
        return {'moodle_course_id':cid,'course_code':f'GEM-SENSI-{cid}','course_name':'Sensibilización en Igualdad',
            'start_date':today+timedelta(days=-1+offset),'end_date':today+timedelta(days=10+offset),
            'company':'Synthetic','enabled':True,'windows':[{'start':0,'end':0}]}

    def sync(self):
        self.payload['observed_at']=datetime.now(timezone.utc)
        return self.endpoints['/v2/accounts/snapshot'](Snapshot(**self.payload))

    def test_two_courses_same_name_and_idempotent_dates(self):
        self.assertEqual(self.sync()['inserted'],2)
        self.payload['courses'][0]['end_date']+=timedelta(days=2)
        self.assertEqual(self.sync()['updated'],2)
        rows=self.pg.run('SELECT * FROM public.current_course_access')
        self.assertEqual(len(rows),2)
        self.assertEqual({r['access_state'] for r in rows},{'active'})
        self.assertEqual(len({r['external_id'] for r in rows}),2)

    def test_existing_password_preserved_and_changed_hash_invalidates(self):
        self.sync()
        self.payload['password']=None
        self.assertTrue(self.sync()['credentials_available'])
        self.payload['credential_version']='b'*64
        self.assertFalse(self.sync()['credentials_available'])
        self.assertTrue(all(r['password']=='' for r in self.pg.run('SELECT password FROM public.course_access')))

    def test_removal_suspension_future_expiration_and_stale(self):
        self.sync()
        self.payload['courses']=self.payload['courses'][:1]
        self.sync()
        self.assertEqual(self.pg.run("SELECT count(*) AS n FROM public.current_course_access WHERE access_state='active'")[0]['n'],1)
        self.payload['courses'][0]['windows']=[{'start':0,'end':1}]
        self.sync()
        self.assertEqual(self.pg.run("SELECT count(*) AS n FROM public.current_course_access WHERE access_state='active'")[0]['n'],0)
        self.payload['courses']=[self.course(344,5)]
        self.sync()
        self.assertEqual(self.pg.run("SELECT access_state FROM public.current_course_access WHERE moodle_course_id=344")[0]['access_state'],'upcoming')
        self.pg.run("UPDATE public.campus_accounts SET synced_at=now()-interval '3 hours'")
        self.assertEqual(self.pg.run("SELECT access_state FROM public.current_course_access WHERE moodle_course_id=344")[0]['access_state'],'inactive')
        self.payload['enabled']=False
        self.assertFalse(self.sync()['credentials_available'])

    def test_lookup_is_exact_and_expired_is_404(self):
        self.sync()
        lookup=self.endpoints['/v2/course-access/lookup']
        p=Lookup(platform='moodle_senda',moodle_user_id=123,moodle_course_id=376)
        self.assertEqual(lookup(p)['course_code'],'GEM-SENSI-376')
        self.pg.run("UPDATE public.course_access SET end_date=(now() AT TIME ZONE 'Europe/Madrid')::date-1")
        with self.assertRaises(HTTPException) as e: lookup(p)
        self.assertEqual(e.exception.status_code,404)

    def test_legacy_rows_are_not_assumed_active(self):
        self.pg.run("INSERT INTO public.course_access(external_id,phone,username,password,course_name) VALUES ('legacy','612000000','synthetic-user','Legacy-test','old')")
        self.assertEqual(self.pg.run('SELECT count(*) AS n FROM public.current_course_access')[0]['n'],0)
        endpoint=self.endpoints['/v2/accounts/credential-candidates']
        self.assertEqual(endpoint(CredentialCandidates(platform='moodle_senda',username='synthetic-user',phone='34612000000'))['candidates'],['Legacy-test'])

    def test_out_of_order_snapshot_rejected(self):
        self.sync()
        self.payload['observed_at']-=timedelta(minutes=1)
        with self.assertRaises(HTTPException) as e:
            self.endpoints['/v2/accounts/snapshot'](Snapshot(**self.payload))
        self.assertEqual(e.exception.status_code,409)

    def test_empty_snapshot_and_expired_future_window(self):
        self.sync()
        self.payload['courses']=[]
        self.sync()
        self.assertEqual(self.pg.run("SELECT count(*) AS n FROM public.current_course_access WHERE access_state='active'")[0]['n'],0)
        self.payload['courses']=[self.course(344,5)]
        self.payload['courses'][0]['windows']=[{'start':0,'end':1}]
        self.sync()
        self.assertEqual(self.pg.run("SELECT access_state FROM public.current_course_access WHERE moodle_course_id=344")[0]['access_state'],'inactive')

    def test_preflight_refuses_legacy_username_uniqueness(self):
        self.pg.run('CREATE UNIQUE INDEX synthetic_legacy_username ON public.course_access(username)')
        try:
            with self.assertRaisesRegex(AssertionError,'Review legacy unique index'):
                self.pg.run((ROOT/'migrations/002_multicourse.sql').read_text(),script=True)
        finally:
            self.pg.run('ROLLBACK')
            self.pg.run('DROP INDEX synthetic_legacy_username')

    def test_catalogue_and_token(self):
        # The authenticated Moodle catalogue is authoritative for new courses.
        self.payload['courses'][0]['course_code']='NEW-COURSE-900'
        self.payload['courses'][0]['course_name']='Curso nuevo gestionado en Moodle'
        self.assertEqual(self.sync()['inserted'],2)
        os.environ['SENDA_INTEGRATION_TOKEN']='synthetic-test-token'
        with self.assertRaises(HTTPException): require_token('Bearer wrong')
        require_token('Bearer synthetic-test-token')

    def test_course_context_snapshot_replaces_structure_without_deleting_history(self):
        now=datetime.now(timezone.utc)
        payload={'platform':'moodle_senda','moodle_course_id':344,'course_code':'GEM-SENSI-344',
            'course_name':'Sensibilización en Igualdad','summary':'Resumen','objectives':'Objetivos',
            'methodology':'Vídeos por unidad','audience':'Plantilla','completion_info':'Completar vídeos',
            'assessment_info':'Cuestionario','support_notes':'Ayuda específica','hours':'5',
            'source_url':'https://example.invalid/course/344','content_hash':'a'*64,'enabled':True,
            'observed_at':now,'sections':[{'moodle_section_id':10,'section_number':0,
                'section_name':'','summary':'Introducción','activities':[
                    {'module':'url','name':'Vídeo 1','completion':'Automática'}]}]}
        endpoint=self.endpoints['/v2/course-contexts/snapshot']
        first=endpoint(CourseContextSnapshot(**payload))
        self.assertTrue(first['changed'])
        initial=self.pg.run('SELECT section_name FROM public.course_context_sections WHERE moodle_section_id=10')[0]
        self.assertEqual(initial['section_name'],'General')
        payload['content_hash']='b'*64
        payload['observed_at']=datetime.now(timezone.utc)
        payload['sections']=[{'moodle_section_id':11,'section_number':2,
            'section_name':'Unidad 2','activities':[]}]
        endpoint(CourseContextSnapshot(**payload))
        current=self.pg.run('SELECT * FROM public.current_course_context WHERE moodle_course_id=344')[0]
        self.assertEqual(current['methodology'],'Vídeos por unidad')
        sections=current['sections'] if isinstance(current['sections'],list) else json.loads(current['sections'])
        self.assertEqual([s['section_name'] for s in sections],['Unidad 2'])
        self.assertEqual(self.pg.run('SELECT count(*) AS n FROM public.course_context_sections')[0]['n'],2)

    def test_http_contract_and_validation_redaction(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi.exceptions import RequestValidationError
        from api_service import validation_error
        testapp=FastAPI()
        testapp.add_exception_handler(RequestValidationError,validation_error)
        testapp.include_router(create_router(self.pg.transaction,require_token,canonical_course,normalize_phone))
        os.environ['SENDA_INTEGRATION_TOKEN']='synthetic-test-token'
        headers={'Authorization':'Bearer synthetic-test-token'}
        with TestClient(testapp) as client:
            self.assertEqual(client.get('/v2/health').status_code,401)
            self.assertEqual(client.get('/v2/health',headers=headers).status_code,200)
            body=Snapshot(**self.payload).model_dump(mode='json')
            body['password']='Synthetic-http-77'
            response=client.post('/v2/accounts/snapshot',json=body,headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['inserted'],2)
            body['password']={'invalid':'Synthetic-secret-never-echo'}
            response=client.post('/v2/accounts/snapshot',json=body,headers=headers)
            self.assertEqual(response.status_code,422)
            self.assertNotIn('Synthetic-secret',response.text)


if __name__=='__main__': unittest.main(verbosity=2)
