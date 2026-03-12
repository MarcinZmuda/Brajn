"""
Unified LLM client — supports Claude (primary) and OpenAI (optional).
"""
import anthropic
from src.common.config import ANTHROPIC_API_KEY, OPENAI_API_KEY

_claude_client = None
_openai_client = None


def get_claude_client() -> anthropic.Anthropic:
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _claude_client


def get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            import openai
            _openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
        except ImportError:
            return None
    return _openai_client


def claude_call(
    system_prompt: str,
    user_prompt: str,
    model: str = "claude-sonnet-4-5-20250514",
    max_tokens: int = 8000,
    temperature: float = 0.7,
    timeout: int = 120,
) -> tuple[str, dict]:
    """
    Call Claude API. Returns (text_response, usage_dict).
    """
    client = get_claude_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        timeout=timeout,
    )
    text = response.content[0].text if response.content else ""
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "model": model,
    }
    return text, usage


def openai_call(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4o",
    max_tokens: int = 8000,
    temperature: float = 0.7,
) -> tuple[str, dict] | None:
    """
    Call OpenAI API. Returns (text_response, usage_dict) or None if unavailable.
    """
    client = get_openai_client()
    if not client:
        return None

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    text = response.choices[0].message.content or ""
    usage = {
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "model": model,
    }
    return text, usage
