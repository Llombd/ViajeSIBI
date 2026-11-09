"""Ejecuta desde la raíz: python3 -m evals.comparar."""

import argparse
import json
from time import monotonic
from urllib.request import Request, urlopen

from src.agent import AgenteViajes, ClienteOllama
from src.tools import CATALOGO


CASOS = {
    "coste": ["¿Cuánto cuesta ir a Oporto desde Madrid 4 días para 2 personas? "
              "Dame el total del grupo y el coste por persona."],
    "presupuesto": ["Entre Lisboa y Oporto, ¿cuál cabe en 800 EUR en total para 2 personas "
                    "y 4 días desde Madrid? Compara los dos costes."],
    "origen_no_disponible": ["Calcula el coste de Oporto desde León para 2 personas y 4 días. "
                            "Tenemos 800 EUR en total. No cambies la ciudad de salida."],
}


def responder_sin_agente(modelo, historial):
    """Una llamada directa al mismo modelo, con catálogo y fórmula disponibles."""
    peticion = Request(
        "http://localhost:11434/api/chat",
        data=json.dumps({
            "model": modelo, "messages": historial, "stream": False, "think": False,
            "options": {"num_ctx": 8192, "num_predict": 1024, "temperature": 0.2},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(peticion, timeout=120) as respuesta:
        datos = json.load(respuesta)
    if datos.get("done_reason") == "length":
        raise ValueError("El modelo alcanzó el límite de salida.")
    return datos["message"]["content"].rsplit("</think>", 1)[-1].strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", default="qwen3:4b")
    parser.add_argument("--caso", choices=CASOS, action="append")
    args = parser.parse_args()

    catalogo = json.loads(CATALOGO.read_text(encoding="utf-8"))
    costes = {d["nombre"]: d["costes"] for d in catalogo["destinos"]}
    instrucciones = (
        "Eres un asistente de viajes. Responde en español con los datos ficticios suministrados. "
        "El total del grupo es viajeros por (transporte de ida y vuelta por persona + "
        "alojamiento por persona y noche por (días - 1) + gastos diarios por persona por días). "
        "Si faltan datos, pide una aclaración. Si no hay coste para el origen pedido, "
        "dilo y conserva el origen. Respeta el presupuesto total. Da solo la respuesta final en cinco líneas como máximo. Catálogo: "
        + json.dumps(costes, ensure_ascii=False) + "\n/no_think"
    )
    for nombre in args.caso or CASOS:
        for modo in ("modelo_directo", "agente"):
            trazas = []
            agente = AgenteViajes(cliente=ClienteOllama(args.modelo), mostrar=trazas.append)
            historial = [{"role": "system", "content": instrucciones}]
            for consulta in CASOS[nombre]:
                inicio = monotonic()
                historial.append({"role": "user", "content": consulta})
                try:
                    if modo == "agente":
                        respuesta = agente.responder(consulta)
                    else:
                        respuesta = responder_sin_agente(args.modelo, historial)
                except (RuntimeError, OSError, ValueError, KeyError) as error:
                    respuesta = None
                    fallo = str(error)
                else:
                    fallo = None
                    historial.append({"role": "assistant", "content": respuesta})
                print(json.dumps({
                    "caso": nombre, "modelo": args.modelo, "modo": modo,
                    "consulta": consulta, "respuesta": respuesta, "fallo": fallo,
                    "segundos": round(monotonic() - inicio, 2), "trazas": trazas,
                }, ensure_ascii=False), flush=True)
                if fallo:
                    break


if __name__ == "__main__":
    main()
