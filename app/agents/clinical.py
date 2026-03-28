import json
from openai import AsyncOpenAI
from app.agents.base import BaseAgent
from app.models.clinical import AgentOutput
from app.core.config import get_settings

# System prompt: le decimos al LLM exactamente qué rol tiene
# y en qué formato tiene que responder.
SYSTEM_PROMPT = """Eres un asistente clínico de IA especializado en análisis de casos médicos.

Analiza el caso clínico y responde ÚNICAMENTE con un objeto JSON válido con esta estructura exacta:
{
  "agent_name": "ClinicalAgent",
  "summary": "resumen breve del caso",
  "findings": ["hallazgo 1", "hallazgo 2"],
  "red_flags": ["señal de alerta 1"] o [],
  "recommendations": ["recomendación 1"],
  "confidence": 0.85,
  "context_sources": []
}

Reglas:
- confidence es un número entre 0.0 y 1.0
- red_flags solo incluye señales de peligro inmediato
- No añadas texto fuera del JSON
- Responde siempre en español"""


class ClinicalAgent(BaseAgent):
    """
    FASE 2: Implementación con OpenAI SDK directo.
    Groq es compatible con este SDK — solo cambia base_url y api_key.
    En Fase 3 migramos esto a LangChain para ver el contraste.
    """

    def __init__(self) -> None:
        settings = get_settings()
        # Groq usa la misma interfaz que OpenAI — solo diferente base_url
        self.client = AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
        )
        self.model = settings.llm_model

    async def run(self, caso_clinico: str) -> AgentOutput:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": caso_clinico},
            ],
            response_format={"type": "json_object"},  # fuerza JSON válido
            temperature=0.2,  # bajo para respuestas consistentes y precisas
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)  # str → dict
        return AgentOutput.model_validate(data)  # dict → Pydantic model validado
