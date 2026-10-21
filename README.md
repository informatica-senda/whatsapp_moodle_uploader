# API Moodle multicurso v2

La sincronización autoritativa se realiza desde el plugin Moodle por HTTPS. Mantener el puerto PostgreSQL privado.
Aplicar `migrations/001_inspect.sql` (solo lectura) y las migraciones necesarias en la base de pruebas antes de habilitar
la API. No apuntar las pruebas a producción.
La guía coordinada está en `local/enviarmensaje/integration/MULTICURSO.md` del plugin.

## Preparar el esquema de datos por grupo en staging

`migrations/004_user_group_data.sql` crea únicamente `public.user_group_data` y su índice. No modifica
`course_access`, las tablas de WhatsApp ni las de contexto. La migración no copia datos de Moodle y la tabla debe
quedar vacía hasta que se active posteriormente la sincronización desde Moodle. La API no ejecuta migraciones al arrancar.

Aplicar el archivo desde una consola del servicio/API de pruebas que tenga configurada su propia variable
`SENDA_POSTGRES_URL`. Antes de ejecutar DDL, confirmar que la URL corresponde a la base de staging:

```sh
psql "$SENDA_POSTGRES_URL" -X -v ON_ERROR_STOP=1 -c "SELECT current_database(), current_user;"
```

Continuar solo si la base devuelta es la base de pruebas esperada. Aplicar la migración desde la raíz del repositorio:

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

Comprobar que aún no se han cargado alumnos y que el rol de la API tiene los permisos necesarios:

```sql
SELECT count(*) AS rows_expected_zero FROM public.user_group_data;
SELECT has_table_privilege(current_user, 'public.user_group_data', 'SELECT') AS can_select,
       has_table_privilege(current_user, 'public.user_group_data', 'INSERT') AS can_insert,
       has_table_privilege(current_user, 'public.user_group_data', 'UPDATE') AS can_update,
       has_table_privilege(current_user, 'public.user_group_data', 'DELETE') AS can_delete,
       has_sequence_privilege(current_user, 'public.user_group_data_id_seq', 'USAGE') AS can_use_id_sequence;
```

Si la estructura existente no coincide, detenerse y revisar el estado antes de aplicar cambios manuales o eliminar objetos.
No usar la URL, token ni base de producción para este procedimiento.

Arranque: `uvicorn api_service:app --host 0.0.0.0 --port 8000`. Python 3.12; Dockerfile actualizado.
Conservar `SENDA_POSTGRES_URL` y `SENDA_INTEGRATION_TOKEN` en EasyPanel; no incluir sus valores en archivos versionados.

Endpoints privados, todos con `Authorization: Bearer`:

- `GET /v2/health`: conexión y disponibilidad del esquema v2.
- `POST /v2/accounts/snapshot`: cuenta verificada por Moodle y lista completa de matrículas gestionadas.
- `POST /v2/accounts/credential-candidates`: candidatas antiguas exclusivamente para que Moodle las valide; no para el agente.
- `POST /v2/course-access/lookup`: plataforma, `moodle_user_id`, `moodle_course_id`, `include_upcoming` opcional.
- `POST /v2/welcome-links`: relaciona `message_id`, `access_id` y teléfono tras un envío confirmado.
- `POST /v2/course-contexts/snapshot`: descripción, objetivos, metodología, secciones y actividades extraídas por Moodle.
- `POST /v2/user-group-data/snapshots`: lote idempotente por plataforma, alumno y código de grupo; solo revisiones iguales o superiores reemplazan la fila.
- `DELETE /v2/user-group-data/{platform}/{moodle_user_id}`: elimina la réplica por alumno tras una solicitud aprobada de privacidad.

Los modelos de petición están en `multicourse.py` y el contrato se publica en `/openapi.json`.
El catálogo autenticado que envía Moodle es la fuente de nombres y códigos; añadir un curso al plugin no requiere modificar
una segunda lista dentro de la API.
La API conserva `GET /health` público y `/v1/health` privado. La escritura v1 responde 409 para exigir actualizar Moodle.
La consulta v1 admite solo matrículas activas verificadas y responde 409 si un nombre identifica varias.

`course_access` conserva el histórico y su forma anterior, con nuevas columnas de relación. Las filas heredadas no se
suponen activas. `current_course_access` filtra el estado a partir de la sincronización Moodle y las ventanas de matrícula.
El programa de escritorio conserva su interfaz y utilidades, pero su botón de subir a PostgreSQL indica usar Moodle.

Pruebas: instalar `requirements-dev.txt`; instalar `@electric-sql/pglite` en un directorio de pruebas y definir
`PGLITE_MODULE` con su ruta absoluta. Ejecutar `python tests/test_multicourse.py`. No usa registros ni servicios reales.

## Documentación anterior (flujo v1, sustituido para sincronización)

# Senda - Moodle → PostgreSQL → WhatsApp

Aplicación de escritorio para cargar el fichero de alta de Moodle (CSV/XLSX), normalizar los datos, insertar las matrículas en `public.course_access` y enviar la plantilla de WhatsApp de forma masiva.

## Qué hace

- Lee CSV separados por `;` o `,`, incluidos CSV Windows/Excel en CP1252, y XLSX.
- Comprueba las columnas del fichero Moodle.
- Limpia espacios de nombres y teléfonos.
- Guarda en PostgreSQL el teléfono nacional español sin `34`, compatible con el flujo n8n actual.
- Para la API de WhatsApp añade automáticamente `34` cuando corresponde.
- Convierte fechas `DD/MM/YYYY` a fecha PostgreSQL.
- Estandariza nombres de curso según `COURSE_MAP`.
- Evita repetir exactamente la misma matrícula (mismo username + curso + fechas), pero permite que un teléfono/persona tenga varios cursos.
- Envía la plantilla `confirmacion_cursos` con 7 parámetros: nombre, curso, empresa, inicio, fin, horas y URL.
- Exporta un log CSV con enviados, errores y registros ya existentes.

## Cursos estandarizados incluidos

- `GEM-SENSI-344` → `Sensibilización en Igualdad` (5 h)
- `GEM-SENSI-376` → `Sensibilización en Igualdad` (5 h)
- `PRL-PREVEMEPAUX-372` → `PRL, Evacuación, Emergencia y Primeros Auxilios` (15 h)
- `PRL-TBAS-319` → `Técnico Básico en Prevención de Riesgos Laborales` (50 h)

La tabla está en `course_catalog.py` y se comparte con la API del VPS. Los cursos nuevos deben añadirse ahí antes de importarlos, para impedir variantes de nombres en PostgreSQL. Las horas sí pueden ajustarse desde la aplicación de escritorio antes del envío.

## Uso rápido

1. Instala Python 3.11+ en Windows si aún no está instalado.
2. Ejecuta `instalar_y_abrir.bat` la primera vez.
3. Selecciona el CSV/XLSX de Moodle.
4. Revisa los avisos de validación.
5. Pega la URL externa de PostgreSQL que proporciona EasyPanel, por ejemplo `postgresql://usuario:password@host:puerto/basedatos`.
6. Pulsa `Probar conexión PostgreSQL`.
7. Pulsa `Subir alumnos a PostgreSQL`.
8. Pega el token de WhatsApp y comprueba el Phone Number ID.
9. Pulsa `Enviar WhatsApp masivo`. La app pide confirmación antes de enviar.

## Crear un .exe

Ejecuta `crear_exe.bat`. El ejecutable quedará en:

`dist\Senda_Moodle_WhatsApp.exe`

De esta forma podrás usar posteriormente la aplicación sin abrir PowerShell ni ejecutar `app.py` manualmente.

## Seguridad

La aplicación no guarda el token de WhatsApp ni la URL de PostgreSQL en archivos. Puedes introducirlos cada vez o definir las variables de entorno:

- `SENDA_POSTGRES_URL`
- `SENDA_WHATSAPP_TOKEN`
- `SENDA_WHATSAPP_PHONE_ID`

No compartas el `.exe` con credenciales incrustadas.

## API para Moodle en Dinahosting

`api_service.py` permite que el plugin Moodle sincronice y consulte `course_access` por HTTPS sin abrir PostgreSQL al hosting compartido.

Variables de entorno necesarias en el VPS:

- `SENDA_POSTGRES_URL`: URL interna de PostgreSQL. Debe utilizar el hostname privado del servicio dentro del VPS.
- `SENDA_INTEGRATION_TOKEN`: secreto largo y aleatorio compartido únicamente con el plugin Moodle.

Despliegue con EasyPanel/Docker:

1. Crear una aplicación desde este repositorio.
2. EasyPanel detectará el `Dockerfile` incluido. `Dockerfile.api` contiene la misma definición como referencia explícita.
3. Configurar las dos variables de entorno.
4. Exponer el puerto interno `8000` mediante un dominio con HTTPS.
5. Configurar en Moodle la URL pública, sin barra final, y el mismo token.

Endpoints:

- `GET /health`: comprueba que el servicio y PostgreSQL responden.
- `GET /v1/health`: comprobación autenticada utilizada por Moodle.
- `POST /v1/course-access/upsert`: inserta o actualiza una matrícula.
- `POST /v1/course-access/lookup`: recupera la matrícula que necesita el envío.

PostgreSQL no necesita publicar el puerto `5432` a Internet. El usuario usado por la API solo necesita `SELECT`, `INSERT` y `UPDATE` sobre `public.course_access`.
