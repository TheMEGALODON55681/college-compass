"""ONNX Runtime replacement for the PyTorch/sentence-transformers encoder,
used only to embed free-text counsellor queries at request time (see
models/counsellor_retrieval.py's _semantic_records). /similar never needs an
encoder at all - see models/similarity.py.

Same weights as the FAISS index was built with (the plain fp32 export at
sentence-transformers/all-MiniLM-L6-v2's onnx/model.onnx on the Hub, not one
of the quantized/optimized variants also published there), so it must
produce the same vectors. Reproduces sentence-transformers' default pipeline
exactly, per that model's own 1_Pooling/config.json and
sentence_bert_config.json: tokenize (max_seq_length 256), run the ONNX
session, mean-pool the token embeddings over the attention mask, L2
normalize. Getting pooling or normalization wrong is the single most likely
way to silently break retrieval - verified once, before torch/sentence-
transformers were removed from requirements.txt, against 50+ queries (see
the Phase 1 report for worst-case cosine similarity and FAISS top-10
agreement). Not re-checked on every run: once torch is gone from
requirements.txt, nothing in this environment can still load the old path
to compare against.

Exposes the same .encode(texts, normalize_embeddings=True) surface as
SentenceTransformer.encode, so callers don't change.
"""

import os

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "artifacts", "onnx_encoder")
MODEL_PATH = os.path.join(ARTIFACT_DIR, "model.onnx")
TOKENIZER_PATH = os.path.join(ARTIFACT_DIR, "tokenizer.json")
MAX_SEQ_LENGTH = 256
DEFAULT_BATCH_SIZE = 32
EMBEDDING_DIM = 384


class OnnxSentenceEncoder:
    def __init__(self, model_path=MODEL_PATH, tokenizer_path=TOKENIZER_PATH):
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=MAX_SEQ_LENGTH)
        self.tokenizer.enable_padding(length=None)
        self._input_names = {i.name for i in self.session.get_inputs()}

    def _mean_pool(self, token_embeddings, attention_mask):
        mask = attention_mask[..., np.newaxis].astype(np.float32)
        summed = (token_embeddings * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
        return summed / counts

    def _encode_batch(self, texts):
        encodings = self.tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

        onnx_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in self._input_names:
            onnx_inputs["token_type_ids"] = np.zeros_like(input_ids)

        token_embeddings = self.session.run(None, onnx_inputs)[0]
        return self._mean_pool(token_embeddings, attention_mask)

    def encode(self, texts, normalize_embeddings=True, batch_size=DEFAULT_BATCH_SIZE):
        """Matches SentenceTransformer.encode's calling convention: a bare
        string returns a single 1-D vector, a list returns a 2-D array (one
        row per text, in order), and an empty list returns an empty 2-D
        array - all without an ONNX call, matching the old encoder's
        behavior for inputs the running app never actually sends today
        (always exactly one string in a list) but that the interface
        contract still promises.
        """
        input_was_string = isinstance(texts, str)
        texts = [texts] if input_was_string else list(texts)

        if not texts:
            embeddings = np.empty((0, EMBEDDING_DIM), dtype=np.float32)
        else:
            batches = [self._encode_batch(texts[i : i + batch_size]) for i in range(0, len(texts), batch_size)]
            embeddings = np.concatenate(batches, axis=0)

        if normalize_embeddings and embeddings.size:
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = embeddings / np.clip(norms, a_min=1e-9, a_max=None)

        embeddings = embeddings.astype(np.float32)
        return embeddings[0] if input_was_string else embeddings


def _demo():
    encoder = OnnxSentenceEncoder()
    vectors = encoder.encode(["good CS options near my rank", "IIT Bombay computer science"])
    print(f"encoded {len(vectors)} texts, dim {vectors.shape[1]}, norms {np.linalg.norm(vectors, axis=1)}")


if __name__ == "__main__":
    _demo()
