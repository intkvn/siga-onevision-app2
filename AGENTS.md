# Instrucciones para agentes

## Idioma y estilo

- Responde en español salvo que el usuario solicite otro idioma.
- No uses emojis salvo que el usuario los pida.
- No uses guiones largos.
- No presentes inferencias, especulaciones o información no comprobada como hechos.
- Si una afirmación no puede comprobarse, indícalo claramente.
- No reformules la entrada del usuario salvo que lo solicite.
- Si falta información que pueda cambiar materialmente el resultado, solicita aclaración.

## Contexto del proyecto

Consulta los documentos según la tarea:

- Usa `README.md` para alcance, instalación, variables y despliegue.
- Usa `ARCHITECTURE.md` para componentes, límites y decisiones de arquitectura.
- Usa `DATA_MODEL.md` para modelos, tablas, campos y relaciones.
- Usa `BUSINESS_RULES.md` para validaciones y flujos funcionales.
- Usa `REQUIREMENTS.md` para requerimientos acordados que todavía no han sido implementados.
- Usa `STATUS.md` para estado, problemas conocidos y backlog.

No asumas que la documentación refleja cambios externos recientes. Contrasta con el código, Git y el estado actual antes de actuar.

## Seguridad y producción

- No muestres ni copies secretos, contraseñas, cookies o cadenas de conexión.
- No agregues `.env`, `.env.production.local`, bases locales, reportes ni respaldos a Git.
- Usa `.env.production.local` únicamente cuando una tarea autorizada requiera producción.
- Antes de modificar producción, identifica exactamente el servicio, la base, la rama y la operación.
- Las consultas de diagnóstico deben ser de solo lectura.
- No borres, trunques, restaures ni modifiques datos productivos sin autorización explícita del usuario.
- Antes de una operación destructiva en producción, crea un respaldo completo y su checksum, salvo que el usuario indique expresamente otro procedimiento.
- No restaures un respaldo sobre producción sin autorización explícita.
- El despliegue productivo de Render es manual.
- No hagas commit, push ni despliegue sin una solicitud explícita.

## Flujo de trabajo

- Revisa primero `git status` y conserva cambios existentes del usuario.
- No uses comandos destructivos de Git.
- Implementa y prueba los cambios localmente antes de proponer producción.
- Limita cada cambio al alcance solicitado.
- Usa los patrones y servicios existentes antes de crear abstracciones nuevas.
- Cuando cambie una regla de negocio, actualiza sus pruebas y la documentación relacionada.
- Ejecuta las pruebas con `.venv/bin/python -m unittest discover -s tests -v`.
- Informa qué se cambió, qué se probó y qué no pudo verificarse.
- Para despliegues, informa el commit exacto que debe seleccionarse en Render.

## Base de datos y respaldos

- Desarrollo local usa SQLite salvo configuración explícita distinta.
- Producción usa PostgreSQL de Neon.
- Los respaldos de producción se guardan en `backups/production/` y están excluidos de Git.
- Un respaldo completo debe incluir el archivo `.dump` y su archivo `.sha256`.
- Comprueba el checksum y que `pg_restore` pueda leer el catálogo.
- Una restauración solo se considera probada después de restaurar en una base aislada y revisar tablas, cantidades y operaciones principales.

## Infraestructura confirmada

- Proyecto: `gestion-ovc-siga`.
- Producción: `https://gestion-ovc-siga.onrender.com`.
- Render: Ohio, US East.
- Despliegue: Manual Deploy.
- Neon: AWS US East 2, Ohio.
- PostgreSQL: versión 18.
- El Web Service anterior está suspendido.
