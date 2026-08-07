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
