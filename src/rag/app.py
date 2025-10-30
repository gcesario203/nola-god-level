import os
import json
import re
from pathlib import Path
from typing import List, Optional

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
# FastAPI
# =========================
app = FastAPI(title="RAG Query Builder API (OpenAI)", version="1.0.0")


class AskRequest(BaseModel):
    question: str
    top_k: Optional[int] = None  # sobrepõe TOP_K global, opcional


class AskResponse(BaseModel):
    tables_used: List[str]
    columns_used: List[str]
    joins_explained: List[str]
    assumptions: List[str]
    sql: str
    retrieved_chunks: int
    model_used: str


class IngestResponse(BaseModel):
    files: int
    chunks: int
    message: str


def log_env():
    print("[ENV] OPENAI_API_KEY:", "***" if OPENAI_API_KEY else "NOT SET")
    print("[ENV] OPENAI_MODEL:", OPENAI_MODEL)
    print("[ENV] OPENAI_EMBED_MODEL:", OPENAI_EMBED_MODEL)
    print("[ENV] CORPUS_DIR:", str(CORPUS_DIR))
    print("[ENV] TOP_K:", TOP_K)
    print("[ENV] CHUNK_SIZE:", CHUNK_SIZE)
    print("[ENV] TIMEOUT_SECONDS:", TIMEOUT_SECONDS)
    if CHROMA_PERSIST_DIR:
        print("[ENV] CHROMA_PERSIST_DIR:", CHROMA_PERSIST_DIR)
    else:
        print("[ENV] CHROMA_PERSIST_DIR: (in-memory)")
    print("[ENV] CHROMA_COLLECTION:", CHROMA_COLLECTION)


def embed(text: str):
    """Gera embedding usando OpenAI API"""
    response = client.embeddings.create(
        model=OPENAI_EMBED_MODEL,
        input=text
    )
    return response.data[0].embedding


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
            embs.append(embed(chunk))

    if docs:
        col.add(documents=docs, metadatas=metas, ids=ids, embeddings=embs)

    return IngestResponse(files=len(files), chunks=len(docs), message="Ingestion completed")


def retrieve(user_input: str, k: int):
    _, col = ensure_collection()
    q_emb = embed(user_input)
    res = col.query(query_embeddings=[q_emb], n_results=k)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    return list(zip(docs, metas))


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
    return {"status": "ok", "model": OPENAI_MODEL, "embed_model": OPENAI_EMBED_MODEL}


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
        contexts = retrieve(req.question, k)
        prompt = build_prompt_with_context(req.question, contexts)
        raw = call_openai(SYSTEM_PROMPT, prompt)
        data = parse_json(raw)

        # Normaliza campos esperados
        return AskResponse(
            tables_used=data.get("tables_used", []),
            columns_used=data.get("columns_used", []),
            joins_explained=data.get("joins_explained", []),
            assumptions=data.get("assumptions", []),
            sql=data.get("sql", ""),
            retrieved_chunks=len(contexts),
            model_used=OPENAI_MODEL
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
