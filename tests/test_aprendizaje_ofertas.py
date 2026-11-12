from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.datos_viaje import DatosViaje


class TestAprendizajeOfertas(unittest.TestCase):
    def test_repetir_clic_no_duplica_y_las_decisiones_persisten_por_origen(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "perfil.sqlite3"
            datos = DatosViaje(ruta)
            self.assertEqual(datos.registrar_rechazo_salida("LEN", "primera"), 1)
            self.assertEqual(datos.registrar_rechazo_salida("LEN", "primera"), 1)
            reabierto = DatosViaje(ruta)
            self.assertEqual(reabierto.registrar_rechazo_salida("LEN", "segunda"), 2)
            self.assertEqual(reabierto.registrar_rechazo_salida("VLC", "tercera"), 1)
            self.assertEqual(reabierto.prioridades_ofertas(), {})
