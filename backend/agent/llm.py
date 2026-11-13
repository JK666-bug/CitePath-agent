import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from agent.telemetry import UsageLog

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

# 系统环境变量优先；缺少的配置再从 backend/.env 读取。
load_dotenv(ENV_PATH, override=False)

# 保留 HKU 原来的默认配置。
DEFAULT_DEPLOYMENT = "gpt-4.1-mini"
DEFAULT_API_VERSION = "2025-04-01-preview"

DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _setting(name: str, default: str = "", settings=None) -> str:
    """读取配置；空字符串按未配置处理。"""
    source = os.environ if settings is None else settings
    return str(source.get(name) or "").strip() or default


def model_configuration(settings=None) -> dict:
    """Describe the selected provider without constructing a client or exporting keys.

    The endpoint is represented only by its fingerprint, because a custom base
    URL may contain credentials or private query parameters.
    """
    provider = _setting("LLM_PROVIDER", "hku", settings).lower()
    if provider == "hku":
        model = _setting("HKU_DEPLOYMENT", DEFAULT_DEPLOYMENT, settings)
        base_url = "https://api.hku.hk/openai/student/deployments/" + model
        api_version = _setting("HKU_API_VERSION", DEFAULT_API_VERSION, settings)
        timeout = 60
        key_name = "HKU_API_KEY"
    elif provider == "deepseek":
        model = _setting("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL, settings)
        base_url = _setting("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL, settings).rstrip("/")
        api_version = None
        timeout = 120
        key_name = "DEEPSEEK_API_KEY"
    else:
        raise RuntimeError("Unsupported LLM_PROVIDER. Use 'hku' or 'deepseek' in backend/.env")
    return {
        "provider": provider, "model": model, "api_version": api_version,
        "timeout": timeout, "base_url_sha256": hashlib.sha256(base_url.encode("utf-8")).hexdigest(),
        "key_name": key_name, "key_configured": bool(_setting(key_name, settings=settings)),
    }


def _required_key(name: str) -> str:
    """只在选中对应提供商时，检查其 API key。"""
    key = _setting(name)
    if not key:
        raise RuntimeError(f"Set {name} in backend/.env")
    return key


def _hku_model() -> AzureChatOpenAI:
    key = _required_key("HKU_API_KEY")
    deployment = _setting("HKU_DEPLOYMENT", DEFAULT_DEPLOYMENT)
    api_version = _setting("HKU_API_VERSION", DEFAULT_API_VERSION)

    return AzureChatOpenAI(
        base_url=(
            "https://api.hku.hk/openai/student/deployments/"
            f"{deployment}"
        ),
        api_version=api_version,
        api_key=key,
        model=deployment,
        temperature=0,
        timeout=60,
        max_retries=1,
        callbacks=[UsageLog(deployment)],
        default_headers={
            "api-key": key,
            "Ocp-Apim-Subscription-Key": key,
        },
    )


def _deepseek_model() -> ChatOpenAI:
    key = _required_key("DEEPSEEK_API_KEY")
    model = _setting("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    base_url = _setting(
        "DEEPSEEK_BASE_URL",
        DEFAULT_DEEPSEEK_BASE_URL,
    ).rstrip("/")

    return ChatOpenAI(
        api_key=key,
        base_url=base_url,
        model=model,
        temperature=0,
        timeout=120,
        max_retries=1,
        callbacks=[UsageLog(model)],
        # 沿用项目现有的 Chat Completions 消息结构。
        use_responses_api=False,
        # 当前适配使用非思考模式，兼容现有工具调用循环。
        extra_body={
            "thinking": {
                "type": "disabled",
            },
        },
    )


def chat_model() -> BaseChatModel:
    """根据配置创建模型，默认继续使用 HKU。"""
    provider = model_configuration()["provider"]

    if provider == "hku":
        return _hku_model()

    if provider == "deepseek":
        return _deepseek_model()

    raise RuntimeError(
        "Unsupported LLM_PROVIDER. "
        "Use 'hku' or 'deepseek' in backend/.env"
    )


def ping() -> str:
    reply = chat_model().invoke([
        HumanMessage(content="Hello!"),
    ])
    return str(reply.content)
