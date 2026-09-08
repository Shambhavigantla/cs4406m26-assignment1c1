"""From-scratch BM25 (Okapi): postings-list inverted index + vectorized scoring.

Scores a query by touching only the postings of its terms (via numpy's
vectorized np.add.at), not by scanning the whole corpus per query -- see
SPEC.md Q2 section 1 for why that matters at the scale this pipeline runs at
(tens of thousands of per-user queries).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re

import numpy as np
import pandas as pd


def tokenize(text) -> list[str]:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    return re.findall(r"\w+", text.lower())


@dataclass
class BM25Index:
    doc_ids: np.ndarray
    doc_len: np.ndarray
    avgdl: float
    idf: dict[str, float]
    postings: dict[str, tuple[np.ndarray, np.ndarray]]
    doc_norm: np.ndarray
    k1: float
    b: float

    @property
    def n_docs(self) -> int:
        return len(self.doc_ids)


def build_index(doc_ids, doc_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75) -> BM25Index:
    n_docs = len(doc_tokens)
    doc_len = np.array([len(tokens) for tokens in doc_tokens], dtype=np.float64)
    avgdl = doc_len.mean()

    postings_lists: dict[str, list[list[int]]] = defaultdict(lambda: [[], []])
    doc_freq: dict[str, int] = defaultdict(int)
    for doc_idx, tokens in enumerate(doc_tokens):
        for term, tf in Counter(tokens).items():
            postings_lists[term][0].append(doc_idx)
            postings_lists[term][1].append(tf)
            doc_freq[term] += 1

    postings = {
        term: (np.array(idxs, dtype=np.int64), np.array(tfs, dtype=np.float64))
        for term, (idxs, tfs) in postings_lists.items()
    }

    # Non-negative IDF variant (Lucene/BM25+): log((N - df + 0.5)/(df + 0.5) + 1).
    # The classic Robertson/Sparck-Jones IDF goes negative for terms in more
    # than half the corpus; the +1 guarantees idf(term) >= 0 for every term.
    idf = {
        term: np.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
        for term, df in doc_freq.items()
    }

    doc_norm = k1 * (1 - b + b * doc_len / avgdl)

    return BM25Index(
        doc_ids=np.asarray(doc_ids),
        doc_len=doc_len,
        avgdl=avgdl,
        idf=idf,
        postings=postings,
        doc_norm=doc_norm,
        k1=k1,
        b=b,
    )


def get_scores(index: BM25Index, query_tokens: list[str]) -> np.ndarray:
    scores = np.zeros(index.n_docs, dtype=np.float64)
    # sorted(set(...)), not set(...): Python randomizes string hashing per
    # process, so a bare set iterates its terms in a different order in every
    # run. Float addition is not associative, so the accumulation order below
    # changes the last bits of each score -- identical input produced scores
    # differing by ~5e-16 relative across two runs (measured; within-impression
    # rankings were unaffected, but the values were not reproducible).
    # Sorting costs nothing on a query-sized token set and makes BM25
    # bit-reproducible run to run.
    for term in sorted(set(query_tokens)):
        entry = index.postings.get(term)
        if entry is None:
            continue
        doc_idx, tf = entry
        contrib = index.idf[term] * tf * (index.k1 + 1) / (tf + index.doc_norm[doc_idx])
        np.add.at(scores, doc_idx, contrib)
    return scores


def top_k(index: BM25Index, query_tokens: list[str], k: int) -> list[tuple[str, float]]:
    if not query_tokens:
        return []
    scores = get_scores(index, query_tokens)
    n_docs = index.n_docs
    if k >= n_docs:
        top_idx = np.argsort(-scores)
    else:
        part = np.argpartition(-scores, k)[:k]
        top_idx = part[np.argsort(-scores[part])]
    return [(index.doc_ids[i], float(scores[i])) for i in top_idx]
