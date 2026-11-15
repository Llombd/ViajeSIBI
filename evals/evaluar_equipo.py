"""Compara un agente con el equipo usando Qwen3 y ofertas ficticias."""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from time import monotonic

from src.agent import ClienteOllama
from src.demo_ofertas import consultar_catalogo_ficticio
from src.equipo_viaje import EquipoViaje
from src.seleccion_viaje import proponer_busquedas, decidir_siguiente_busqueda, explorar_ofertas

# Casos fijados antes de revisar la eficiencia del equipo.
CASOS = (("VLC", 600, "cultura"), ("LEN", 500, "gastronomía"), ("BIO", 700, "museos"))
FECHAS = [(date(2027, 3, 2), date(2027, 3, 5)), (date(2027, 3, 9), date(2027, 3, 12))]


class ClienteContado:
    def __init__(self):
        self.cliente = ClienteOllama()
        self.llamadas = 0

    def consultar_json(self, mensajes, formato):
        self.llamadas += 1
        return self.cliente.consultar_json(mensajes, formato)


def medir(origen, presupuesto, gustos, equipo):
    cliente = ClienteContado()
    consultas = 0

    def proveedor(parametros):
        nonlocal consultas
        consultas += 1
        return consultar_catalogo_ficticio(parametros)

    inicio = monotonic()
    if equipo:
        planes, traza, _ = EquipoViaje(cliente, proveedor).planificar(
            origen, FECHAS, gustos, 2, presupuesto, objetivo=3,
        )
    else:
        propuestas = proponer_busquedas(cliente, origen, FECHAS, gustos, 2, presupuesto)
        planes, traza, _ = explorar_ofertas(
            proveedor, origen, propuestas, 2, presupuesto,
            replantear=lambda datos: decidir_siguiente_busqueda(
                cliente, origen, FECHAS, gustos, 2, presupuesto, datos, propuestas,
            ), fechas=FECHAS, limite_intentos=3, conservar_pendientes=True, limite_total=presupuesto,
        )
    confirmados = [p["total"] for p in planes if p.get("impuestos_confirmados")]
    total = min(confirmados, default=None)
    return dict(total=total, viable=total is not None and total <= presupuesto,
                consultas=consultas, llamadas_modelo=cliente.llamadas,
                segundos=round(monotonic() - inicio, 2), planes=planes, traza=traza)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salida", required=True)
    args = parser.parse_args()
    informe = dict(fecha_utc=datetime.now(timezone.utc).isoformat(), modelo="qwen3:4b",
                   datos="ficticios", limites={"consultas_datos": 12, "destinos_fechas": 3},
                   casos=[], codigo_sha256={n: hashlib.sha256(Path(n).read_bytes()).hexdigest()
                                           for n in ("src/equipo_viaje.py", "src/seleccion_viaje.py", "src/demo_ofertas.py")})
    for indice, (origen, presupuesto, gustos) in enumerate(CASOS):
        caso = dict(origen=origen, presupuesto=presupuesto, gustos=gustos)
        for equipo in ((False, True) if indice % 2 == 0 else (True, False)):
            etiqueta = "equipo" if equipo else "un_agente"
            print(origen, etiqueta, "ejecutando", flush=True)
            caso[etiqueta] = medir(origen, presupuesto, gustos, equipo)
            r = caso[etiqueta]
            print(origen, etiqueta, r["total"], r["consultas"], r["llamadas_modelo"], flush=True)
        informe["casos"].append(caso)
        Path(args.salida).write_text(json.dumps(informe, ensure_ascii=False, indent=2, default=str) + "\n")
    print("Informe", args.salida, flush=True)


if __name__ == "__main__":
    main()
