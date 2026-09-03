"""
Tablas de la base de datos.
Cada clase de aquí es una tabla. Sigue el modelo de datos que definimos:

Expediente 1—N Pecosa 1—N BienAlta
Persona y CentroCosto son maestros (catálogos) que se cruzan contra BienAlta.
LoteCarga agrupa un envío de normalización/carga a One Visión.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, ForeignKey, Text, UniqueConstraint
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
    pecosa_id = Column(Integer, ForeignKey("pecosas.id"), nullable=False)
    lote_id = Column(Integer, ForeignKey("lotes_carga.id"), nullable=True)

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
