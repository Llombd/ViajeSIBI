"""Conversación por terminal: python3 -m src.main."""

from src.agent import AgenteViajes, ErrorOllama


def main():
    agente = AgenteViajes()
    print("Agente de viajes · Ollama local · qwen3:4b")
    print("Datos ficticios. Escribe salir para terminar. El historial dura esta sesión.")
    try:
        while True:
            texto = input("\nTú: ").strip()
            if texto.casefold() == "salir":
                break
            if not texto:
                continue
            print("Consultando el modelo local...", flush=True)
            try:
                respuesta = agente.responder(texto)
                print(f"\nAgente: {respuesta}")
            except ErrorOllama as error:
                print(f"\nError: {error}")
    except (EOFError, KeyboardInterrupt):
        print("\nSesión terminada.")


if __name__ == "__main__":
    main()
