import os
import inspect
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import xlrd
import xlwt
import pandas as pd
from openpyxl import Workbook as OpenpyxlWorkbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, _opciones_engine
from app.models import (
    BienAlta, CentroCosto, CorreccionAsignacionBien, Expediente, Pecosa,
    LoteCarga, Persona, RelacionPecosaItem, VerificacionPecosaSiga,
    ObservacionControlPecosa,
)
from app.routers.carga_inicial import _estado_maestros
from app.routers.control import (
    ESTADO_COMPLETA, ESTADO_EXCESO, ESTADO_FALTA_FIRMA, ESTADO_OBSERVADA,
    ESTADO_PENDIENTE_ALMACEN,
    _calcular_control, _filtrar_filas_control, _mover_bien_a_pecosa,
)
from app.routers.normalizacion import (
    _completar_bienes_lote, _diferir_pecosa_faltante, _indicadores_cruce_lote,
    _pecosas_no_encontradas,
    _regularizar_bienes_historicos, _resumen_lote,
)
from app.routers.impresion import procesar_reporte_qr
from app.routers.pecosas import registrar_pecosas_multiples
from app.services.excel_relacion_pecosas import COLUMNAS_NECESARIAS, leer_relacion_pecosas
from app.services.excel_onevision import (
    ENCABEZADOS, generar_formato_importacion, iterar_reporte_qr_onevision,
)
from app.services.excel_verificacion import leer_reporte_verificacion
from app.services.lote_status import expedientes_de_lotes
from app.services.pagination import paginas_visibles, rango_registros
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


class ConfiguracionConexionTest(unittest.TestCase):
    def test_postgresql_verifica_y_recicla_conexiones(self):
        opciones = _opciones_engine("postgresql://usuario:clave@servidor/base")

        self.assertTrue(opciones["pool_pre_ping"])
        self.assertEqual(opciones["pool_recycle"], 240)

    def test_sqlite_conserva_su_configuracion_local(self):
        opciones = _opciones_engine("sqlite:///./local_dev.db")

        self.assertEqual(
            opciones,
            {"connect_args": {"check_same_thread": False}},
        )


class LecturaReporteQrTest(unittest.TestCase):
    def _guardar_libro(self, encabezados, filas):
        descriptor, ruta = tempfile.mkstemp(suffix=".xlsx")
        os.close(descriptor)
        libro = OpenpyxlWorkbook()
        hoja = libro.active
        hoja.append(encabezados)
        for fila in filas:
            hoja.append(fila)
        libro.save(ruta)
        libro.close()
        self.addCleanup(lambda: os.path.exists(ruta) and os.remove(ruta))
        return ruta

    def test_lee_progresivamente_solo_las_columnas_del_cruce(self):
        ruta = self._guardar_libro(
            ["Código Patrimonial", "Descripción", "Código QR", "Ruta QR"],
            [
                [" 740899502020", "BIEN 1", 696554, "https://qr/696554"],
                ["740899502021", "BIEN 2", None, None],
            ],
        )

        filas = list(iterar_reporte_qr_onevision(ruta))

        self.assertEqual(filas, [
            {
                "codigo_patrimonial_corregido": "740899502020",
                "codigo_qr": "696554",
                "ruta_qr": "https://qr/696554",
            },
            {
                "codigo_patrimonial_corregido": "740899502021",
                "codigo_qr": "",
                "ruta_qr": "",
            },
        ])

    def test_rechaza_reporte_sin_codigo_patrimonial(self):
        ruta = self._guardar_libro(
            ["Descripción", "Código QR"],
            [["BIEN 1", "696554"]],
        )

        with self.assertRaisesRegex(ValueError, "Código Patrimonial"):
            list(iterar_reporte_qr_onevision(ruta))

    def test_rechaza_reporte_sin_codigo_qr(self):
        ruta = self._guardar_libro(
            ["Código Patrimonial", "Descripción"],
            [["740899502020", "BIEN 1"]],
        )

        with self.assertRaisesRegex(ValueError, "Código QR"):
            list(iterar_reporte_qr_onevision(ruta))

    def test_el_cruce_no_bloquea_el_event_loop(self):
        self.assertFalse(inspect.iscoroutinefunction(procesar_reporte_qr))


class IndicadoresCruceLoteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_resume_total_y_bienes_por_expediente(self):
        expediente_1 = Expediente(numero="60144")
        expediente_2 = Expediente(numero="60150")
        persona = Persona(nombre_completo="PERSONA COMPLETA", dni="12345678")
        centro = CentroCosto(nombre_depend="CENTRO COMPLETO", ipress="10460")
        lote = LoteCarga(
            anio="2026", ejecutora="785", pecosas_solicitadas="4719,4720,4721",
        )
        self.db.add_all([expediente_1, expediente_2, persona, centro, lote])
        self.db.flush()

        pecosa_1 = Pecosa(numero="4719", expediente_id=expediente_1.id)
        pecosa_2 = Pecosa(numero="4720", expediente_id=expediente_1.id)
        pecosa_sin_bienes = Pecosa(numero="4721", expediente_id=expediente_2.id)
        self.db.add_all([pecosa_1, pecosa_2, pecosa_sin_bienes])
        self.db.flush()

        bienes = [
            BienAlta(
                pecosa_id=pecosa_1.id, lote_id=lote.id,
                codigo_patrimonial="740899502020", descripcion="BIEN COMPLETO 1",
                persona_id=persona.id, centro_costo_id=centro.id,
            ),
            BienAlta(
                pecosa_id=pecosa_1.id, lote_id=lote.id,
                codigo_patrimonial="740899502021", descripcion="BIEN PENDIENTE",
                centro_costo_id=centro.id,
            ),
            BienAlta(
                pecosa_id=pecosa_2.id, lote_id=lote.id,
                codigo_patrimonial="740899502022", descripcion="BIEN COMPLETO 2",
                persona_id=persona.id, centro_costo_id=centro.id,
            ),
        ]
        self.db.add_all(bienes)
        self.db.commit()

        resultado = _indicadores_cruce_lote(
            bienes, [pecosa_1, pecosa_2, pecosa_sin_bienes]
        )

        self.assertEqual(resultado["total"], 3)
        self.assertEqual(resultado["correctos"], 2)
        self.assertEqual(resultado["pendientes"], 1)
        self.assertEqual(resultado["por_expediente"], [
            {
                "expediente": "60144",
                "pecosas": ["4719", "4720"],
                "cantidad_pecosas": 2,
                "total": 3,
                "correctos": 2,
                "pendientes": 1,
            },
            {
                "expediente": "60150",
                "pecosas": ["4721"],
                "cantidad_pecosas": 1,
                "total": 0,
                "correctos": 0,
                "pendientes": 0,
            },
        ])


class PaginacionTest(unittest.TestCase):
    def test_muestra_todas_las_paginas_cuando_son_pocas(self):
        self.assertEqual(paginas_visibles(3, 5), [1, 2, 3, 4, 5])

    def test_compacta_paginas_intermedias_con_separadores(self):
        self.assertEqual(
            paginas_visibles(9, 17),
            [1, 2, None, 7, 8, 9, 10, 11, None, 16, 17],
        )

    def test_muestra_extremos_al_inicio_y_final(self):
        self.assertEqual(
            paginas_visibles(1, 17),
            [1, 2, 3, 4, 5, 6, 7, None, 16, 17],
        )
        self.assertEqual(
            paginas_visibles(17, 17),
            [1, 2, None, 11, 12, 13, 14, 15, 16, 17],
        )

    def test_calcula_rango_visible(self):
        self.assertEqual(rango_registros(2, 50, 123), (51, 100))
        self.assertEqual(rango_registros(3, 50, 123), (101, 123))
        self.assertEqual(rango_registros(1, 50, 0), (0, 0))


class FiltrosControlTest(unittest.TestCase):
    def setUp(self):
        self.filas = [
            {
                "nro_pecosa": "1200", "estado": ESTADO_COMPLETA,
                "lotes": [22], "expediente_alta": "31863",
                "expediente_firma": "52607",
            },
            {
                "nro_pecosa": "1212", "estado": ESTADO_FALTA_FIRMA,
                "lotes": [22], "expediente_alta": "31864",
                "expediente_firma": "52607",
            },
            {
                "nro_pecosa": "1227", "estado": ESTADO_COMPLETA,
                "lotes": [23], "expediente_alta": "31865",
                "expediente_firma": "53001",
            },
        ]

    def test_filtra_por_numero_parcial_de_expediente_firma(self):
        resultado = _filtrar_filas_control(
            self.filas, expediente_firma="526"
        )

        self.assertEqual(
            [fila["nro_pecosa"] for fila in resultado], ["1200", "1212"]
        )

    def test_combina_expediente_firma_con_estado_firmada(self):
        resultado = _filtrar_filas_control(
            self.filas,
            expediente_firma="52607",
            estado=ESTADO_COMPLETA,
        )

        self.assertEqual(
            [fila["nro_pecosa"] for fila in resultado], ["1200"]
        )


class RegistroMasivoPecosasTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_no_crea_expediente_si_todas_las_pecosas_ya_existen(self):
        expediente_original = Expediente(numero="50001")
        self.db.add(expediente_original)
        self.db.flush()
        self.db.add(Pecosa(numero="4602", expediente_id=expediente_original.id))
        self.db.commit()

        respuesta = registrar_pecosas_multiples(
            request=SimpleNamespace(),
            numero_expediente="123",
            numeros_pecosa="4602",
            db=self.db,
            _=None,
        )

        self.assertEqual(respuesta.status_code, 303)
        self.assertIn("error=", respuesta.headers["location"])
        self.assertIsNone(
            self.db.query(Expediente).filter(Expediente.numero == "123").first()
        )
        self.assertEqual(self.db.query(Pecosa).count(), 1)

    def test_agrega_solo_nuevas_a_un_expediente_existente(self):
        expediente = Expediente(numero="50002")
        self.db.add(expediente)
        self.db.flush()
        self.db.add(Pecosa(numero="100", expediente_id=expediente.id))
        self.db.commit()

        respuesta = registrar_pecosas_multiples(
            request=SimpleNamespace(),
            numero_expediente="50002",
            numeros_pecosa="100\n101\n101,102",
            db=self.db,
            _=None,
        )

        self.assertEqual(respuesta.status_code, 303)
        pecosas = self.db.query(Pecosa).order_by(Pecosa.numero).all()
        self.assertEqual([pecosa.numero for pecosa in pecosas], ["100", "101", "102"])
        self.assertTrue(all(pecosa.expediente_id == expediente.id for pecosa in pecosas))
        self.assertEqual(
            self.db.query(Expediente).filter(Expediente.numero == "50002").count(),
            1,
        )


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


class ExpedientesPorLotesTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        expediente_uno = Expediente(numero="40001")
        expediente_dos = Expediente(numero="40002")
        lote_uno = LoteCarga(anio="2026", ejecutora="785", pecosas_solicitadas="101,102")
        lote_dos = LoteCarga(anio="2026", ejecutora="785", pecosas_solicitadas="102,999")
        self.db.add_all([expediente_uno, expediente_dos, lote_uno, lote_dos])
        self.db.flush()
        self.db.add_all([
            Pecosa(numero="101", expediente_id=expediente_uno.id),
            Pecosa(numero="102", expediente_id=expediente_dos.id),
        ])
        self.db.commit()
        self.lote_uno = lote_uno
        self.lote_dos = lote_dos

    def tearDown(self):
        self.db.close()

    def test_agrupa_expedientes_para_varios_lotes(self):
        resultado = expedientes_de_lotes(self.db, [self.lote_uno, self.lote_dos])

        self.assertEqual(resultado[self.lote_uno.id], ["40001", "40002"])
        self.assertEqual(resultado[self.lote_dos.id], ["40002"])


class LotesParcialesTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        expediente = Expediente(numero="57725")
        lote = LoteCarga(
            anio="2026", ejecutora="785", pecosas_solicitadas="4601,4602",
        )
        self.db.add_all([expediente, lote])
        self.db.flush()
        self.pecosa_procesada = Pecosa(
            numero="4601", expediente_id=expediente.id, estado="Normalizada",
        )
        self.pecosa_faltante = Pecosa(
            numero="4602", expediente_id=expediente.id, estado="Recibida",
        )
        self.db.add_all([self.pecosa_procesada, self.pecosa_faltante])
        self.db.flush()
        self.db.add(BienAlta(
            pecosa_id=self.pecosa_procesada.id,
            lote_id=lote.id,
            codigo_patrimonial="740899502020",
            descripcion="BIEN PROCESADO",
        ))
        self.db.commit()
        self.lote = lote

    def tearDown(self):
        self.db.close()

    def test_difiere_pecosa_sin_filas_y_completa_el_lote_parcial(self):
        bienes = self.db.query(BienAlta).filter(BienAlta.lote_id == self.lote.id).all()
        self.assertEqual(_pecosas_no_encontradas(self.lote, bienes), ["4602"])

        correcto, _ = _diferir_pecosa_faltante(
            self.db, self.lote, self.pecosa_faltante.numero,
        )

        self.assertTrue(correcto)
        self.assertEqual(self.lote.pecosas_solicitadas, "4601")
        self.assertEqual(self.pecosa_faltante.estado, "Recibida")
        self.assertEqual(_pecosas_no_encontradas(self.lote, bienes), [])

    def test_no_permite_dejar_un_lote_sin_pecosas_procesadas(self):
        self.lote.pecosas_solicitadas = "4602"
        self.db.commit()

        correcto, mensaje = _diferir_pecosa_faltante(
            self.db, self.lote, self.pecosa_faltante.numero,
        )

        self.assertFalse(correcto)
        self.assertIn("sin ninguna pecosa procesada", mensaje)
        self.assertEqual(self.lote.pecosas_solicitadas, "4602")


class CompletarLoteParcialTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        self.expediente = Expediente(numero="60150")
        self.persona = Persona(nombre_completo="RESPONSABLE HUAGAL", dni="12345678")
        self.centro = CentroCosto(nombre_depend="HUAGAL", ipress="4501")
        self.lote = LoteCarga(
            anio="2026",
            ejecutora="785",
            pecosas_solicitadas="4744",
            archivo_generado="formato_importacion_lote_26.xls",
        )
        self.db.add_all([self.expediente, self.persona, self.centro, self.lote])
        self.db.flush()
        self.pecosa = Pecosa(
            numero="4744", expediente_id=self.expediente.id, estado="Normalizada",
        )
        self.db.add(self.pecosa)
        self.db.flush()
        self.db.add_all([
            BienAlta(
                pecosa_id=self.pecosa.id, lote_id=self.lote.id,
                codigo_patrimonial="740899502001", descripcion="BIEN EXISTENTE 1",
                persona_id=self.persona.id, centro_costo_id=self.centro.id,
            ),
            BienAlta(
                pecosa_id=self.pecosa.id, lote_id=self.lote.id,
                codigo_patrimonial="740899502002", descripcion="BIEN EXISTENTE 2",
                persona_id=self.persona.id, centro_costo_id=self.centro.id,
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _reporte_corregido(self):
        filas = [
            ("740899502001", "BIEN CAMBIADO", "4744"),
            ("740899502002", "BIEN EXISTENTE 2", "PECOSA 4744-2026"),
            ("740899502003", "BIEN NUEVO", "4744"),
            ("740899502003", "BIEN NUEVO REPETIDO", "4744"),
            ("740899509999", "OTRA PECOSA", "9999"),
        ]
        return pd.DataFrame([
            {
                "codigo_patrimonial": codigo,
                "descripcion": descripcion,
                "observaciones": observacion,
                "modelo": "MODELO",
                "marca": "MARCA",
                "estado_conserv": "1",
                "nro_serie": "SERIE",
                "fecha_movimto": "2026-08-31",
                "nombre_depend": "HUAGAL",
                "nombre_completo": "RESPONSABLE HUAGAL",
            }
            for codigo, descripcion, observacion in filas
        ])

    def test_agrega_solo_el_bien_faltante_al_mismo_lote_y_expediente(self):
        resultado = _completar_bienes_lote(
            self.db, self.lote, self._reporte_corregido()
        )
        self.db.commit()

        bienes = self.db.query(BienAlta).order_by(BienAlta.codigo_patrimonial).all()
        self.assertEqual(resultado["agregados"], 1)
        self.assertEqual(resultado["agregados_por_pecosa"], {"4744": 1})
        self.assertEqual(resultado["duplicados_omitidos"], 3)
        self.assertEqual(len(bienes), 3)
        self.assertEqual(bienes[-1].codigo_patrimonial, "740899502003")
        self.assertTrue(all(bien.lote_id == self.lote.id for bien in bienes))
        self.assertTrue(all(bien.pecosa_id == self.pecosa.id for bien in bienes))
        self.assertEqual(self.pecosa.expediente_id, self.expediente.id)
        self.assertEqual(self.db.query(LoteCarga).count(), 1)
        self.assertEqual(self.db.query(Expediente).count(), 1)
        self.assertIsNone(self.lote.archivo_generado)
        self.assertEqual(bienes[0].descripcion, "BIEN EXISTENTE 1")

    def test_repetir_el_reporte_no_duplica_bienes(self):
        _completar_bienes_lote(self.db, self.lote, self._reporte_corregido())
        self.db.commit()

        resultado = _completar_bienes_lote(
            self.db, self.lote, self._reporte_corregido()
        )
        self.db.commit()

        self.assertEqual(resultado["agregados"], 0)
        self.assertEqual(self.db.query(BienAlta).count(), 3)


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
