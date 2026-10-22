# API Moodle multicurso v2

La sincronización de Moodle se inicia en `local_senda` y llega a esta API por HTTPS; Moodle no se conecta directamente
a PostgreSQL. Otros servicios, como n8n, conservan su propio acceso configurado. Mantén PostgreSQL privado y usa bases
y credenciales separadas para pruebas y producción. No apuntes pruebas a producción.

El runtime de la API está formado por `api_service.py`, `multicourse.py`, `course_catalog.py` y
`requirements-api.lock`, que fija las dependencias exactas con hashes para Python 3.12/Linux. El contenedor se construye
con `Dockerfile` (o `Dockerfile.api`); ambos usan el mismo lock y ejecutan con un usuario no root. Las utilidades antiguas de
escritorio no forman parte de la imagen.

## Versión

**2.1.3 (2026-10-22).** Endurecimiento del despliegue: dependencias bloqueadas con hashes, contenedor no root, límite de 64 MiB por petición y exclusión de archivos de entorno del contexto Docker. Sin cambios en los contratos de la API.

## Configuración y despliegue

Python 3.12. El lock con hashes está dirigido al contenedor Linux. Para ejecutar localmente en desarrollo:

```sh
pip install -r requirements-api.txt
uvicorn api_service:app --host 0.0.0.0 --port 8000
```

Define únicamente en el gestor de secretos del servicio:

- `SENDA_POSTGRES_URL`: conexión privada a la base de datos de ese entorno.
- `SENDA_INTEGRATION_TOKEN`: secreto compartido con el ajuste `integrationapitoken` de Moodle.

En EasyPanel/Docker, publica el puerto interno `8000` detrás de HTTPS y configura ambas variables. La aplicación corre
como UID 10001, ignora cabeceras `X-Forwarded-*` y limita el cuerpo HTTP a 64 MiB (incluidas peticiones sin
`Content-Length`). No guardes secretos en Git, en este README ni en logs. `GET /health` es una comprobación pública
básica; las rutas `/v1` y `/v2` requieren `Authorization: Bearer <token>`. No registres cuerpos ni respuestas de estas
rutas: algunas respuestas contienen credenciales necesarias para Moodle.

Configura en el proxy de EasyPanel, usando la IP real del cliente que ve el proxy, estos límites por IP:

- Rutas de la API: 1.200 peticiones por minuto, con ráfaga de 100.
- Fallos de autenticación (`401`): 30 intentos por minuto.
- Tamaño máximo de cuerpo: 64 MiB (igual que la aplicación).

Mantén el puerto 8000 accesible solo desde el proxy y no actives confianza indiscriminada en cabeceras reenviadas. La
aplicación no interpreta esas cabeceras; el proxy debe aplicar sus límites por IP directamente. Si se cambia de proxy
o se ejecutan varias réplicas, verificar que las cuotas siguen siendo globales por IP y no solo por instancia.
`/health` debe quedar exento del límite de autenticación y responder `200` sin consultar PostgreSQL.

Moodle envía `platform` en cada petición y la API lo guarda como identificador del campus; no existe una lista de
plataformas que haya que registrar aparte. Usa valores distintos por entorno, por ejemplo `moodle_senda_test` para
staging y `moodle_senda` para producción, con API, token y base PostgreSQL separados.

## Preparar el esquema de datos por grupo en staging

`migrations/004_user_group_data.sql` crea de forma aditiva `public.user_group_data` y su índice. No modifica
`course_access`, las tablas de WhatsApp ni las de contexto. La migración no importa datos; Moodle los envía después
cuando su cron procesa las filas pendientes. La API no ejecuta migraciones al arrancar, así que hay que aplicar la
migración antes de habilitar la sincronización por grupo.

Aplicar el archivo desde un cliente administrativo `psql` con acceso a la base correcta, fuera del contenedor de la API
(la imagen no incluye `psql` ni los archivos de migración). Antes de ejecutar DDL, confirmar que la conexión corresponde
a la base de staging o producción que se va a actualizar:

```sh
psql "$SENDA_POSTGRES_URL" -X -v ON_ERROR_STOP=1 -c "SELECT current_database(), current_user;"
```

Continuar solo si la base devuelta es exactamente el destino esperado. Aplicar la migración desde una copia del repositorio:

```sh
psql "$SENDA_POSTGRES_URL" -X -v ON_ERROR_STOP=1 -f migrations/004_user_group_data.sql
```

Se puede repetir: la creación de la tabla y el índice usa `IF NOT EXISTS`. La migración debe ejecutarse con el usuario
PostgreSQL de la API para que este sea propietario de la secuencia y la tabla. Si se aplica con un usuario DBA distinto,
conceder al usuario configurado en `SENDA_POSTGRES_URL` `SELECT`, `INSERT`, `UPDATE` y `DELETE` sobre la tabla, además
de `USAGE` y `SELECT` sobre `public.user_group_data_id_seq`.

Comprobar columnas y tipos:

```sql
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'user_group_data'
 ORDER BY ordinal_position;
```

Comprobar la clave única y el índice:

```sql
SELECT conname, pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE conrelid = 'public.user_group_data'::regclass;

SELECT indexname, indexdef
  FROM pg_indexes
 WHERE schemaname = 'public' AND tablename = 'user_group_data';
```

Comprobar las filas esperadas para ese entorno y que el rol de la API tiene los permisos necesarios:

```sql
SELECT platform, count(*) AS filas, max(synced_at) AS ultima_sincronizacion
  FROM public.user_group_data GROUP BY platform ORDER BY platform;
SELECT has_table_privilege(current_user, 'public.user_group_data', 'SELECT') AS can_select,
       has_table_privilege(current_user, 'public.user_group_data', 'INSERT') AS can_insert,
       has_table_privilege(current_user, 'public.user_group_data', 'UPDATE') AS can_update,
       has_table_privilege(current_user, 'public.user_group_data', 'DELETE') AS can_delete,
       has_sequence_privilege(current_user, 'public.user_group_data_id_seq', 'USAGE') AS can_use_id_sequence;
```

Si la estructura existente no coincide, detenerse y revisar el estado antes de aplicar cambios manuales o eliminar objetos.
No usar la URL, token ni base de producción para este procedimiento.

Arranque local: `uvicorn api_service:app --host 0.0.0.0 --port 8000 --no-proxy-headers`. Python 3.12; los Dockerfiles
usan un usuario no root y no habilitan confianza en cabeceras proxy.
Conservar `SENDA_POSTGRES_URL` y `SENDA_INTEGRATION_TOKEN` en EasyPanel; no incluir sus valores en archivos versionados.

Endpoints privados, todos con `Authorization: Bearer`:

- `GET /v2/health`: valida las vistas de acceso y contexto. No sustituye la comprobación de `user_group_data`.
- `POST /v2/accounts/snapshot`: cuenta verificada por Moodle y lista completa de matrículas gestionadas.
- `POST /v2/accounts/credential-candidates`: candidatas antiguas exclusivamente para que Moodle las valide; no para el agente.
- `POST /v2/course-access/lookup`: plataforma, `moodle_user_id`, `moodle_course_id`, `include_upcoming` opcional.
- `POST /v2/welcome-links`: relaciona `message_id`, `access_id` y teléfono tras un envío confirmado.
- `POST /v2/course-contexts/snapshot`: descripción, objetivos, metodología, secciones y actividades extraídas por Moodle.
- `POST /v2/user-group-data/snapshots`: recibe de 1 a 100 filas; unicidad por campus, alumno y grupo. Una revisión más antigua no reemplaza una nueva; responde con contadores `inserted`, `updated` y `stale`.
- `DELETE /v2/user-group-data/{platform}/{moodle_user_id}`: elimina la réplica por alumno tras una solicitud aprobada de privacidad.

Los modelos de petición están en `multicourse.py` y el contrato se publica en `/openapi.json`. La API conserva
`GET /health` público y `/v1/health` privado. La escritura v1 responde 409 para exigir actualizar Moodle. La consulta
v1 admite solo matrículas activas verificadas y responde 409 si un nombre identifica varias.

`course_access` conserva el histórico y su forma anterior, con nuevas columnas de relación. Las filas heredadas no se
suponen activas. `current_course_access` filtra el estado a partir de la sincronización Moodle y las ventanas de matrícula.

El procedimiento del lado Moodle (importación CSV, edición en el perfil, backfill y controles) está documentado en
`local_senda/docs/USER_GROUP_DATA.md` dentro del repositorio del plugin.

Pruebas: instalar `requirements-dev.txt`; instalar `@electric-sql/pglite` en un directorio de pruebas y definir
`PGLITE_MODULE` con su ruta absoluta. Ejecutar `python tests/test_multicourse.py`. No usa registros ni servicios reales.
