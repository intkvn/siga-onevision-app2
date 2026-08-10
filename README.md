# SIGA MP → One Visión — App de normalización y control de pecosas

App para tu proceso de altas de bienes muebles: control de pecosas, normalización
de datos de SIGA al formato de One Visión, y cruce del reporte de códigos QR para
la impresión de stickers.

## Estructura del proyecto

```
app/
  main.py            → arranque de la aplicación
  config.py          → configuración (variables de entorno)
  database.py        → conexión a la base de datos
  models.py          → tablas (Persona, CentroCosto, Expediente, Pecosa, BienAlta, LoteCarga)
  auth.py            → login de un solo usuario
  routers/           → las páginas y acciones de cada módulo
    pecosas.py        → Módulo A: control de pecosas
    maestros.py       → Módulo C: personas y centros de costo
    normalizacion.py  → Módulo B: normalización y generación del .xls
    impresion.py      → Módulo D: cruce del reporte QR y hoja de impresión
  services/          → la lógica de lectura/cruce/generación de Excel
  templates/         → las páginas HTML
sql/
  vista_bartender.sql → vista de solo lectura para conectar BarTender directo
GUIA_DESPLIEGUE.md   → guía paso a paso para publicar la app gratis (Railway)
```

## Cómo empezar

Sigue la guía **GUIA_DESPLIEGUE.md** — está pensada para alguien sin experiencia
previa en programación, paso a paso, con capturas de lo que deberías ver.

## Para quien sepa programar (uso local, opcional)

```bash
python -m venv .venv
source .venv/bin/activate  # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # y edita los valores
uvicorn app.main:app --reload
```
