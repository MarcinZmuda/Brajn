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
    model: str = "claude-sonnet-4-6",
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


def gemini_call(
    system_prompt: str,
    user_prompt: str,
    model: str = "gemini-2.5-flash",
    max_tokens: int = 8000,
    temperature: float = 0.7,
    timeout: int = 120,
) -> tuple[str, dict]:
    """
    Call Gemini API via google-generativeai SDK.
    Returns (text_response, usage_dict).
    Falls back to claude_call if Gemini is unavailable.
    """
    try:
        import google.generativeai as genai
        from src.common.config import GEMINI_API_KEY
    except ImportError:
        print("[LLM] google-generativeai not installed, falling back to Claude")
        return claude_call(system_prompt, user_prompt, max_tokens=max_tokens,
                           temperature=temperature, timeout=timeout)

    if not GEMINI_API_KEY:
        print("[LLM] GEMINI_API_KEY not set, falling back to Claude")
        return claude_call(system_prompt, user_prompt, max_tokens=max_tokens,
                           temperature=temperature, timeout=timeout)

    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        ),
    )

    try:
        response = gemini_model.generate_content(user_prompt)
        text = response.text or ""
        # Gemini usage metadata
        usage_meta = getattr(response, "usage_metadata", None)
        usage = {
            "input_tokens": getattr(usage_meta, "prompt_token_count", 0) if usage_meta else 0,
            "output_tokens": getattr(usage_meta, "candidates_token_count", 0) if usage_meta else 0,
            "model": model,
        }
        return text, usage
    except Exception as e:
        print(f"[LLM] Gemini error: {e}, falling back to Claude")
        return claude_call(system_prompt, user_prompt, max_tokens=max_tokens,
                           temperature=temperature, timeout=timeout)


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
