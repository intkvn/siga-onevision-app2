import os
import tempfile
import unittest
from unittest.mock import patch

import xlwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CentroCosto, Persona
from app.routers.carga_inicial import _estado_maestros
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
