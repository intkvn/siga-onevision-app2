"""
Tablas de la base de datos.
Cada clase de aquí es una tabla. Sigue el modelo de datos que definimos:

Expediente 1—N Pecosa 1—N BienAlta
Persona y CentroCosto son maestros (catálogos) que se cruzan contra BienAlta.
LoteCarga agrupa un envío de normalización/carga a One Visión.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Float, ForeignKey, Index, Text,
    UniqueConstraint, Numeric, LargeBinary,
)
from sqlalchemy.orm import relationship
from app.database import Base


class Persona(Base):
    """Maestro de responsables. Se cruza por NOMBRE COMPLETO para obtener el DNI."""
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True)
    nombre_completo = Column(String(200), unique=True, nullable=False, index=True)
    dni = Column(String(15), nullable=False)


class CentroCosto(Base):
    """Maestro de centros de costo. Se cruza por nombre_depend para obtener el IPRESS."""
    __tablename__ = "centros_costo"

    id = Column(Integer, primary_key=True)
    nombre_depend = Column(String(200), unique=True, nullable=False, index=True)
    ipress = Column(String(20), nullable=False)  # ID de centro de costo en One Visión


class Expediente(Base):
    """El oficio con el que almacén remite una o varias pecosas."""
    __tablename__ = "expedientes"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50), unique=True, nullable=False, index=True)
    fecha_recepcion = Column(Date, nullable=True)

    pecosas = relationship("Pecosa", back_populates="expediente")


class Pecosa(Base):
    """Cada pecosa remitida por almacén. El número de pecosa es único —
    esto es lo que evita el doble ingreso."""
    __tablename__ = "pecosas"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50), unique=True, nullable=False, index=True)
    expediente_id = Column(Integer, ForeignKey("expedientes.id"), nullable=False)
    fecha_recepcion = Column(Date, nullable=True)

    # Recibida -> IngresadaSIGA -> Normalizada -> CargadaOneVision -> StickerGenerado -> Firmada
    estado = Column(String(30), nullable=False, default="Recibida")

    firmante = Column(String(200), nullable=True)
    fecha_firma = Column(Date, nullable=True)
    expediente_firma = Column(String(50), nullable=True)  # N° de expediente con el que almacén devuelve la pecosa firmada

    creado_en = Column(DateTime, default=datetime.utcnow)

    expediente = relationship("Expediente", back_populates="pecosas")
    bienes = relationship("BienAlta", back_populates="pecosa")


class LoteCarga(Base):
    """Un lote = una corrida de normalización/carga (puede agrupar
    varios expedientes/pecosas, como en tu ejemplo de 3 expedientes)."""
    __tablename__ = "lotes_carga"

    id = Column(Integer, primary_key=True)
    fecha = Column(DateTime, default=datetime.utcnow)
    anio = Column(String(4), nullable=False)
    ejecutora = Column(String(10), nullable=False)
    archivo_generado = Column(String(300), nullable=True)
    pecosas_solicitadas = Column(Text, nullable=True)  # CSV de números de pecosa elegidos al procesar

    bienes = relationship("BienAlta", back_populates="lote")


class PerfilImpresionEtiqueta(Base):
    """Configuración persistente para el PDF de etiquetas de la impresora."""
    __tablename__ = "perfiles_impresion_etiquetas"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), unique=True, nullable=False)
    ancho_pagina_mm = Column(Float, nullable=False, default=105.1)
    ancho_etiqueta_mm = Column(Float, nullable=False, default=50.8)
    alto_etiqueta_mm = Column(Float, nullable=False, default=38.1)
    margen_izquierdo_mm = Column(Float, nullable=False, default=0.75)
    margen_derecho_mm = Column(Float, nullable=False, default=0.75)
    separacion_central_mm = Column(Float, nullable=False, default=2.0)
    avance_adicional_mm = Column(Float, nullable=False, default=0.0)
    desplazamiento_x_mm = Column(Float, nullable=False, default=0.0)
    desplazamiento_y_mm = Column(Float, nullable=False, default=0.0)
    rotacion_contenido = Column(Integer, nullable=False, default=180)
    anio_1 = Column(String(4), nullable=False, default="2026")
    anio_2 = Column(String(4), nullable=False, default="2027")
    anio_marcado = Column(String(4), nullable=False, default="2026")


class UsuarioAplicacion(Base):
    """Usuario interno con acceso según su rol dentro de la aplicación."""
    __tablename__ = "usuarios_aplicacion"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    nombre_completo = Column(String(200), nullable=False)
    password_hash = Column(String(255), nullable=False)
    rol = Column(String(30), nullable=False, default="Inventariador", index=True)
    activo = Column(Integer, nullable=False, default=1, index=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    actualizado_en = Column(DateTime, default=datetime.utcnow, nullable=False)

    solicitudes_impresion = relationship(
        "SolicitudImpresionInventario", back_populates="usuario"
    )


class InventarioImpresion(Base):
    """Campaña anual que contiene el universo de bienes a etiquetar."""
    __tablename__ = "inventarios_impresion"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    anio = Column(String(4), nullable=False, index=True)
    unidad_ejecutora = Column(String(100), nullable=False, default="DIRESA")
    archivo_ultimo = Column(String(300), nullable=True)
    total_registros = Column(Integer, nullable=False, default=0)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    actualizado_en = Column(DateTime, default=datetime.utcnow, nullable=False)

    bienes = relationship(
        "BienInventarioImpresion", back_populates="inventario",
        cascade="all, delete-orphan",
    )
    lotes = relationship(
        "LoteImpresionInventario", back_populates="inventario",
        cascade="all, delete-orphan",
    )
    solicitudes = relationship(
        "SolicitudImpresionInventario", back_populates="inventario",
        cascade="all, delete-orphan",
    )
    cargas_reportes = relationship(
        "CargaInventarioImpresion", back_populates="inventario",
        cascade="all, delete-orphan",
    )


class CargaInventarioImpresion(Base):
    """Resultado persistente de una importación del reporte de impresión."""
    __tablename__ = "cargas_inventario_impresion"

    id = Column(Integer, primary_key=True)
    inventario_id = Column(
        Integer, ForeignKey("inventarios_impresion.id"), nullable=False, index=True,
    )
    archivo = Column(String(300), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    filas_procesadas = Column(Integer, nullable=False, default=0)
    nuevos = Column(Integer, nullable=False, default=0)
    actualizados = Column(Integer, nullable=False, default=0)
    sin_cambios = Column(Integer, nullable=False, default=0)
    activos_fijos = Column(Integer, nullable=False, default=0)
    sobrantes = Column(Integer, nullable=False, default=0)
    duplicados = Column(Integer, nullable=False, default=0)
    omitidos = Column(Integer, nullable=False, default=0)
    total_universo = Column(Integer, nullable=False, default=0)
    activos_fijos_universo = Column(Integer, nullable=False, default=0)
    sobrantes_universo = Column(Integer, nullable=False, default=0)

    inventario = relationship(
        "InventarioImpresion", back_populates="cargas_reportes"
    )


class BienInventarioImpresion(Base):
    """Bien del reporte general de One Vision para una campaña anual."""
    __tablename__ = "bienes_inventario_impresion"
    __table_args__ = (
        UniqueConstraint(
            "inventario_id", "codigo_patrimonial",
            name="uq_bien_inventario_codigo",
        ),
        Index(
            "ix_bien_inventario_estado",
            "inventario_id", "activo", "estado_impresion",
        ),
        Index(
            "ix_bien_inventario_red",
            "inventario_id", "activo", "red",
        ),
        Index(
            "ix_bien_inventario_establecimiento",
            "inventario_id", "activo", "establecimiento",
        ),
        Index(
            "ix_bien_inventario_area",
            "inventario_id", "activo", "area",
        ),
    )

    id = Column(Integer, primary_key=True)
    inventario_id = Column(
        Integer, ForeignKey("inventarios_impresion.id"), nullable=False, index=True,
    )
    bien_alta_id = Column(Integer, ForeignKey("bienes_alta.id"), nullable=True, index=True)
    codigo_patrimonial = Column(String(30), nullable=True, index=True)
    codigo_qr = Column(String(50), nullable=True, index=True)
    tipo_bien = Column(
        String(30), nullable=False, default="Activo fijo", index=True,
    )
    ruta_qr = Column(String(500), nullable=True)
    descripcion = Column(String(500), nullable=False)
    establecimiento = Column(String(300), nullable=True, index=True)
    red = Column(String(250), nullable=True, index=True)
    area = Column(String(300), nullable=True, index=True)
    marca = Column(String(150), nullable=True)
    modelo = Column(String(200), nullable=True)
    color = Column(String(100), nullable=True)
    nro_serie = Column(String(150), nullable=True)
    activo = Column(Integer, nullable=False, default=1, index=True)
    imprimible = Column(Integer, nullable=False, default=1, index=True)
    motivo_bloqueo = Column(String(300), nullable=True)
    estado_impresion = Column(
        String(30), nullable=False, default="Pendiente", index=True,
    )
    sticker_generado_en = Column(DateTime, nullable=True)
    impreso_en = Column(DateTime, nullable=True, index=True)
    relacion_alta = Column(String(30), nullable=False, default="Sin alta")
    importado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    actualizado_en = Column(DateTime, default=datetime.utcnow, nullable=False)

    inventario = relationship("InventarioImpresion", back_populates="bienes")
    bien_alta = relationship("BienAlta")
    items_impresion = relationship(
        "ItemLoteImpresionInventario", back_populates="bien",
        cascade="all, delete-orphan",
    )


class LoteImpresionInventario(Base):
    """Selección congelada de bienes de inventario para una impresión."""
    __tablename__ = "lotes_impresion_inventario"

    id = Column(Integer, primary_key=True)
    inventario_id = Column(
        Integer, ForeignKey("inventarios_impresion.id"), nullable=False, index=True,
    )
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    pdf_generado_en = Column(DateTime, nullable=True)
    estado = Column(String(30), nullable=False, default="Preparado", index=True)
    filtros = Column(Text, nullable=True)
    total_bienes = Column(Integer, nullable=False, default=0)

    inventario = relationship("InventarioImpresion", back_populates="lotes")
    items = relationship(
        "ItemLoteImpresionInventario", back_populates="lote",
        cascade="all, delete-orphan",
    )


class ItemLoteImpresionInventario(Base):
    """Bien incluido en un lote y confirmación de su impresión física."""
    __tablename__ = "items_lote_impresion_inventario"
    __table_args__ = (
        UniqueConstraint("lote_id", "bien_id", name="uq_lote_impresion_bien"),
    )

    id = Column(Integer, primary_key=True)
    lote_id = Column(
        Integer, ForeignKey("lotes_impresion_inventario.id"), nullable=False, index=True,
    )
    bien_id = Column(
        Integer, ForeignKey("bienes_inventario_impresion.id"), nullable=False, index=True,
    )
    solicitud_item_id = Column(
        Integer, ForeignKey("items_solicitud_impresion_inventario.id"),
        nullable=True, unique=True, index=True,
    )
    impreso_en = Column(DateTime, nullable=True, index=True)

    lote = relationship("LoteImpresionInventario", back_populates="items")
    bien = relationship("BienInventarioImpresion", back_populates="items_impresion")
    solicitud_item = relationship(
        "ItemSolicitudImpresionInventario", back_populates="item_lote"
    )


class SolicitudImpresionInventario(Base):
    """Envío de uno o varios QR realizado por un inventariador."""
    __tablename__ = "solicitudes_impresion_inventario"

    id = Column(Integer, primary_key=True)
    inventario_id = Column(
        Integer, ForeignKey("inventarios_impresion.id"), nullable=False, index=True,
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios_aplicacion.id"), nullable=False, index=True,
    )
    estado = Column(String(40), nullable=False, default="Pendiente", index=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    actualizado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    recogido_en = Column(DateTime, nullable=True)

    inventario = relationship("InventarioImpresion", back_populates="solicitudes")
    usuario = relationship("UsuarioAplicacion", back_populates="solicitudes_impresion")
    items = relationship(
        "ItemSolicitudImpresionInventario", back_populates="solicitud",
        cascade="all, delete-orphan",
    )


class ItemSolicitudImpresionInventario(Base):
    """QR validado u observado dentro de una solicitud del inventariador."""
    __tablename__ = "items_solicitud_impresion_inventario"
    __table_args__ = (
        UniqueConstraint(
            "solicitud_id", "codigo_qr", name="uq_solicitud_impresion_qr"
        ),
    )

    id = Column(Integer, primary_key=True)
    solicitud_id = Column(
        Integer, ForeignKey("solicitudes_impresion_inventario.id"),
        nullable=False, index=True,
    )
    bien_id = Column(
        Integer, ForeignKey("bienes_inventario_impresion.id"),
        nullable=True, index=True,
    )
    codigo_qr = Column(String(80), nullable=False, index=True)
    estado = Column(String(40), nullable=False, default="Pendiente", index=True)
    motivo_observacion = Column(String(300), nullable=True)
    es_reimpresion = Column(Integer, nullable=False, default=0)
    listo_recojo_en = Column(DateTime, nullable=True)
    recogido_en = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)

    solicitud = relationship("SolicitudImpresionInventario", back_populates="items")
    bien = relationship("BienInventarioImpresion")
    item_lote = relationship(
        "ItemLoteImpresionInventario", back_populates="solicitud_item",
        uselist=False,
    )


class RelacionPecosaItem(Base):
    """Una línea del reporte 'Relación de Pecosas' que se descarga de SIGA
    (cada pecosa puede tener varias líneas de ítems distintos). Se usa
    para saber cuántos bienes en total debería tener cada pecosa
    (sumando cant_aprobada) y así detectar ingresos incompletos.
    Se reemplaza por completo cada vez que se vuelve a importar el reporte."""
    __tablename__ = "relacion_pecosa_items"

    id = Column(Integer, primary_key=True)
    nro_pecosa = Column(String(50), nullable=False, index=True)
    ano_eje = Column(String(4), nullable=True)
    nombre_item = Column(String(300), nullable=True)
    nombre_depend = Column(String(250), nullable=True)
    precio_unit = Column(String(30), nullable=True)
    motivo_pedido = Column(String(500), nullable=True)
    fecha_pecosa = Column(String(30), nullable=True)
    clasificador = Column(String(50), nullable=True)
    cant_aprobada = Column(Integer, nullable=True)


class BienAlta(Base):
    """Cada bien mueble dado de alta, ya con los datos cruzados
    (DNI e IPRESS) listos para el Formato de Importación."""
    __tablename__ = "bienes_alta"

    id = Column(Integer, primary_key=True)
    pecosa_id = Column(Integer, ForeignKey("pecosas.id"), nullable=False, index=True)
    lote_id = Column(Integer, ForeignKey("lotes_carga.id"), nullable=True, index=True)

    codigo_patrimonial = Column(String(20), nullable=False, index=True)
    descripcion = Column(String(300), nullable=False)
    modelo = Column(String(150), nullable=True)
    marca = Column(String(100), nullable=True)
    estado_conservacion = Column(String(5), nullable=True)  # código 1-7
    nro_serie = Column(String(100), nullable=True)
    fecha_alta = Column(DateTime, nullable=True)

    # Valores tal como vinieron del reporte SIGA (para trazabilidad y
    # para poder corregir manualmente si el cruce falló)
    nombre_depend_siga = Column(String(250), nullable=True)
    nombre_completo_siga = Column(String(250), nullable=True)

    # Resultado del cruce (lo que de verdad exige el Formato de Importación)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=True)
    centro_costo_id = Column(Integer, ForeignKey("centros_costo.id"), nullable=True)

    # Se completan luego de la carga a One Visión (Módulo D)
    codigo_qr = Column(String(50), nullable=True)
    ruta_qr = Column(String(300), nullable=True)

    pecosa = relationship("Pecosa", back_populates="bienes")
    lote = relationship("LoteCarga", back_populates="bienes")
    persona = relationship("Persona")
    centro_costo = relationship("CentroCosto")


class VerificacionPecosaSiga(Base):
    """Último reporte patrimonial de SIGA usado para validar una pecosa.

    El año y el número de pecosa se conservan en columnas distintas. El año
    proviene de fecha_alta del reporte SIGA, por lo que el usuario no necesita
    ingresarlo al registrar una pecosa en la aplicación.
    """
    __tablename__ = "verificacion_pecosas_siga"

    id = Column(Integer, primary_key=True)
    codigo_patrimonial = Column(String(20), unique=True, nullable=False, index=True)
    nro_pecosa = Column(String(50), nullable=True, index=True)
    anio_siga = Column(String(4), nullable=True, index=True)
    importado_en = Column(DateTime, default=datetime.utcnow, nullable=False)


class ObservacionControlPecosa(Base):
    """Exclusión sustentada de una pecosa que no se procesará en SIGA DIRESA.

    Se identifica por año y número en campos separados. La pecosa no se crea
    en el flujo de normalización, porque una observación no es un registro de
    alta pendiente.
    """
    __tablename__ = "observaciones_control_pecosa"
    __table_args__ = (UniqueConstraint("ano_eje", "nro_pecosa", name="uq_observacion_control_pecosa"),)

    id = Column(Integer, primary_key=True)
    ano_eje = Column(String(4), nullable=False, index=True)
    nro_pecosa = Column(String(50), nullable=False, index=True)
    causal = Column(String(100), nullable=False)
    sustento = Column(Text, nullable=False)
    activa = Column(Integer, nullable=False, default=1)
    observada_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    restituida_en = Column(DateTime, nullable=True)


class CorreccionAsignacionBien(Base):
    """Historial de los traslados de un bien entre pecosas.

    Se conserva para que una corrección posterior no oculte el origen del
    bien ni el motivo documentado por Patrimonio.
    """
    __tablename__ = "correcciones_asignacion_bienes"

    id = Column(Integer, primary_key=True)
    bien_id = Column(Integer, ForeignKey("bienes_alta.id"), nullable=False, index=True)
    pecosa_origen_id = Column(Integer, ForeignKey("pecosas.id"), nullable=False)
    pecosa_destino_id = Column(Integer, ForeignKey("pecosas.id"), nullable=False)
    motivo = Column(String(500), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)

    bien = relationship("BienAlta")
    pecosa_origen = relationship("Pecosa", foreign_keys=[pecosa_origen_id])
    pecosa_destino = relationship("Pecosa", foreign_keys=[pecosa_destino_id])


class CargaPatrimonial(Base):
    """Carga validada del reporte Maestro Patrimonial emitido por SIGA."""
    __tablename__ = "cargas_patrimoniales"

    id = Column(Integer, primary_key=True)
    nombre_archivo = Column(String(300), nullable=False)
    huella_archivo = Column(String(64), nullable=False, index=True)
    usuario_carga = Column(String(100), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    confirmado_en = Column(DateTime, nullable=True)
    estado = Column(String(30), nullable=False, default="Validando", index=True)
    tipo_carga = Column(String(20), nullable=False, default="Completa", index=True)
    progreso = Column(Integer, nullable=False, default=0)
    mensaje_progreso = Column(String(300), nullable=True)
    archivo_contenido = Column(LargeBinary, nullable=True)
    total_filas = Column(Integer, nullable=False, default=0)
    filas_validas = Column(Integer, nullable=False, default=0)
    total_errores = Column(Integer, nullable=False, default=0)
    total_alertas = Column(Integer, nullable=False, default=0)
    total_nuevos = Column(Integer, nullable=False, default=0)
    total_actualizados = Column(Integer, nullable=False, default=0)
    total_sin_cambios = Column(Integer, nullable=False, default=0)
    total_no_incluidos = Column(Integer, nullable=False, default=0)
    detalle_validacion = Column(Text, nullable=True)
    detalle_alertas = Column(Text, nullable=True)

    filas = relationship(
        "BienCargaPatrimonial", back_populates="carga",
        cascade="all, delete-orphan",
    )
    versiones = relationship("VersionBienPatrimonial", back_populates="carga")


class ExportacionPatrimonial(Base):
    """Excel solicitado en segundo plano y disponible para descarga posterior."""
    __tablename__ = "exportaciones_patrimoniales"

    id = Column(Integer, primary_key=True)
    usuario = Column(String(100), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completado_en = Column(DateTime, nullable=True)
    estado = Column(String(30), nullable=False, default="Pendiente", index=True)
    progreso = Column(Integer, nullable=False, default=0)
    tipo_reporte = Column(String(30), nullable=False)
    columnas = Column(Text, nullable=False)
    filtros = Column(Text, nullable=False)
    total_filas = Column(Integer, nullable=False, default=0)
    nombre_archivo = Column(String(300), nullable=True)
    archivo_contenido = Column(LargeBinary, nullable=True)
    mensaje_error = Column(String(500), nullable=True)


class BienPatrimonial(Base):
    """Información vigente y última fuente SIGA de un bien patrimonial."""
    __tablename__ = "bienes_patrimoniales"
    __table_args__ = (
        Index("ix_bien_mp_dependencia", "nombre_dependencia"),
        Index("ix_bien_mp_usuario", "usuario"),
        Index("ix_bien_mp_ubicacion", "ubicacion_fisica"),
        Index("ix_bien_mp_descripcion", "descripcion"),
    )

    id = Column(Integer, primary_key=True)
    codigo_patrimonial = Column(String(50), unique=True, nullable=False, index=True)
    codigo_qr = Column(String(80), nullable=True, index=True)
    descripcion = Column(String(500), nullable=False)
    nombre_dependencia = Column(String(350), nullable=False)
    usuario = Column(String(300), nullable=False)
    fecha_compra = Column(Date, nullable=True)
    valor_compra = Column(Numeric(18, 4), nullable=False)
    fecha_alta = Column(Date, nullable=True)
    valor_inicial = Column(Numeric(18, 4), nullable=False)
    ubicacion_fisica = Column(String(350), nullable=False)
    modelo = Column(String(250), nullable=True)
    numero_orden = Column(String(100), nullable=True)
    medidas = Column(String(300), nullable=True)
    valor_neto = Column(Numeric(18, 4), nullable=False)
    numero_documento = Column(String(150), nullable=True)
    marca = Column(String(250), nullable=False)
    estado_conservacion = Column(String(100), nullable=False)
    fecha_nea = Column(Date, nullable=True)
    numero_serie = Column(String(250), nullable=True)
    color = Column(String(150), nullable=True)
    caracteristicas = Column(Text, nullable=True)
    observaciones = Column(Text, nullable=True)
    datos_importados = Column(Text, nullable=False)
    datos_fuente = Column(Text, nullable=False)
    ultima_carga_id = Column(
        Integer, ForeignKey("cargas_patrimoniales.id"), nullable=False, index=True,
    )
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    actualizado_en = Column(DateTime, default=datetime.utcnow, nullable=False)

    ultima_carga = relationship("CargaPatrimonial", foreign_keys=[ultima_carga_id])
    cargas = relationship("BienCargaPatrimonial", back_populates="bien")
    versiones = relationship(
        "VersionBienPatrimonial", back_populates="bien",
        cascade="all, delete-orphan",
    )
    correcciones = relationship(
        "CorreccionBienPatrimonial", back_populates="bien",
        cascade="all, delete-orphan",
    )
    conflictos = relationship(
        "ConflictoBienPatrimonial", back_populates="bien",
        cascade="all, delete-orphan",
    )


class BienCargaPatrimonial(Base):
    """Fila del Excel y clasificación obtenida dentro de una carga."""
    __tablename__ = "bienes_carga_patrimonial"
    __table_args__ = (
        UniqueConstraint("carga_id", "codigo_patrimonial", name="uq_carga_mp_codigo"),
        Index("ix_carga_mp_clasificacion", "carga_id", "clasificacion"),
    )

    id = Column(Integer, primary_key=True)
    carga_id = Column(
        Integer, ForeignKey("cargas_patrimoniales.id"), nullable=False, index=True,
    )
    bien_id = Column(Integer, ForeignKey("bienes_patrimoniales.id"), nullable=True, index=True)
    numero_fila = Column(Integer, nullable=True)
    codigo_patrimonial = Column(String(50), nullable=False, index=True)
    clasificacion = Column(String(30), nullable=False, index=True)
    datos_comparables = Column(Text, nullable=True)
    datos_fuente = Column(Text, nullable=True)

    carga = relationship("CargaPatrimonial", back_populates="filas")
    bien = relationship("BienPatrimonial", back_populates="cargas")


class VersionBienPatrimonial(Base):
    """Instantánea del bien creada por una carga o una edición manual."""
    __tablename__ = "versiones_bienes_patrimoniales"

    id = Column(Integer, primary_key=True)
    bien_id = Column(
        Integer, ForeignKey("bienes_patrimoniales.id"), nullable=False, index=True,
    )
    carga_id = Column(Integer, ForeignKey("cargas_patrimoniales.id"), nullable=True, index=True)
    origen = Column(String(30), nullable=False)
    usuario = Column(String(100), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    snapshot = Column(Text, nullable=False)

    bien = relationship("BienPatrimonial", back_populates="versiones")
    carga = relationship("CargaPatrimonial", back_populates="versiones")
    cambios = relationship(
        "CambioBienPatrimonial", back_populates="version",
        cascade="all, delete-orphan",
    )


class CambioBienPatrimonial(Base):
    """Diferencia de un campo dentro de una versión."""
    __tablename__ = "cambios_bienes_patrimoniales"

    id = Column(Integer, primary_key=True)
    version_id = Column(
        Integer, ForeignKey("versiones_bienes_patrimoniales.id"),
        nullable=False, index=True,
    )
    campo = Column(String(80), nullable=False)
    valor_anterior = Column(Text, nullable=True)
    valor_nuevo = Column(Text, nullable=True)

    version = relationship("VersionBienPatrimonial", back_populates="cambios")


class CorreccionBienPatrimonial(Base):
    """Valor manual vigente o histórico aplicado sobre un campo importado."""
    __tablename__ = "correcciones_bienes_patrimoniales"
    __table_args__ = (
        Index("ix_correccion_mp_activa", "bien_id", "campo", "activa"),
    )

    id = Column(Integer, primary_key=True)
    bien_id = Column(
        Integer, ForeignKey("bienes_patrimoniales.id"), nullable=False, index=True,
    )
    campo = Column(String(80), nullable=False)
    valor_anterior = Column(Text, nullable=True)
    valor_nuevo = Column(Text, nullable=True)
    motivo = Column(String(500), nullable=False)
    usuario = Column(String(100), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    activa = Column(Integer, nullable=False, default=1, index=True)
    cerrada_en = Column(DateTime, nullable=True)

    bien = relationship("BienPatrimonial", back_populates="correcciones")


class ConflictoBienPatrimonial(Base):
    """Cambio SIGA que contradice una corrección manual activa."""
    __tablename__ = "conflictos_bienes_patrimoniales"
    __table_args__ = (
        Index("ix_conflicto_mp_pendiente", "bien_id", "estado"),
    )

    id = Column(Integer, primary_key=True)
    bien_id = Column(
        Integer, ForeignKey("bienes_patrimoniales.id"), nullable=False, index=True,
    )
    carga_id = Column(
        Integer, ForeignKey("cargas_patrimoniales.id"), nullable=False, index=True,
    )
    correccion_id = Column(
        Integer, ForeignKey("correcciones_bienes_patrimoniales.id"), nullable=False,
    )
    campo = Column(String(80), nullable=False)
    valor_siga_anterior = Column(Text, nullable=True)
    valor_siga_nuevo = Column(Text, nullable=True)
    valor_manual = Column(Text, nullable=True)
    estado = Column(String(30), nullable=False, default="Pendiente", index=True)
    resuelto_por = Column(String(100), nullable=True)
    resuelto_en = Column(DateTime, nullable=True)

    bien = relationship("BienPatrimonial", back_populates="conflictos")
    carga = relationship("CargaPatrimonial")
    correccion = relationship("CorreccionBienPatrimonial")
