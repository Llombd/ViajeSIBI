"""Compara las estrategias con Qwen3 local y un catálogo reproducible."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import monotonic
from datetime import date

from src.agent import ClienteOllama, ErrorOllama
from src.balance_comparacion import balance_comparacion
from src.demo_ofertas import consultar_catalogo_ficticio
from src.seleccion_viaje import comparar_estrategias, evaluar_comparacion, intervalos


CASOS = (
    ("VLC", 400, "cultura, museos"),
    ("LEN", 450, "ciudad grande, gastronomía"),
    ("BIO", 500, "playa, buena comida"),
    ("MAD", 600, "museos, vida nocturna"),
    ("SVQ", 700, "cultura, naturaleza"),
    ("BCN", 350, "gastronomía, ciudad mediana"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salida", help="Archivo JSON con resultados y trazas, sin claves API")
    parser.add_argument("--detalle", action="store_true", help="Muestra decisiones y errores de revisión")
    parser.add_argument("--comprobar-limite", action="store_true",
                        help="Ejecuta solo un caso de 200 EUR para comprobar el descarte previo al hotel; no sustituye el piloto de seis casos")
    args = parser.parse_args()
    cliente = ClienteOllama()
    informe = {"fecha_utc": datetime.now(timezone.utc).isoformat(), "modelo": "qwen3:4b",
               "datos": "ficticios", "casos": [], "codigo_sha256": {}}
    for nombre in ("src/seleccion_viaje.py", "src/ofertas_reales.py", "src/demo_ofertas.py"):
        informe["codigo_sha256"][nombre] = hashlib.sha256(Path(nombre).read_bytes()).hexdigest()
    fechas = intervalos(date(2027, 2, 1), date(2027, 2, 21), 3)
    balance = Counter()
    casos = (("MAD", 200, "cultura"),) if args.comprobar_limite else CASOS
    informe["protocolo"] = "Comprobación de límite" if args.comprobar_limite else "Piloto de seis casos"
    for origen, presupuesto, gustos in casos:
        inicio = monotonic()
        try:
            resultados = comparar_estrategias(
                cliente, consultar_catalogo_ficticio, origen, fechas, gustos, 2, presupuesto,
            )
        except ErrorOllama as error:
            balance["Error del modelo"] += 1
            print(f"{origen} | {presupuesto} € | {error}", flush=True)
            informe["casos"].append(dict(origen=origen, presupuesto=presupuesto, gustos=gustos,
                                         error=str(error), segundos=monotonic()-inicio))
            continue
        resultado = evaluar_comparacion(resultados)
        balance[resultado] += 1
        informe["casos"].append(dict(origen=origen, presupuesto=presupuesto, gustos=gustos,
                                     resultado=resultado, segundos=monotonic()-inicio, estrategias=resultados,
                                     balance_economico=balance_comparacion(resultados, presupuesto)))
        campos = []
        for _, intentos, planes, _ in resultados:
            destinos = ", ".join(f"{i['aeropuerto']} {i['ida']}" for i in intentos)
            total = f"{planes[0]['total']:.2f} €" if planes else "Sin plan"
            campos.append(f"{total} ({destinos})")
        print(f"{origen} | {presupuesto} € | {' | '.join(campos)} | {resultado}", flush=True)
        print(balance_comparacion(resultados, presupuesto)["titulo"], flush=True)
        if args.detalle:
            for paso in resultados[1][3]:
                print("  " + paso, flush=True)
    print(dict(balance))
    informe["balance"] = dict(balance)
    if args.salida:
        Path(args.salida).write_text(json.dumps(informe, ensure_ascii=False, indent=2,
                                              default=lambda valor: valor.isoformat()) + "\n")
    if balance["Error del modelo"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
