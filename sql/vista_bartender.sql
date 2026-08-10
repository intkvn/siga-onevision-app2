-- Vista de solo lectura para que BarTender imprima directo desde la base de datos,
-- sin pasos manuales de exportación.
--
-- Cómo usarla:
-- 1. Ejecuta este SQL una vez en tu base de Railway (pestaña "Query" del servicio Postgres).
-- 2. Crea un usuario de solo lectura limitado a esta vista (ver más abajo).
-- 3. En la PC de BarTender, instala el driver ODBC de PostgreSQL y crea una conexión
--    usando ese usuario, el host y el puerto públicos que te da Railway.
-- 4. En BarTender: Database Connection Setup -> ODBC -> selecciona esta vista
--    (vw_lote_impresion) y filtra por lote_id según el lote que estés imprimiendo.

CREATE OR REPLACE VIEW vw_lote_impresion AS
SELECT
    b.lote_id,
    b.codigo_patrimonial,
    b.codigo_qr,
    b.ruta_qr,
    b.descripcion AS bien,
    cc.nombre_depend AS establecimiento,
    b.marca,
    b.modelo,
    b.nro_serie,
    p.numero AS numero_pecosa,
    e.numero AS numero_expediente
FROM bienes_alta b
LEFT JOIN centros_costo cc ON cc.id = b.centro_costo_id
LEFT JOIN pecosas p ON p.id = b.pecosa_id
LEFT JOIN expedientes e ON e.id = p.expediente_id
WHERE b.codigo_qr IS NOT NULL;

-- Usuario de solo lectura, limitado a esta vista (ajusta la contraseña):
-- CREATE USER bartender_reader WITH PASSWORD 'pon-aqui-una-clave-fuerte';
-- GRANT CONNECT ON DATABASE railway TO bartender_reader;
-- GRANT SELECT ON vw_lote_impresion TO bartender_reader;
