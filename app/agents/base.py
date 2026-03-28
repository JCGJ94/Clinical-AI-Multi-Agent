from abc import ABC, abstractmethod
from app.models.clinical import AgentOutput


class BaseAgent(ABC):
    """
    Contrato que todos los agentes deben cumplir.
    Cada agente recibe un caso clínico y devuelve un AgentOutput estructurado.
    """

    @abstractmethod
    async def run(self, caso_clinico: str) -> AgentOutput:
        """
        Analiza el caso clínico y devuelve un resultado estructurado.
        Siempre async — nunca bloqueamos el event loop con llamadas a APIs externas.
        """
        ...
