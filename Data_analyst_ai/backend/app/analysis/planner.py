"""Turn natural-language questions and schema context into structured analysis plans."""

from backend.app.llm.base import LLMProvider

from .models import SQLPlan


class AnalysisPlanner:
    """Ask the LLM for a typed direct-answer, clarification, or SQL plan."""
    def __init__(self, llm_provider: LLMProvider) -> None:
        """Initialize the AnalysisPlanner with its required collaborators and state."""
        self._llm_provider = llm_provider

    def plan(
        self,
        question: str,
        schema_catalog: str,
        business_glossary: str = "",
    ) -> SQLPlan:
        """Perform plan and return the resulting application value."""
        if not question.strip():
            raise ValueError("Question must not be empty")
        prompt = self._build_prompt(question, schema_catalog, business_glossary)
        response = self._llm_provider.generate_structured(prompt, SQLPlan)
        return response.parsed_output

    def repair(
        self,
        question: str,
        schema_catalog: str,
        failed_plan: SQLPlan,
        failure_reason: str,
        business_glossary: str = "",
    ) -> SQLPlan:
        """Perform repair and return the resulting application value."""
        repair_context = (
            f"Previous plan intent: {failed_plan.intent}\n"
            f"Previous SQL: {failed_plan.sql}\n"
            f"Safe failure reason: {failure_reason}\n"
            "Return a corrected read-only plan. Do not add tables or columns "
            "that are absent from the schema."
        )
        prompt = self._build_prompt(
            question,
            schema_catalog,
            business_glossary,
            repair_context,
        )
        response = self._llm_provider.generate_structured(prompt, SQLPlan)
        return response.parsed_output

    @staticmethod
    def _build_prompt(
        question: str,
        schema_catalog: str,
        business_glossary: str,
        additional_context: str = "",
    ) -> str:
        """Internal helper that performs build prompt and returns the normalized result."""
        return (
            "Create a read-only MySQL analysis plan. Return only fields in the "
            "requested SQLPlan schema. Never claim that SQL was executed. "
            "For a general question that needs no database, provide a concise "
            "direct_answer and leave sql empty. "
            "If the question is ambiguous, set clarification_question and leave "
            "sql empty. Use only tables and columns in the supplied catalog. "
            "For net revenue, use the supplied business metric and avoid joining "
            "payment and refund fact rows before aggregation.\n\n"
            f"Schema catalog JSON:\n{schema_catalog}\n\n"
            f"Business glossary:\n{business_glossary}\n\n"
            f"User question:\n{question}\n\n"
            f"Additional repair context:\n{additional_context}"
        )
