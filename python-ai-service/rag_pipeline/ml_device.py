"""Device selection for local embedding/reranker models.

SAP BTP runs CPU-only PyTorch. On macOS, MPS (Metal) + Gunicorn fork causes
SIGABRT and objc_initializeAfterForkError crashes — always use CPU here.
Override for experiments: ML_DEVICE=cuda|mps|cpu
"""
import os

ML_DEVICE = os.getenv("ML_DEVICE", "cpu")
