import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import xlrd
import xlwt
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    BienAlta, CentroCosto, CorreccionAsignacionBien, Expediente, Pecosa,
    LoteCarga, Persona, RelacionPecosaItem, VerificacionPecosaSiga,
    ObservacionControlPecosa,
)
from app.routers.carga_inicial import _estado_maestros
from app.routers.control import (
    ESTADO_EXCESO, ESTADO_OBSERVADA, ESTADO_PENDIENTE_ALMACEN,
    _calcular_control, _mover_bien_a_pecosa,
)
from app.routers.normalizacion import _regularizar_bienes_historicos, _resumen_lote
from app.services.excel_relacion_pecosas import COLUMNAS_NECESARIAS, leer_relacion_pecosas
from app.services.excel_onevision import ENCABEZADOS, generar_formato_importacion
from app.services.excel_verificacion import leer_reporte_verificacion
from app.routers.verificacion import (
    ESTADO_CORRECTA, ESTADO_INCORRECTA, _filas_verificacion,
)


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
        lote = LoteCarga(id=14, anio="2026", ejecutora="785", pecosas_solicitadas="2011")
        self.db.add(lote)
        self.origen = Pecosa(numero="2011", expediente_id=expediente_origen.id, estado="StickerGenerado")
        self.destino = Pecosa(numero="2473", expediente_id=expediente_destino.id)
        self.db.add_all([self.origen, self.destino])
        self.db.flush()
        self.bien_corregido = BienAlta(
            pecosa_id=self.origen.id,
            lote_id=14,
            codigo_patrimonial="536498312255",
            descripcion="TERMO PARA TRANSPORTE DE BIOLOGICOS Y VACUNAS",
            codigo_qr="695614",
        )
        self.db.add_all([
            BienAlta(
                pecosa_id=self.origen.id,
                lote_id=14,
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
        self.assertEqual(control_inicial["2011"]["lotes"], [14])

        _mover_bien_a_pecosa(
            self.db, self.bien_corregido, self.destino,
            "SIGA MP corrigió la pecosa asignada al bien.",
        )
        self.db.commit()

        self.assertEqual(self.bien_corregido.pecosa_id, self.destino.id)
        self.assertEqual(self.destino.estado, "StickerGenerado")
        historial = self.db.query(CorreccionAsignacionBien).one()
        self.assertEqual(historial.pecosa_origen_id, self.origen.id)
        self.assertEqual(historial.pecosa_destino_id, self.destino.id)
        self.assertEqual(historial.motivo, "SIGA MP corrigió la pecosa asignada al bien.")
        self.assertIn("2473", self.db.query(LoteCarga).get(14).pecosas_solicitadas.split(","))

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


class FormatoImportacionOneVisionTest(unittest.TestCase):
    def test_generar_archivo_con_qr_y_formato_vigente(self):
        bien = SimpleNamespace(
            codigo_qr="QR-001",
            codigo_patrimonial="740899502020",
            descripcion="UNIDAD CENTRAL",
            fecha_alta=date(2026, 6, 22),
            modelo="M90",
            marca="LENOVO",
            estado_conservacion="Bueno",
            nro_serie="SN001",
            pecosa=SimpleNamespace(numero="1417"),
            centro_costo=SimpleNamespace(ipress="4451"),
            persona=SimpleNamespace(dni="44797419"),
        )
        descriptor, ruta = tempfile.mkstemp(suffix=".xls")
        os.close(descriptor)
        try:
            generar_formato_importacion([bien], "2026", "785", ruta)
            libro = xlrd.open_workbook(ruta, formatting_info=True)
            hoja = libro.sheet_by_index(0)
        finally:
            os.remove(ruta)

        self.assertEqual(hoja.ncols, 16)
        self.assertEqual(hoja.row_values(4), ENCABEZADOS)
        self.assertEqual(hoja.cell_value(7, 0), "QR-001")
        self.assertEqual(hoja.cell_value(7, 1), "2026")
        self.assertEqual(hoja.cell_value(7, 2), "785")
        self.assertEqual(hoja.cell_value(7, 5), "740899502020")
        self.assertEqual(hoja.cell_value(7, 12), "1417")
        self.assertNotEqual(
            libro.xf_list[hoja.cell_xf_index(4, 0)].background.pattern_colour_index,
            0,
        )


class VerificacionPecosasTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        expediente = Expediente(numero="50001")
        lote = LoteCarga(anio="2026", ejecutora="785", pecosas_solicitadas="2473")
        self.db.add_all([expediente, lote])
        self.db.flush()
        pecosa = Pecosa(numero="2473", expediente_id=expediente.id, estado="Firmada")
        self.db.add(pecosa)
        self.db.flush()
        self.db.add_all([
            BienAlta(
                pecosa_id=pecosa.id, lote_id=lote.id,
                codigo_patrimonial="740899502037", descripcion="BIEN DE PRUEBA",
            ),
            RelacionPecosaItem(nro_pecosa="2473", ano_eje="2026", cant_aprobada=1),
            VerificacionPecosaSiga(
                codigo_patrimonial="740899502037", nro_pecosa="2473", anio_siga="2026",
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_verifica_pecosa_y_anio_en_columnas_independientes(self):
        fila = _filas_verificacion(self.db)[0]
        self.assertEqual(fila["estado"], ESTADO_CORRECTA)
        self.assertEqual(fila["anio_lote"], "2026")
        self.assertEqual(fila["anio_siga"], "2026")
        self.assertEqual(fila["pecosa_alta"], "2473")
        self.assertEqual(fila["pecosa_real"], "2473")

        registro = self.db.query(VerificacionPecosaSiga).one()
        registro.nro_pecosa = "2474"
        self.db.commit()
        self.assertEqual(_filas_verificacion(self.db)[0]["estado"], ESTADO_INCORRECTA)

    def test_lee_reporte_xls_con_anio_separado(self):
        libro = xlwt.Workbook()
        hoja = libro.add_sheet("SIGA")
        for columna, valor in enumerate(["codigo_patrimonial", "nro_pecosa", "fecha_alta"]):
            hoja.write(0, columna, valor)
        hoja.write(1, 0, "740899502037")
        hoja.write(1, 1, "2473")
        hoja.write(1, 2, "27/08/2026 00:00:00")
        descriptor, ruta = tempfile.mkstemp(suffix=".xls")
        os.close(descriptor)
        try:
            libro.save(ruta)
            reporte = leer_reporte_verificacion(ruta)
        finally:
            os.remove(ruta)

        self.assertEqual(reporte.iloc[0]["codigo_patrimonial"], "740899502037")
        self.assertEqual(reporte.iloc[0]["nro_pecosa"], "2473")
        self.assertEqual(reporte.iloc[0]["anio_siga"], "2026")


class ObservacionControlPecosaTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(RelacionPecosaItem(
            nro_pecosa="36", ano_eje="2026", cant_aprobada=1,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_observacion_excluye_pendiente_por_anio_y_pecosa(self):
        self.assertEqual(_calcular_control(self.db)[0]["estado"], ESTADO_PENDIENTE_ALMACEN)
        self.db.add(ObservacionControlPecosa(
            ano_eje="2026", nro_pecosa="36",
            causal="Transferencia a otra RIS/unidad ejecutora",
            sustento="La RIS maneja su propio SIGA.",
        ))
        self.db.commit()

        fila = _calcular_control(self.db)[0]
        self.assertEqual(fila["estado"], ESTADO_OBSERVADA)
        self.assertEqual(fila["observacion"].sustento, "La RIS maneja su propio SIGA.")


class RegularizacionCargaInicialTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        self.persona = Persona(nombre_completo="RESPONSABLE SIGA", dni="12345678")
        self.centro = CentroCosto(nombre_depend="CENTRO SIGA", ipress="4567")
        expediente = Expediente(numero="41724")
        lote_historico = LoteCarga(anio="", ejecutora="", pecosas_solicitadas="2011")
        lote_normal = LoteCarga(anio="2026", ejecutora="785", pecosas_solicitadas="2473")
        self.db.add_all([self.persona, self.centro, expediente, lote_historico, lote_normal])
        self.db.flush()
        pecosa = Pecosa(numero="2011", expediente_id=expediente.id, estado="StickerGenerado")
        self.db.add(pecosa)
        self.db.flush()
        self.bien_historico = BienAlta(
            pecosa_id=pecosa.id, lote_id=lote_historico.id,
            codigo_patrimonial="602287628807", descripcion="BIEN HISTORICO",
        )
        self.bien_no_encontrado = BienAlta(
            pecosa_id=pecosa.id, lote_id=lote_historico.id,
            codigo_patrimonial="602287628808", descripcion="BIEN SIN FILA",
        )
        self.bien_normal = BienAlta(
            pecosa_id=pecosa.id, lote_id=lote_normal.id,
            codigo_patrimonial="602287628809", descripcion="BIEN NORMAL",
        )
        self.db.add_all([self.bien_historico, self.bien_no_encontrado, self.bien_normal])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_regulariza_todos_los_lotes_historicos_por_codigo_patrimonial(self):
        reporte = pd.DataFrame([{
            "codigo_patrimonial": "602287628807",
            "ano_eje": "2026",
            "sec_ejec": "785",
            "nombre_completo": "RESPONSABLE SIGA",
            "nombre_depend": "CENTRO SIGA",
            "fecha_movimto": "2026-09-02",
            "estado_conserv": "1",
        }])

        resumen = _regularizar_bienes_historicos(self.db, reporte)
        self.db.commit()

        self.assertEqual(resumen["pendientes"], 2)
        self.assertEqual(resumen["actualizados"], 1)
        self.assertEqual(resumen["no_encontrados"], 1)
        self.assertEqual(self.bien_historico.nombre_completo_siga, "RESPONSABLE SIGA")
        self.assertEqual(self.bien_historico.nombre_depend_siga, "CENTRO SIGA")
        self.assertEqual(self.bien_historico.persona_id, self.persona.id)
        self.assertEqual(self.bien_historico.centro_costo_id, self.centro.id)
        self.assertEqual(self.bien_historico.lote.anio, "2026")
        self.assertEqual(self.bien_historico.lote.ejecutora, "785")
        self.assertEqual(resumen["lotes_actualizados"], 1)
        self.assertIsNone(self.bien_normal.nombre_completo_siga)
        self.assertEqual(_resumen_lote(self.db, self.bien_historico.lote)["estado"], "Incompleto")


if __name__ == "__main__":
    unittest.main()
