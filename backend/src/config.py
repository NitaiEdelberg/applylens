import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Optional embeddings key for the RAG career-corpus (Circle 4). When set, the
# retriever uses hosted Gemini embeddings; when unset it falls back to a local,
# deterministic scikit-learn TF-IDF embedder (no network, fully testable).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "text-embedding-004")

# Jina embeddings — free, no credit card, no region limit (get a key at
# https://jina.ai/embeddings). Preferred hosted embedder for RAG; falls back to
# a local scikit-learn TF-IDF embedder when unset.
JINA_API_KEY = os.getenv("JINA_API_KEY", "")
JINA_EMBED_MODEL = os.getenv("JINA_EMBED_MODEL", "jina-embeddings-v3")

# Optional Elasticsearch instance for full-text search over tracked applications
# (Circle 5). Bonsai/Elastic Cloud give a full URL with credentials embedded
# (https://USER:PASS@host). Unset -> the search endpoint falls back to a
# case-insensitive DB substring match, so the feature is fully testable with no
# credential. BONSAI_URL is accepted as an alias (Bonsai's default env var name).
ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "").strip() or os.getenv("BONSAI_URL", "").strip()
ELASTICSEARCH_INDEX = os.getenv("ELASTICSEARCH_INDEX", "applylens-apps")
