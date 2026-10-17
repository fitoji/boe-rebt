#!/usr/bin/env python3
"""Tests para boe_rebt_to_markdown.py — stdlib unittest, sin acceso a red.

Cubre las correcciones acordadas en la revisión (imágenes, encabezados
numerados, versión vigente, caché no envenenable, bloque editorial tras las
ITC) y pinea el comportamiento previo que no debe cambiar (expansión de
colspan/rowspan, super/subíndices, reutilización de caché válida).
"""
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boe_rebt_to_markdown as boe

VALIDO = b"<response><status><code>200</code></status></response>"
BASURA = b"Bad Gateway"


def el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def respuesta_http(data: bytes):
    r = mock.MagicMock()
    r.__enter__.return_value.read.return_value = data
    return r


# --------------------------------------------------------------- correcciones
class TestImagenes(unittest.TestCase):
    def test_imagen_se_conserva_como_enlace_absoluto(self):
        p = el('<p class="imagen"><img src="/datos/imagenes/disp/2002/224/18099_image32.png"/></p>')
        txt = boe.inline_text(p)
        self.assertIn(
            "![imagen](https://www.boe.es/datos/imagenes/disp/2002/224/18099_image32.png)",
            txt,
        )

    def test_imagen_sin_src_no_genera_ruido(self):
        p = el('<p class="imagen">texto <img/></p>')
        self.assertEqual(boe.inline_text(p), "texto")


class TestEncabezadosNumerados(unittest.TestCase):
    def test_apartado_corto_es_encabezado(self):
        self.assertEqual(boe.numbered_heading_level("1. Objeto y campo de aplicación"), 3)
        self.assertEqual(boe.numbered_heading_level("1.1 Generalidades"), 4)

    def test_enumeracion_del_cuerpo_no_es_encabezado(self):
        self.assertEqual(
            boe.numbered_heading_level(
                "1. Se deberá comprobar que los valores de tensión cumplen lo indicado "
                "en el apartado anterior de esta instrucción."
            ),
            0,
        )
        self.assertEqual(boe.numbered_heading_level("Los valores de 1.5 y 2.0 son válidos."), 0)

    def test_miles_no_son_encabezado(self):
        self.assertEqual(boe.numbered_heading_level("16.000 instalaciones nuevas"), 0)


class TestVersionVigente(unittest.TestCase):
    BLOQUE = (
        "<bloque>"
        '<version fecha_vigencia="20020918"><p>texto viejo</p></version>'
        '<version fecha_vigencia="20990101"><p>texto futuro</p></version>'
        "</bloque>"
    )

    def test_no_exporta_version_futura(self):
        ver = boe.pick_latest_version(el(self.BLOQUE), hoy="20251017")
        self.assertEqual(ver.findtext("p"), "texto viejo")

    def test_todas_futuras_cae_a_la_mas_temprana(self):
        b = el(
            "<bloque>"
            '<version fecha_vigencia="20990101"/>'
            '<version fecha_vigencia="20980101"/>'
            "</bloque>"
        )
        ver = boe.pick_latest_version(b, hoy="20251017")
        self.assertEqual(ver.get("fecha_vigencia"), "20980101")


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "c.xml"
        sleep = mock.patch.object(boe.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_cache_corrupta_se_redescarga_y_sobrescribe(self):
        self.cache.write_bytes(BASURA)
        with mock.patch.object(
            boe.urllib.request, "urlopen", return_value=respuesta_http(VALIDO)
        ) as u:
            data = boe.fetch("http://ejemplo", self.cache)
        self.assertEqual(data, VALIDO)
        self.assertEqual(self.cache.read_bytes(), VALIDO)
        u.assert_called_once()

    def test_respuesta_no_xml_no_se_cachea(self):
        with mock.patch.object(
            boe.urllib.request,
            "urlopen",
            side_effect=[respuesta_http(BASURA), respuesta_http(VALIDO)],
        ) as u:
            data = boe.fetch("http://ejemplo", self.cache)
        self.assertEqual(data, VALIDO)
        self.assertEqual(self.cache.read_bytes(), VALIDO)
        self.assertEqual(u.call_count, 2)

    def test_cache_valida_se_reusa_sin_red(self):
        self.cache.write_bytes(VALIDO)
        with mock.patch.object(
            boe.urllib.request, "urlopen", side_effect=AssertionError("no debe salir a red")
        ):
            self.assertEqual(boe.fetch("http://ejemplo", self.cache), VALIDO)


class TestAgrupacion(unittest.TestCase):
    def test_bloque_editorial_tras_itc_va_a_archivo_propio(self):
        g, started = boe.group_for_block("ITC-BT-52", "00_reglamento", False)
        self.assertEqual((g, started), ("ITC-BT-52", True))
        g2, started2 = boe.group_for_block("[Información relacionada]", g, started)
        self.assertEqual(g2, "zz_informacion-relacionada")
        self.assertTrue(started2)

    def test_bloques_previos_a_las_itc_siguen_en_reglamento(self):
        g, started = boe.group_for_block("Disposición adicional primera", "00_reglamento", False)
        self.assertEqual((g, started), ("00_reglamento", False))


class TestSaltosDeLinea(unittest.TestCase):
    def test_inline_text_colapsa_saltos_del_xml_pretty_printed(self):
        # El BOE parte número y título de un apartado en líneas distintas
        # dentro del mismo <p>: "0.\n   ÍNDICE" debe quedar "0. ÍNDICE".
        p = el("<p>0.\n      ÍNDICE</p>")
        self.assertEqual(boe.inline_text(p), "0. ÍNDICE")


# ------------------------------------------------ preservación (no regresión)
class TestComportamientoExistente(unittest.TestCase):
    def test_tabla_expande_colspan_y_rowspan(self):
        t = el(
            "<table>"
            '<tr><td colspan="2">A</td><td>B</td></tr>'
            '<tr><td rowspan="2">C</td><td>D</td><td>E</td></tr>'
            "<tr><td>F</td><td>G</td></tr>"
            "</table>"
        )
        self.assertEqual(
            boe.table_to_grid(t),
            [["A", "", "B"], ["C", "D", "E"], ["C", "F", "G"]],
        )

    def test_super_y_subindice_legibles(self):
        p = el("<p>R<sub>2</sub> = 10<sup>-3</sup> Ω</p>")
        self.assertEqual(boe.inline_text(p), "R_2 = 10^-3 Ω")


if __name__ == "__main__":
    unittest.main()
