"""Server-only Meta model provider selection; never exposes credentials."""
import os


def config():
    provider = os.getenv("META_PROVIDER", "meta").strip().lower()
    if provider == "baseten":
        return provider, os.getenv("BASETEN_API_KEY", "").strip(), "meta-models/muse-spark-open-1026", "https://inference.baseten.co/v1/chat/completions"
    if provider != "meta":
        raise ValueError("META_PROVIDER must be meta or baseten")
    return provider, os.getenv("META_API_KEY", "").strip(), os.getenv("META_MODEL", "muse-spark-1.3"), "https://api.meta.ai/v1/chat/completions"
