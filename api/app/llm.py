"""Cliente de modelo, con salida estructurada y loop de reparación.

Dos decisiones que importan:

1. **API compatible con OpenAI.** Ollama la expone, y Groq, Cerebras y
   OpenRouter también. Así el modelo se cambia por configuración —incluido
   comparar varios en el harness— sin tocar el código de los agentes.

2. **Loop de reparación.** Un modelo de 4B o 7B devuelve JSON inválido o fuera
   de esquema con frecuencia suficiente como para que reintentar con el error
   de validación en el prompt no sea un parche: es una pieza del sistema. La
   cantidad de reparaciones es una métrica, no un detalle de implementación.

Nada de esto sale de la máquina: `OLLAMA_BASE_URL` apunta a localhost. Si la
privacidad es la premisa del producto, ningún componente que vea un movimiento
puede hablar con un servicio externo — el supervisor incluido.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
MODELO = os.getenv("CENTAVO_MODELO", "qwen2.5:7b")
TIMEOUT = float(os.getenv("CENTAVO_LLM_TIMEOUT", "120"))
MAX_REPARACIONES = int(os.getenv("CENTAVO_MAX_REPARACIONES", "2"))

_BLOQUE_JSON = re.compile(r"\{.*\}", re.S)


@dataclass
class Uso:
    """Lo que costó una llamada. Se acumula para el scorecard."""

    llamadas: int = 0
    reparaciones: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    segundos: float = 0.0

    def sumar(self, otro: "Uso") -> None:
        self.llamadas += otro.llamadas
        self.reparaciones += otro.reparaciones
        self.tokens_entrada += otro.tokens_entrada
        self.tokens_salida += otro.tokens_salida
        self.segundos += otro.segundos


class ErrorModelo(RuntimeError):
    pass


@dataclass
class ClienteLLM:
    modelo: str = MODELO
    base_url: str = BASE_URL
    temperatura: float = 0.0          # clasificar es determinista, no creativo
    uso: Uso = field(default_factory=Uso)

    def _post(self, mensajes: list[dict[str, str]], esquema: dict | None) -> tuple[str, dict]:
        cuerpo: dict[str, Any] = {
            "model": self.modelo,
            "messages": mensajes,
            "temperature": self.temperatura,
        }
        if esquema is not None:
            # Ollama soporta structured outputs por esta vía; si el servidor no
            # la entiende, el loop de reparación sigue cubriendo el caso.
            cuerpo["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "respuesta", "schema": esquema, "strict": True},
            }

        inicio = time.perf_counter()
        with httpx.Client(timeout=TIMEOUT) as cli:
            r = cli.post(f"{self.base_url}/chat/completions", json=cuerpo)
        transcurrido = time.perf_counter() - inicio

        if r.status_code >= 400:
            raise ErrorModelo(f"{r.status_code}: {r.text[:300]}")

        data = r.json()
        uso = data.get("usage") or {}
        self.uso.llamadas += 1
        self.uso.segundos += transcurrido
        self.uso.tokens_entrada += uso.get("prompt_tokens", 0)
        self.uso.tokens_salida += uso.get("completion_tokens", 0)

        return data["choices"][0]["message"]["content"], uso

    def estructurado(
        self,
        sistema: str,
        usuario: str,
        modelo_salida: type[T],
    ) -> T:
        """Pide una respuesta y la valida contra el modelo Pydantic.

        Si no valida, reintenta pasándole el error — que es información mucho
        más útil que 'devolvé JSON válido'.
        """
        esquema = modelo_salida.model_json_schema()
        mensajes = [
            {"role": "system", "content": sistema},
            {"role": "user", "content": usuario},
        ]

        ultimo_error = ""
        for intento in range(MAX_REPARACIONES + 1):
            crudo, _ = self._post(mensajes, esquema)
            try:
                return modelo_salida.model_validate_json(_extraer_json(crudo))
            except (ValidationError, ValueError) as exc:
                ultimo_error = str(exc)[:500]
                self.uso.reparaciones += 1
                mensajes = [
                    *mensajes,
                    {"role": "assistant", "content": crudo[:1000]},
                    {
                        "role": "user",
                        "content": (
                            "Esa respuesta no valida contra el esquema. Error:\n"
                            f"{ultimo_error}\n\n"
                            "Devolvé SOLO el objeto JSON corregido, sin texto alrededor."
                        ),
                    },
                ]

        raise ErrorModelo(
            f"no logré una respuesta válida en {MAX_REPARACIONES + 1} intentos. "
            f"Último error: {ultimo_error}"
        )


def _extraer_json(texto: str) -> str:
    """Un modelo chico suele envolver el JSON en prosa o en un bloque ```json.
    Rescatar el objeto es más barato que reintentar."""
    t = texto.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    if t.startswith("{"):
        return t
    if (m := _BLOQUE_JSON.search(t)) is not None:
        return m.group(0)
    raise ValueError(f"no hay un objeto JSON en la respuesta: {texto[:200]!r}")


def ping() -> tuple[bool, str]:
    """¿Hay un Ollama del otro lado y el modelo está bajado?"""
    try:
        with httpx.Client(timeout=10) as cli:
            r = cli.get(f"{BASE_URL.rsplit('/v1', 1)[0]}/api/tags")
        nombres = [m["name"] for m in r.json().get("models", [])]
    except Exception as exc:
        return False, f"Ollama no responde en {BASE_URL}: {exc.__class__.__name__}"

    if MODELO not in nombres:
        return False, (
            f"el modelo {MODELO!r} no está bajado. "
            f"Disponibles: {', '.join(nombres) or 'ninguno'}. "
            f"Bajalo con: ollama pull {MODELO}"
        )
    return True, f"{MODELO} listo"
