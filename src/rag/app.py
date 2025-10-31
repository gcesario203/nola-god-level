import os
import json
import re
import hashlib
import pickle
from pathlib import Path
from typing import List, Optional, Any
from datetime import datetime, timedelta

from openai import OpenAI
import chromadb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# =========================
# Variáveis de Ambiente
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

CORPUS_DIR = Path(os.getenv("CORPUS_DIR", "./corpus"))
TOP_K = int(os.getenv("TOP_K", "6"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2000"))
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "180"))

# Persistência do Chroma (opcional)
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "").strip()
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "querybuilder_docs")

# Configurações de Cache
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"
CACHE_TYPE = os.getenv("CACHE_TYPE", "memory")  # "memory" ou "redis"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

SYSTEM_PROMPT = """
Você é um Query Builder SQL especializado em PostgreSQL. Use APENAS tabelas/colunas presentes no CONTEXTO RAG.
Gere SQL seguro e legível (CTEs quando útil).

IMPORTANTE: Retorne APENAS um objeto JSON válido (sem markdown, sem ```json).

Formato obrigatório:
{
  "tables_used": [],
  "columns_used": [],
  "joins_explained": [],
  "assumptions": [],
  "sql": "..."
}

Regras:
- Filtro padrão: últimos 90 dias e status COMPLETED quando o usuário não especificar.
- Evite SELECT *.
- Para datas use sales.created_at; para status use sales.sale_status_desc.
- Para granularidade diária: DATE(sales.created_at) como sale_date.
- Joins frequentes: sales→stores, sales→channels, sales→customers (LEFT), product_sales→sales, item_product_sales→product_sales, payments→payment_types.
- Se faltar algo no contexto, explique em "assumptions".
"""

# =========================
# OpenAI Client
# =========================
client = OpenAI(api_key=OPENAI_API_KEY, timeout=TIMEOUT_SECONDS)

# =========================
# Cache Manager
# =========================
class CacheManager:
    """Gerenciador de cache com suporte para memória e Redis"""
    
    def __init__(self, cache_type: str = "memory", redis_url: str = None):
        self.cache_type = cache_type
        self.memory_cache = {}
        
        if cache_type == "redis":
            try:
                import redis
                self.redis_client = redis.from_url(redis_url or REDIS_URL)
                print(f"[CACHE] Redis conectado: {redis_url or REDIS_URL}")
            except ImportError:
                print("[CACHE] Redis não disponível, usando cache em memória")
                self.cache_type = "memory"
            except Exception as e:
                print(f"[CACHE] Erro ao conectar Redis: {e}, usando cache em memória")
                self.cache_type = "memory"
    
    def _hash_key(self, *args) -> str:
        """Gera hash SHA256 para chave de cache"""
        combined = ":".join(str(arg) for arg in args)
        return hashlib.sha256(combined.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Busca valor do cache"""
        if not CACHE_ENABLED:
            return None
            
        try:
            if self.cache_type == "redis":
                data = self.redis_client.get(key)
                return pickle.loads(data) if data else None
            else:
                if key in self.memory_cache:
                    value, timestamp, ttl = self.memory_cache[key]
                    if datetime.now() - timestamp < timedelta(seconds=ttl):
                        return value
                    else:
                        del self.memory_cache[key]
                return None
        except Exception as e:
            print(f"[CACHE] Erro ao buscar cache: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = 3600):
        """Salva valor no cache com TTL em segundos"""
        if not CACHE_ENABLED:
            return
            
        try:
            if self.cache_type == "redis":
                self.redis_client.setex(key, ttl, pickle.dumps(value))
            else:
                self.memory_cache[key] = (value, datetime.now(), ttl)
        except Exception as e:
            print(f"[CACHE] Erro ao salvar cache: {e}")
    
    def clear(self):
        """Limpa todo o cache"""
        try:
            if self.cache_type == "redis":
                self.redis_client.flushdb()
            else:
                self.memory_cache.clear()
            print("[CACHE] Cache limpo com sucesso")
        except Exception as e:
            print(f"[CACHE] Erro ao limpar cache: {e}")
    
    def get_embedding_key(self, text: str) -> str:
        """Gera chave para cache de embedding"""
        return f"embed:{self._hash_key(text, OPENAI_EMBED_MODEL)}"
    
    def get_retrieval_key(self, query: str, k: int) -> str:
        """Gera chave para cache de retrieval"""
        return f"retrieval:{self._hash_key(query, k)}"
    
    def get_response_key(self, question: str, top_k: int) -> str:
        """Gera chave para cache de resposta completa"""
        return f"response:{self._hash_key(question, top_k, OPENAI_MODEL)}"


# Inicializa cache manager
cache_manager = CacheManager(cache_type=CACHE_TYPE, redis_url=REDIS_URL)

# =========================
# FastAPI
# =========================
app = FastAPI(title="RAG Query Builder API (OpenAI)", version="1.0.0")


class AskRequest(BaseModel):
    question: str
    top_k: Optional[int] = None  # sobrepõe TOP_K global, opcional
    use_cache: Optional[bool] = True  # permite desabilitar cache por request


class AskResponse(BaseModel):
    tables_used: List[str]
    columns_used: List[str]
    joins_explained: List[str]
    assumptions: List[str]
    sql: str
    retrieved_chunks: int
    model_used: str
    cached: bool = False  # indica se veio do cache


class IngestResponse(BaseModel):
    files: int
    chunks: int
    message: str


class CacheStatsResponse(BaseModel):
    cache_enabled: bool
    cache_type: str
    memory_cache_size: int


def log_env():
    print("[ENV] OPENAI_API_KEY:", "***" if OPENAI_API_KEY else "NOT SET")
    print("[ENV] OPENAI_MODEL:", OPENAI_MODEL)
    print("[ENV] OPENAI_EMBED_MODEL:", OPENAI_EMBED_MODEL)
    print("[ENV] CORPUS_DIR:", str(CORPUS_DIR))
    print("[ENV] TOP_K:", TOP_K)
    print("[ENV] CHUNK_SIZE:", CHUNK_SIZE)
    print("[ENV] TIMEOUT_SECONDS:", TIMEOUT_SECONDS)
    print("[ENV] CACHE_ENABLED:", CACHE_ENABLED)
    print("[ENV] CACHE_TYPE:", CACHE_TYPE)
    if CACHE_TYPE == "redis":
        print("[ENV] REDIS_URL:", REDIS_URL)
    if CHROMA_PERSIST_DIR:
        print("[ENV] CHROMA_PERSIST_DIR:", CHROMA_PERSIST_DIR)
    else:
        print("[ENV] CHROMA_PERSIST_DIR: (in-memory)")
    print("[ENV] CHROMA_COLLECTION:", CHROMA_COLLECTION)


def embed(text: str):
    """Gera embedding usando OpenAI API com cache"""
    cache_key = cache_manager.get_embedding_key(text)
    
    # Tenta buscar do cache
    cached_embedding = cache_manager.get(cache_key)
    if cached_embedding is not None:
        return cached_embedding
    
    # Gera embedding
    response = client.embeddings.create(
        model=OPENAI_EMBED_MODEL,
        input=text
    )
    embedding = response.data[0].embedding
    
    # Salva no cache (24 horas)
    cache_manager.set(cache_key, embedding, ttl=86400)
    
    return embedding


def get_chroma_client():
    if CHROMA_PERSIST_DIR:
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        return chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    return chromadb.Client()


def ensure_collection():
    client_db = get_chroma_client()
    try:
        col = client_db.get_collection(CHROMA_COLLECTION)
    except:
        col = client_db.create_collection(CHROMA_COLLECTION)
    return client_db, col


def chunk_text(text: str, chunk_size: int):
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def ingest_corpus() -> IngestResponse:
    client_db, col = ensure_collection()
    docs, metas, ids, embs = [], [], [], []

    if not CORPUS_DIR.exists():
        return IngestResponse(files=0, chunks=0, message=f"Corpus dir not found: {CORPUS_DIR}")

    files = sorted(CORPUS_DIR.glob("*.md"))
    if not files:
        return IngestResponse(files=0, chunks=0, message=f"No .md files found in {CORPUS_DIR}")

    for p in files:
        content = p.read_text(encoding="utf-8")
        chunks = chunk_text(content, CHUNK_SIZE)
        for k, chunk in enumerate(chunks):
            docs.append(chunk)
            metas.append({"source": p.name, "chunk": k})
            ids.append(f"{p.name}-{k}")
            embs.append(embed(chunk))  # Usa embed com cache

    if docs:
        col.add(documents=docs, metadatas=metas, ids=ids, embeddings=embs)

    return IngestResponse(files=len(files), chunks=len(docs), message="Ingestion completed")


def retrieve(user_input: str, k: int, use_cache: bool = True):
    """Busca documentos relevantes com cache"""
    cache_key = cache_manager.get_retrieval_key(user_input, k)
    
    # Tenta buscar do cache
    if use_cache:
        cached_result = cache_manager.get(cache_key)
        if cached_result is not None:
            return cached_result
    
    # Busca no ChromaDB
    _, col = ensure_collection()
    q_emb = embed(user_input)  # Usa embed com cache
    res = col.query(query_embeddings=[q_emb], n_results=k)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    result = list(zip(docs, metas))
    
    # Salva no cache (6 horas)
    if use_cache:
        cache_manager.set(cache_key, result, ttl=21600)
    
    return result


def build_prompt_with_context(user_input: str, contexts):
    context_text = "\n\n".join(
        [f"[DOC {i + 1} - {m['source']}#chunk{m['chunk']}]\n{c}" for i, (c, m) in enumerate(contexts)]
    )
    instruction = (
        "Use APENAS o que está no contexto abaixo para escolher tabelas e colunas. "
        "Se algo não estiver claro, faça suposições em 'assumptions'. "
        "Responda somente com o JSON no formato solicitado."
    )
    return f"{instruction}\n\n=== CONTEXTO RAG INÍCIO ===\n{context_text}\n=== CONTEXTO RAG FIM ===\n\nSolicitação do usuário: {user_input}\n"


def call_openai(system: str, prompt: str) -> str:
    """Chama OpenAI ChatGPT API"""
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        response_format={"type": "json_object"}  # Força resposta JSON
    )
    return response.choices[0].message.content


def parse_json(text: str):
    try:
        return json.loads(text)
    except:
        # Tenta extrair JSON se houver texto extra
        m = re.search(r"\{[\s\S]*\}\s*$", text)
        if not m:
            raise ValueError("Model response does not contain valid JSON.")
        return json.loads(m.group(0))


@app.on_event("startup")
def on_startup():
    log_env()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": OPENAI_MODEL,
        "embed_model": OPENAI_EMBED_MODEL,
        "cache_enabled": CACHE_ENABLED,
        "cache_type": CACHE_TYPE
    }


@app.get("/cache/stats", response_model=CacheStatsResponse)
def cache_stats():
    """Retorna estatísticas do cache"""
    return CacheStatsResponse(
        cache_enabled=CACHE_ENABLED,
        cache_type=cache_manager.cache_type,
        memory_cache_size=len(cache_manager.memory_cache) if cache_manager.cache_type == "memory" else 0
    )


@app.post("/cache/clear")
def clear_cache():
    """Limpa todo o cache"""
    try:
        cache_manager.clear()
        return {"message": "Cache cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest", response_model=IngestResponse)
def api_ingest():
    try:
        result = ingest_corpus()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/report", response_model=AskResponse)
def api_report(req: AskRequest):
    try:
        k = req.top_k if req.top_k and req.top_k > 0 else TOP_K
        use_cache = req.use_cache if req.use_cache is not None else True
        
        # Verifica cache de resposta completa
        cache_key = cache_manager.get_response_key(req.question, k)
        if use_cache:
            cached_response = cache_manager.get(cache_key)
            if cached_response is not None:
                cached_response.cached = True
                return cached_response
        
        # Processa normalmente
        contexts = retrieve(req.question, k, use_cache=use_cache)
        prompt = build_prompt_with_context(req.question, contexts)
        raw = call_openai(SYSTEM_PROMPT, prompt)
        data = parse_json(raw)

        # Normaliza campos esperados
        response = AskResponse(
            tables_used=data.get("tables_used", []),
            columns_used=data.get("columns_used", []),
            joins_explained=data.get("joins_explained", []),
            assumptions=data.get("assumptions", []),
            sql=data.get("sql", ""),
            retrieved_chunks=len(contexts),
            model_used=OPENAI_MODEL,
            cached=False
        )
        
        # Salva no cache (1 hora)
        if use_cache:
            cache_manager.set(cache_key, response, ttl=3600)
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))