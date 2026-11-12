"""Práctica y validación con Qwen3 real y ofertas ficticias, sin SerpApi."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from src.agent import ClienteOllama
from src.demo_ofertas import consultar_catalogo_ficticio
from src.memoria_busquedas import MemoriaBusquedas
from src.mejora_agente import practicar, experimentar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salida", required=True)
    parser.add_argument("--guardar-local", action="store_true", help="Conserva experiencia ficticia y experimento en la app")
    args = parser.parse_args()
    with TemporaryDirectory() as temporal:
        memoria = MemoriaBusquedas(None if args.guardar_local else Path(temporal) / "experimento.sqlite3")
        cliente = ClienteOllama()
        progreso = lambda texto: print(texto, flush=True)
        practica = practicar(cliente, consultar_catalogo_ficticio, memoria, progreso)
        informe = experimentar(cliente, consultar_catalogo_ficticio, memoria, progreso)
        informe["practica"] = practica
        Path(args.salida).write_text(json.dumps(informe, ensure_ascii=False, indent=2) + "\n")
        print("Adoptada:", informe["adoptada"], informe["motivo_validacion"], flush=True)
        for par in informe["validacion"]:
            print({k: {c: v[c] for c in ("ida", "total", "consultas", "llamadas_modelo", "error")}
                   for k, v in par.items()}, flush=True)
        if any(r["error"] for r in practica) or any(r["error"] for p in informe["validacion"] for r in p.values()):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
