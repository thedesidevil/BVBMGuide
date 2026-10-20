from typing import Callable

from pydantic import BaseModel, ValidationError

from src.common.ai_provider import AIClient, _lookup_pricing

from .config import Settings


class LLMStepError(Exception):
    def __init__(self, step: str, problems: list[str]):
        self.step = step
        self.problems = problems
        super().__init__(f"step '{step}' failed: " + "; ".join(problems))


class StepLLM:
    def __init__(self, settings: Settings, client_factory: Callable[[str], AIClient] | None = None):
        self.settings = settings
        self._factory = client_factory or (lambda m: AIClient(model=m))
        self._log: list[dict] = []

    @property
    def cost_log(self) -> list[dict]:
        return self._log

    def total_usd(self) -> float:
        return sum(e["usd"] for e in self._log)

    def run_json(self, step: str, system: str, prompt: str, schema: type[BaseModel],
                 validate: Callable[[BaseModel], list[str]] | None = None,
                 max_tokens: int = 8000) -> BaseModel:
        model = self.settings.models[step]
        obj, problems = self._attempt(step, model, system, prompt, schema, validate, max_tokens, False)
        if obj is not None:
            return obj
        retry_prompt = prompt + "\n\nYour previous answer was rejected for these problems:\n" + \
            "\n".join(f"- {p}" for p in problems) + "\nReturn corrected JSON only."
        obj, problems = self._attempt(step, self.settings.fallback_model, system, retry_prompt,
                                      schema, validate, max_tokens, True)
        if obj is not None:
            return obj
        raise LLMStepError(step, problems)

    def _attempt(self, step, model, system, prompt, schema, validate, max_tokens, fallback):
        client = self._factory(model)
        resp = client._client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_completion_tokens=max_tokens,
        )
        usage = resp.usage
        p_tok = getattr(usage, "prompt_tokens", 0) or 0
        c_tok = getattr(usage, "completion_tokens", 0) or 0
        price = _lookup_pricing(model)
        usd = (p_tok * price[0] + c_tok * price[1]) / 1_000_000 if price else 0.0
        self._log.append({"step": step, "model": model, "prompt_tokens": p_tok,
                          "completion_tokens": c_tok, "usd": usd, "fallback": fallback})
        text = resp.choices[0].message.content or ""
        try:
            obj = schema.model_validate_json(text)
        except ValidationError as e:
            return None, [f"invalid JSON for schema: {e.errors(include_url=False, include_input=False)}"]
        problems = validate(obj) if validate else []
        if problems:
            return None, list(problems)
        return obj, []
