import os
import tempfile
import unittest
from unittest.mock import patch

import xlwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    BienAlta, CentroCosto, CorreccionAsignacionBien, Expediente, Pecosa,
    Persona, RelacionPecosaItem,
)
from app.routers.carga_inicial import _estado_maestros
from app.routers.control import ESTADO_EXCESO, _calcular_control, _mover_bien_a_pecosa
from app.services.excel_relacion_pecosas import COLUMNAS_NECESARIAS, leer_relacion_pecosas


class ValidacionCargaInicialTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_exige_personas_y_centros_de_costo(self):
        self.assertFalse(_estado_maestros(self.db)["maestros_listos"])

        self.db.add(Persona(nombre_completo="PERSONA DE PRUEBA", dni="12345678"))
        self.db.commit()
        self.assertFalse(_estado_maestros(self.db)["maestros_listos"])

        self.db.add(CentroCosto(nombre_depend="CENTRO DE PRUEBA", ipress="001"))
        self.db.commit()
        self.assertTrue(_estado_maestros(self.db)["maestros_listos"])


class CorreccionPecosaTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        expediente_origen = Expediente(numero="41724")
        expediente_destino = Expediente(numero="43613")
        self.db.add_all([expediente_origen, expediente_destino])
        self.db.flush()
        self.origen = Pecosa(numero="2011", expediente_id=expediente_origen.id, estado="StickerGenerado")
        self.destino = Pecosa(numero="2473", expediente_id=expediente_destino.id)
        self.db.add_all([self.origen, self.destino])
        self.db.flush()
        self.bien_corregido = BienAlta(
            pecosa_id=self.origen.id,
            codigo_patrimonial="536498312255",
            descripcion="TERMO PARA TRANSPORTE DE BIOLOGICOS Y VACUNAS",
            codigo_qr="695614",
        )
        self.db.add_all([
            BienAlta(
                pecosa_id=self.origen.id,
                codigo_patrimonial="536498312210",
                descripcion="TERMO PARA TRANSPORTE DE BIOLOGICOS Y VACUNAS",
                codigo_qr="695613",
            ),
            self.bien_corregido,
            RelacionPecosaItem(nro_pecosa="2011", cant_aprobada=1),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_detecta_exceso_y_guarda_historial_al_reasignar(self):
        control_inicial = {fila["nro_pecosa"]: fila for fila in _calcular_control(self.db)}
        self.assertEqual(control_inicial["2011"]["estado"], ESTADO_EXCESO)
        self.assertEqual(control_inicial["2011"]["cantidad_ingresada"], 2)

        _mover_bien_a_pecosa(
            self.db, self.bien_corregido, self.destino,
            "SIGA MP corrigió la pecosa asignada al bien.",
        )
        self.db.commit()

        self.assertEqual(self.bien_corregido.pecosa_id, self.destino.id)
        historial = self.db.query(CorreccionAsignacionBien).one()
        self.assertEqual(historial.pecosa_origen_id, self.origen.id)
        self.assertEqual(historial.pecosa_destino_id, self.destino.id)
        self.assertEqual(historial.motivo, "SIGA MP corrigió la pecosa asignada al bien.")

        control_final = {fila["nro_pecosa"]: fila for fila in _calcular_control(self.db)}
        self.assertEqual(control_final["2011"]["cantidad_ingresada"], 1)
        self.assertNotEqual(control_final["2011"]["estado"], ESTADO_EXCESO)


class LecturaRelacionPecosasXlsTest(unittest.TestCase):
    @patch("app.services.excel_relacion_pecosas.pd.read_excel")
    def test_selecciona_xlrd_explicitamente_para_xls(self, leer_excel):
        leer_excel.return_value.columns = COLUMNAS_NECESARIAS

        leer_relacion_pecosas("reporte_siga.xls")

        leer_excel.assert_called_once_with("reporte_siga.xls", engine="xlrd")

    def test_lee_archivo_xls_de_siga(self):
        libro = xlwt.Workbook()
        hoja = libro.add_sheet("Relación")
        for columna, encabezado in enumerate(COLUMNAS_NECESARIAS):
            hoja.write(0, columna, encabezado)
            hoja.write(1, columna, 1 if encabezado == "cant_aprobada" else "DATO")

        descriptor, ruta = tempfile.mkstemp(suffix=".xls")
        os.close(descriptor)
        try:
            libro.save(ruta)
            resultado = leer_relacion_pecosas(ruta)
        finally:
            os.remove(ruta)

        self.assertEqual(list(resultado.columns), COLUMNAS_NECESARIAS)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]["cant_aprobada"], 1)


if __name__ == "__main__":
    unittest.main()
