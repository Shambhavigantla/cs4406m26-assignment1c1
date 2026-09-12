# Assignment 1 Spec

Covers Q1–Q9 of `assignments/Assignment1_v1.pdf`. Q1–Q5 are implemented;
Q6–Q9 are design only, pending implementation.

# Q1 — Reproducible Data Pipeline

## 1. Goal

One pipeline, run once per dataset track, that turns the raw EB-NeRD demo,
EB-NeRD small, and MIND-small files into three unified-schema tables per
dataset — `articles`, `behaviors`, `history` — with a `split` column
(`train`/`val`/`test`) assigned by time, rebuildable from raw files with a
single command.

The dataset tracks are **never merged**: outputs stay in separate per-dataset
directories with dataset-namespaced IDs. Only the schema (column names/types) and the
code that produces it are shared. EB-NeRD small is an additive, independent
track alongside EB-NeRD demo (not a replacement) — its own namespace prefix
(`ebnerd_small_<native_id>`) and its own `data/processed/ebnerd_small/`
directory, built by the same `build_ebnerd_*` functions called with a
different `prefix` argument.

## 2. Unified schema

Namespacing: every ID is prefixed with its source dataset so cross-dataset joins can
never silently collide — `ebnerd_<native_id>` / `mind_<native_id>`. `<native_id>` is
kept in its original type/format for traceability (e.g. `ebnerd_123`, `mind_N55528`).

Only columns needed for Q1–Q4 are included. Dataset-specific columns that aren't
needed yet (EB-NeRD's `sentiment_score`, `entity`/`topic` tags, user demographics;
MIND's KG entity embeddings) are **not** part of this schema — they can be added as
nullable extension columns later if a later question needs them, per the
no-speculative-features guideline. `body` is kept because EB-NeRD has it and it's a
natural bonus signal for BM25/semantic retrieval later, even though MIND's is always
null.

### `articles` — one row per article

| Column | Type | Source: EB-NeRD | Source: MIND |
|---|---|---|---|
| `article_id` | str | `"ebnerd_" + article_id` | `"mind_" + news_id` |
| `dataset` | str | `"ebnerd"` | `"mind"` |
| `title` | str | `title` | `title` |
| `abstract` | str, nullable | `subtitle` | `abstract` |
| `body` | str, nullable | `body` | `null` (licensing — see README) |
| `category` | str | `category_str` | `category` |
| `subcategory` | str, nullable | `subcategory[0]` if present else null (EB-NeRD allows multiple; keep first, drop rest — not needed for Q1–Q4) | `subcategory` |
| `published_time` | datetime, nullable | `published_time` | `null` (not provided) |

### `behaviors` — one row per impression

| Column | Type | Source: EB-NeRD | Source: MIND |
|---|---|---|---|
| `impression_id` | str | `"ebnerd_" + impression_id` | `"mind_" + impression_id` |
| `dataset` | str | `"ebnerd"` | `"mind"` |
| `user_id` | str | `"ebnerd_" + user_id` | `"mind_" + user_id` |
| `impression_time` | datetime | `impression_time` | parsed `time` (`MM/DD/YYYY H:MM:SS AM/PM`) |
| `article_ids_inview` | list[str] | `article_ids_inview`, namespaced | `impressions` tokens (all), namespaced |
| `article_ids_clicked` | list[str] | `article_ids_clicked`, namespaced | `impressions` tokens with label `1`, namespaced |
| `session_id` | str, nullable | `"ebnerd_" + session_id` | `null` (not provided) |
| `split` | str | assigned by pipeline: `train`/`val`/`test` | assigned by pipeline: `train`/`val`/`test` |

### `history` — one row per user (pre-collection-window click history)

| Column | Type | Source: EB-NeRD | Source: MIND |
|---|---|---|---|
| `user_id` | str | `"ebnerd_" + user_id` | `"mind_" + user_id` |
| `dataset` | str | `"ebnerd"` | `"mind"` |
| `article_id_sequence` | list[str] | `article_id_fixed`, namespaced, chronological | first non-null `history` field seen for that user in `behaviors.tsv`, space-split, namespaced (order-only; see note) |
| `timestamp_sequence` | list[datetime], nullable | `impression_time_fixed` | `null` (MIND gives order only, no per-click timestamps) |
| `read_time_sequence` | list[float], nullable | `read_time_fixed` | `null` (not provided) |
| `scroll_percentage_sequence` | list[float], nullable | `scroll_percentage_fixed` | `null` (not provided) |

**MIND history note**: unlike EB-NeRD's dedicated `history.parquet`, MIND's `history`
field is embedded per-row in `behaviors.tsv` and is identical across all of a given
user's rows (it always describes clicks from *before* the log period, not
incrementally up to each impression). The pipeline must verify this invariant while
building the table (assert one distinct non-null `history` string per `user_id`) and
fail loudly if it doesn't hold, rather than silently picking one.

## 3. Temporal split

All three dataset tracks already ship two chronologically contiguous provider
splits (train, then dev/validation) — there is no provider test split.
Verified date ranges (from the actual files on disk):

| | provider `train` | provider `dev`/`validation` |
|---|---|---|
| EB-NeRD demo | 2023-05-18 07:00 → 2023-05-25 07:00 (7 days) | 2023-05-25 07:00 → 2023-06-01 07:00 (7 days) |
| EB-NeRD small | 2023-05-18 07:00 → 2023-05-25 07:00 (7 days, identical range to demo) | 2023-05-25 07:00 → 2023-06-01 07:00 (7 days, identical range to demo) |
| MIND-small | 2019-11-09 00:00 → 2019-11-15 00:00 (6 days) | 2019-11-15 00:00 → 2019-11-16 00:00 (1 day) |

Design decision: treat the provider's dev/validation split as our held-out **test**
set (untouched until final evaluation), and carve **our** validation set from the
last day of the provider's train split by time — never randomly. Concretely:

- EB-NeRD (demo and small — identical provider date range, so identical
  cutoffs): `train` = impressions before `2023-05-24 07:00:00`; `val` =
  impressions in `[2023-05-24 07:00:00, 2023-05-25 07:00:00)`; `test` = all
  of provider `validation/`.
- MIND: `train` = impressions before `2019-11-14 00:00:00`; `val` = impressions in
  `[2019-11-14 00:00:00, 2019-11-15 00:00:00)`; `test` = all of provider `dev/`.

Cutoffs are named constants (per dataset) in the split module, not hardcoded inline,
so they're easy to audit or adjust later (e.g. if 1 day of validation proves too
small/noisy).

## 4. Feature store layout

```
data/processed/ebnerd/articles.parquet
data/processed/ebnerd/behaviors.parquet     # includes `split` column
data/processed/ebnerd/history.parquet
data/processed/ebnerd/manifest.json         # row counts, split date cutoffs, schema version, build timestamp
data/processed/ebnerd_small/articles.parquet
data/processed/ebnerd_small/behaviors.parquet
data/processed/ebnerd_small/history.parquet
data/processed/ebnerd_small/manifest.json
data/processed/ebnerd_large/articles.parquet
data/processed/ebnerd_large/behaviors.parquet
data/processed/ebnerd_large/history.parquet
data/processed/ebnerd_large/manifest.json
data/processed/mind/articles.parquet
data/processed/mind/behaviors.parquet
data/processed/mind/history.parquet
data/processed/mind/manifest.json
data/processed/mind_large/articles.parquet
data/processed/mind_large/behaviors.parquet
data/processed/mind_large/history.parquet
data/processed/mind_large/manifest.json
```

`ebnerd_large` and `mind_large` are two more additive, independent dataset
tracks (own namespace prefix, own `data/processed/{name}/` directory) —
same "shared code, different `prefix` argument" pattern as `ebnerd_small`,
built by the same `build_ebnerd_*`/`build_mind_*` functions. At real scale:
`ebnerd_large` is 125,541 articles / ~24.6M behavior rows / ~975K users;
`mind_large` (from `MINDlarge_train`+`MINDlarge_dev`, not `MINDsmall`) is
~104K articles / ~2.6M behavior rows / ~750K users. Both share their
respective demo/small counterpart's exact provider date range, so the same
`EBNERD_TRAIN_END`/`EBNERD_TEST_START`/`MIND_TRAIN_END`/`MIND_TEST_START`
cutoffs apply — verified directly on the raw files, not assumed.

`data/` is added to `.gitignore` (matches Q8's "no large files / `data/`" policy).
Raw inputs stay wherever they already are on disk (`ebnerd_demo/`, `ebnerd_small/`,
`MINDsmall_train/`, `MINDsmall_dev/`), also already gitignored — the pipeline reads
from there and never copies raw files into `data/`.

## 5. Implementation shape

Per `CLAUDE.md`, all code is notebook-based: one markdown title + one feature cell +
one pytest-style test cell per step, matching the existing style in
`src/explore_datasets.ipynb`. Q1 gets its own notebook, `src/build_pipeline.ipynb`,
with this cell sequence (each numbered item = title/feature/test cell triple):

1. Load raw EB-NeRD → unify to `articles` / `behaviors` / `history` (three
   title/feature/test triples, one per table)
2. Load raw MIND → unify to `articles` / `behaviors` / `history` (three more triples)
3. Temporal split — apply the cutoffs from #3, add `split` column to each dataset's
   `behaviors` table; test asserts per-split time ranges are non-overlapping and
   monotonically ordered `train < val < test` (this doubles as the Q9 leakage
   boundary test for split-level leakage)
4. History/behavior leakage test — for EB-NeRD, assert every timestamp in a user's
   `history.timestamp_sequence` is strictly earlier than every `impression_time` for
   that user in `behaviors` (verified on real data: 0/1590 violations). For MIND,
   content-overlap between history and `article_ids_inview` is **not** a valid
   leakage signal — verified empirically that ~11% of users legitimately have
   popular/previously-seen articles reappear as candidates, since candidate sets
   aren't filtered against history. The real, checkable invariant for MIND is
   structural: every user must have exactly **one** distinct `history` string across
   all of their impression rows (train+dev combined) — this is what proves history
   is a fixed pre-window snapshot rather than something that could be accidentally
   reconstructed per-impression from later data. Verified on real data: 0/91,935
   users violate this. This check is already required to build `mind_history` (#2
   step 6) and is additionally asserted as an explicit test here.
5. Write feature store — serialize all parquet files + manifests to `data/processed/`
6. One-command rebuild entrypoint

**One-command rebuild**: a thin `build_pipeline.py` at the repo root (as literally
named in the assignment) that shells out to
`jupyter nbconvert --to notebook --execute --inplace src/build_pipeline.ipynb`,
so the documented command is `uv run python build_pipeline.py`. Executing the
notebook top-to-bottom re-runs every feature+test cell, so a failed assertion in any
test cell aborts the rebuild — that's the pipeline's correctness gate. README gets a
one-line "Rebuild the feature store" section pointing at this command.

Progress during a rebuild is additionally mirrored to a plain-text
`build_progress.log` at the repo root (gitignored, truncated at the start of
each run) — a timestamped line after every dataset/table/write step,
independent of the notebook's own saved output (`nbconvert --execute
--inplace` only writes `build_pipeline.ipynb` back to disk once, at the very
end of a successful run, so it can't itself be tailed mid-run). Lets a
rebuild's progress be watched externally (e.g. `tail -f build_progress.log`)
without touching Jupyter, and lets a specific dataset's persistence be
confirmed independently by checking whether its `manifest.json` exists yet.

### `polars`, not `pandas`, for raw parsing and the prefix-namespacing transforms

`ebnerd_large` (~24.6M behavior rows, 125,541 articles, ~975K users) and
`mind_large` (~2.6M behavior rows, ~104K articles, ~750K users) are two more
orders of magnitude larger than `ebnerd`/`ebnerd_small`/`mind`. At that
scale, the original `pandas.read_csv` (MIND's TSVs) plus
`.apply()`/`.map()`-based prefix-namespacing (adding the dataset prefix to
every `article_id` inside every list column) became the actual bottleneck —
Python-object overhead per string/list element, not I/O. `polars` replaces
both: `pl.read_csv(..., separator="\t")` for MIND's TSVs (multi-threaded,
not single-threaded like pandas' C parser) and its expression API
(`list.eval`, `pl.element()`) for the prefix-namespacing, which runs as a
vectorized, multi-threaded Rust operation instead of a Python loop per list
element. Every `build_*` function still returns a plain `pandas.DataFrame`
(`.to_pandas()` at the end), so the temporal split, leakage checks, and
tests downstream are unchanged and still operate on pandas — only raw
loading and the unify-to-schema transform itself changed.

MIND's `impressions` field (`news_id-label` tokens packed into one
space-separated string) is parsed via an explode → transform → group-by →
join-back pattern instead of a per-row Python function
(`split_impressions` + `.map()`): explode each impression's tokens into
their own rows, extract `id`/`label` per token via `str.slice` from each
end (`"N55689-1"` → id `"N55689"`, label `"1"` — matches the original
`rsplit("-", 1)` semantics exactly, robust to a hypothetical literal `-` in
an id), filter to clicked tokens, then re-aggregate both candidate and
clicked lists back per impression via `group_by(row_id).agg(...)` and join
back onto the original row order (`.sort("row_id")` after the join — polars
left-joins aren't documented to preserve row order, and Q5's submission
format depends on it). Every step is a vectorized polars operation, not a
Python loop per row per token.

**Correctness fix found along the way, not just a speedup**: `polars.read_csv(...,
quote_char=None)` is used for MIND's TSVs instead of pandas' default
CSV-quote handling. `news.tsv` is a raw TSV with no CSV-style escaping
convention, but pandas' C parser applies `quotechar='"'` semantics
regardless, which silently strips literal `"` characters from ~62 titles /
~628 abstracts across MIND's catalog (verified directly against the
already-built `mind`/`mind_large` catalogs — e.g. a title like `"It changed
everything," Oklahoma woman...` loses both quote marks under the old
pandas-based parsing). `quote_char=None` disables that interpretation, so
these fields round-trip byte-for-byte. This has no effect on BM25 (its
`\w+` tokenizer already discards punctuation) and a negligible one on
embeddings (<1% of articles, punctuation-only difference, averaged over
tens of thousands of impressions in any reported metric) — not something
that required re-running already-computed Q2-Q5 results.

### Parquet writer: `polars.write_parquet`, not `pandas.to_parquet`

`write_feature_store` writes via `pl.from_pandas(df).write_parquet(path)`,
not `df.to_parquet(path)`. This is a real bug fix, found directly: writing
`ebnerd_large`'s `history.parquet` (974,791 rows, nested `list<datetime>`/
`list<float>` columns) via pandas' own writer "succeeded" with no error at
write time, but the resulting file then failed on read-back with
`pyarrow.ArrowNotImplementedError: Nested data conversions not implemented
for chunked array outputs` — a pyarrow limitation combining chunked nested
list arrays that only surfaces at this row count (`ebnerd`/`ebnerd_small`'s
much smaller history tables never hit it; `ebnerd_large`'s own
`behaviors.parquet`, with different nested column types, also didn't hit
it). Verified directly: the identical DataFrame written via
`pl.from_pandas(...).write_parquet(...)` instead reads back via
`pd.read_parquet` with no error, byte-identical data.

### Memory management at `ebnerd_large`/`mind_large` scale

Four attempts at running this pipeline against all five dataset tracks
OOM-killed the kernel (16GB RAM on the reference machine), each time
narrowing the actual cause:

1. **First crash**: by write time, every dataset's raw `polars` frames and
   built `pandas` tables were simultaneously resident, plus a transient
   `polars` copy during each write's `pl.from_pandas()` conversion. Fixed
   by freeing memory as early as it's safe to: each raw `polars` frame
   (`{dataset}_articles_raw`, `{dataset}_behaviors_raw`,
   `{dataset}_history_raw`) is `del`eted (+ `gc.collect()`) immediately
   after its last consumer runs (most are only needed by their own
   immediately-following schema test, for a `len(raw)` comparison; MIND's
   `_behaviors_raw` frames are the exception, needed through both
   `build_mind_history` and the Q9 leakage-check cell, so freed at the end
   of that cell instead); and `write_feature_store` is called and its
   result immediately deleted **one dataset at a time** (write `ebnerd` →
   delete its tables → write `ebnerd_small` → delete → ...) instead of
   building all five datasets' tables in memory and writing them at the
   end.
2. **Second crash, same root cause at a smaller scope**: even with the
   fixes above, writing `ebnerd_large` (the single largest dataset) still
   crashed, because `mind`/`mind_large`'s built tables were *also* resident
   at that point — MIND's build cells run unconditionally before any
   writing starts in the notebook's cell order, regardless of write order.
   Freeing-as-you-write only bounds peak memory to "all five datasets that
   have been built so far," which by `ebnerd_large`'s write time is still
   all five.
3. **Third crash, isolated down to a single dataset**: restructured the
   notebook into two fully separate families, processed one after the
   other — EB-NeRD (build → temporal split → leakage-check → write → free,
   for `ebnerd`/`ebnerd_small`/`ebnerd_large` together) completely before
   MIND's build cells even run, then MIND (`mind`/`mind_large`) the same
   way. The temporal-split and leakage-check cells, previously one shared
   cell each across all five datasets, are now two cells each (EB-NeRD-only,
   MIND-only); `write_feature_store` and `assign_split` are defined once
   (in EB-NeRD's cells) and reused as-is in MIND's. This capped peak memory
   to one *family's* worth of data at a time — but writing `ebnerd_large`
   *alone* (no MIND data resident at all) still crashed, isolating the true
   cause to `ebnerd_large`'s own `behaviors` table (~24.6M rows): holding
   its existing `pandas` representation *and* building a whole new `polars`
   one via `pl.from_pandas()` simultaneously exceeds 16GB by itself,
   independent of anything else in memory.
4. **Fix**: `write_parquet_chunked` replaces the single
   `pl.from_pandas(df).write_parquet(path)` call for tables above a row
   threshold — convert and write each row-chunk to its own temp parquet
   file (bounding the transient pandas+polars overlap to one chunk's size,
   not the whole table), then merge the chunk files into the final path via
   `polars.scan_parquet(...).sink_parquet(...)`, polars' streaming engine,
   which merges without materializing every chunk in memory at once.
   Verified directly on synthetic data with the same nested
   `list<str>`/`list<datetime>` column shapes that a chunk-merged file
   still reads back via `pd.read_parquet` with no error — doesn't
   reintroduce the earlier `ArrowNotImplementedError` chunked-array bug
   (#2 above), since each chunk file is itself a single, internally-
   consistent `polars` write (the exact pattern already proven safe there),
   not multiple row groups appended incrementally into one file.
5. **Fifth crash, at the initial 2,000,000-row chunk size**: still failed at
   the same write step. Diagnosed as Windows/CPython memory fragmentation
   from the churn of building many nested-list `pandas` objects rather than
   raw insufficiency (~12GB nominally free at the time of a ~2.6GB
   allocation failure). Fixed by reducing `chunk_rows` to 300,000 and adding
   a `log_progress` line per chunk written, so a recurrence would identify
   the exact failing chunk rather than just "OOM somewhere in this table."

**`BUILD_LARGE_ONLY` flag**: threaded through every EB-NeRD/MIND build+test/
split/leakage/write cell as `if not BUILD_LARGE_ONLY: ...` guards. When
`True` (used for the run that finally succeeded, below), `ebnerd`/
`ebnerd_small`/`mind` are skipped entirely — not rebuilt with possibly-stale
logic, not written to — while `ebnerd_large`/`mind_large` still build/write
unconditionally; the two write cells set an unwritten path variable for a
skipped dataset instead of ever calling `write_feature_store()` for it, so
those three directories are provably untouched rather than merely
skipped-by-convention. Verified directly on a real run: `ebnerd`/
`ebnerd_small`/`mind`'s `articles.parquet`/`behaviors.parquet`/
`history.parquet` mtimes all predated that run's own start timestamp.

**Confirmed successful build** (300,000-row chunks, `BUILD_LARGE_ONLY=True`):
`ebnerd_large` — 125,541 articles, 24,630,275 behaviors (10,384,901 train /
1,678,989 val / 12,566,385 test), 974,791 history rows. `mind_large` —
104,151 articles, 2,609,219 behaviors (1,801,231 train / 431,517 val /
376,471 test), 750,434 history rows. Both `manifest.json`s present; the
final round-trip test passed for all five dataset tracks.

The final round-trip test (`test_feature_store_roundtrip`) reads expected
row counts from each dataset's persisted `manifest.json` rather than the
original in-memory DataFrames, since those are deliberately no longer
resident by the time this test runs (from either family) — `manifest.json`
was itself written from the same `len(articles)` etc. at write time, so
it's an equally trustworthy source of truth without needing to keep the
DataFrames alive.

## 6. Dependencies

`polars` (`uv add polars`) — added for raw parsing, the prefix-namespacing
transforms, and parquet writing at `ebnerd_large`/`mind_large` scale (see
above for why). Everything else fits within `numpy`/`pandas`/`pyarrow`,
already declared in `pyproject.toml`.

## 7. Open questions / risks (flagged, not blocking)

- MIND's `history` field being null for cold-start users means those users get an
  empty `article_id_sequence` in `history` rather than no row at all — every
  `user_id` seen in `behaviors` should still get a `history` row (possibly all-empty
  lists) so downstream joins (Q2/Q3) don't need special-case null-row handling.
- EB-NeRD's `subcategory` can hold multiple IDs; taking only the first is a
  simplification — acceptable for Q1 since nothing here depends on it yet, but worth
  a one-line callout in the eventual design note (Q6) if it matters later.

# Q2 — Lexical Candidate Generation (BM25)

## 1. Approach

From-scratch BM25 (Okapi), no third-party BM25 library. Implemented as a
proper importable module, `src/cs4406m26_assignment1c1/bm25.py` (not inline
notebook cells like the rest of the project) — a deliberate exception to the
"all code in notebooks" convention, since this is a reusable, unit-testable
component with a real performance requirement (below), not a one-off analysis
step.

Two library options were evaluated and rejected before this: a hand-rolled
implementation using `rank-bm25`'s `BM25Okapi` purely to fit/validate `idf`,
`doc_len`, `avgdl`, paired with our own postings-list scoring. Both were
dropped because a from-scratch implementation performs just as well without
the extra dependency — verified below.

**Performance is the reason this is hand-built rather than a call to a
library's own scoring method.** `rank_bm25.BM25Okapi.get_scores` is O(corpus
size) per query token — for each token it does a Python-level `doc.get(term)`
lookup across *every* document's `doc_freqs` dict, not a sparse postings
lookup. Measured directly on MIND's 65,238-article corpus: ~2.9 seconds for a
single 20-title query. At the volume this pipeline needs (once per val/test
user — tens of thousands), that extrapolates to 40+ hours. `bm25.py`'s own
postings-list index — `term -> (doc_idx array, tf array)`, scored with
`numpy`'s `np.add.at` over only the documents that actually contain each query
term, then top-K selected via `np.argpartition` (not a Python-level `heapq` +
key function, which is also slow at corpus scale) — measured at ~5ms/query on
the same corpus: ~6 minutes extrapolated across all of MIND's val/test users,
well under a minute for EB-NeRD's smaller corpus and user count.

IDF uses the non-negative variant: `log((N - df + 0.5)/(df + 0.5) + 1)`. The
classic Robertson/Sparck-Jones IDF goes negative for terms appearing in more
than half the corpus; the `+1` guarantees `idf(term) >= 0` for every term.

## 2. Scope

Two independent BM25 indexes, one per dataset, each built over that dataset's
full `articles` table (all articles — articles aren't split, only `behaviors`
is). Same "shared code, separate runs per dataset" pattern as Q1.

## 3. Corpus text & tokenization

Corpus text is `title + " " + abstract` only — never `body` (Q2 says "titles
and abstracts"; MIND has no body at all per the Q1 schema). `abstract` must be
`.fillna("")`'d before concatenation: ~5.2% of MIND articles (3,415/65,238) have
a null abstract, and naive string concatenation would propagate NaN, silently
zeroing those articles' tokens/doc length and skewing `avgdl`. EB-NeRD has zero
abstract nulls.

Tokenizer: `re.findall(r"\w+", text.lower())`. Python's `re` is Unicode-aware by
default, so this correctly keeps Danish `æøå`/`ÆØÅ` as word characters under
`\w` and folds case correctly for both languages — no new dependency, no
stemming/stopword removal. Accepted imprecision: hyphens/apostrophes split
words (e.g. `harry's` → `harry`, `s`).

## 4. Query construction

Concatenate the **titles** of a user's most recent `RECENT_N_CLICKS = 20`
clicks from `history.article_id_sequence` (a named, adjustable constant).
`timestamp_sequence` is chronologically ascending, so "most recent N" =
`sequence[-20:]`, the *last* N elements, not the first. Median history length
is 71 (EB-NeRD) / 12 (MIND) — a fixed modest window keeps queries focused on
recent interest and comparable across datasets rather than dominated by
EB-NeRD's longer histories.

Cold-start users (empty `article_id_sequence` — 0 in EB-NeRD demo, 0 in
EB-NeRD small, 1,770 in MIND) produce no query and are excluded from the recall@K aggregate, with
their impression count reported separately per split; cold-start-vs-warm
slicing itself is Q4's job.

## 5. Candidate generation semantics

BM25 retrieves its own top-K from the whole article catalog — this is not a
re-ranking of the impression's given `article_ids_inview`. Recall@K checks
whether `article_ids_clicked` appears in that independently-retrieved top-K.

## 6. Retrieval caching

Since the query depends only on the user's fixed pre-window `history`
(identical for every impression of that user), compute `get_scores` **once
per user** at `k=200`, then derive recall@50/@100/@200 as prefixes of that
single sorted list. This makes `top-50 ⊆ top-100 ⊆ top-200` true by
construction and avoids 3× redundant scoring.

Only users appearing in the `val` or `test` splits of `behaviors` need
retrieval computed (recall@K isn't reported on `train`); extending to
train-split users is deferred to whichever of Q3/Q4 needs it.

## 7. Recall@K definition

Fractional multi-relevant, not binary hit/miss: `article_ids_clicked` is not
always singleton — up to 7 clicks/impression in EB-NeRD, up to 35 in MIND (a
third of MIND impressions have multiple clicks). Per impression:

```
recall@K(impression) = |clicked ∩ top-K| / |clicked|
```

Macro-averaged over included (non-cold-start) impressions, computed for
`split ∈ {val, test}` × `K ∈ {50, 100, 200}`.

## 8. Persistence

Mirrors Q1's `manifest.json` conventions:

```
data/processed/{dataset}/bm25_topk.parquet
  user_id                str
  dataset                str
  n_retrieved            int
  retrieved_article_ids  list[str]    # score-descending
  retrieved_scores       list[float]  # parallel to retrieved_article_ids
data/processed/{dataset}/bm25_metrics.json
  schema_version, build_timestamp
  hyperparameters: {k1, b, recent_n_clicks, topk_max}
  recall_at_k: {val: {50, 100, 200}, test: {50, 100, 200}}
  n_impressions: {val: {total, evaluated, excluded_coldstart}, test: {...}}
  scope: "val_test_users_only"
```

Keyed by user, not impression, to avoid storing duplicate retrieval results
across a user's many impressions.

## 9. Implementation shape

The BM25 implementation itself (`tokenize`, `build_index`, `get_scores`,
`top_k`) lives in `src/cs4406m26_assignment1c1/bm25.py`, a plain importable
module (see #1 for why this one component breaks from the notebook-only
convention). Everything else — loading the feature store, query construction,
retrieval caching, evaluation, persistence — is notebook cells, in
`src/bm25_retrieval.ipynb`, following `build_pipeline.ipynb`'s
markdown/feature/test cell convention, with `bm25_retrieval.py` as the
one-command entrypoint (mirrors `build_pipeline.py`'s `nbconvert --execute
--inplace` wrapper). Cell sequence:

1. Setup — imports (incl. `from cs4406m26_assignment1c1.bm25 import ...`),
   load feature store, constants.
2. Tokenizer smoke test — Danish/English samples, `None`/empty-string handling
   (exercises the imported `tokenize`, not a notebook-local redefinition).
3. Per-dataset tokenized document corpus (`title+abstract`) + test — covers the
   `abstract.fillna("")` case explicitly using a known null-abstract MIND row.
4. Build a `BM25Index` per dataset (`build_index`) + test — cross-check
   `avgdl`/`doc_len` against independently-computed values, and a couple of
   `idf` values against a by-hand calculation on a small sample.
5. Top-K retrieval smoke test (`top_k`) — length, descending order, nesting
   invariant (`top200[:50] == top50`), empty query → `[]`.
6. Query construction from history + test — cold-start → `[]`; window correctly
   takes the *last* N clicks, not the first N.
7. Per-user retrieval cache, restricted to val/test users + test — cache keys
   are a subset of val∪test user_ids; cold-start count cross-checked
   independently per dataset (not hardcoded, since EB-NeRD's true count is 0).
8. Recall@K evaluation + test — monotonic `recall@50 ≤ recall@100 ≤ recall@200`;
   `n_evaluated + n_excluded == n_total`; values in `[0,1]`.
9. Persist `bm25_topk.parquet` + `bm25_metrics.json` + round-trip test.

## 10. Scale: `ebnerd_large`/`mind_large`, and `BUILD_LARGE_ONLY`

Same `polars`-not-`pandas` reasoning as Q1 (see Q1 #5), applied to this
notebook (and Q3-Q5's, identically): `feature_store` loads via
`pl.read_parquet(..., columns=[...])` with an explicit column projection per
table, rather than loading every persisted column and filtering/dropping in
memory afterward. This notebook never touches `article_ids_inview` at all
(only Q4/Q5's re-ranking framing needs it), so `behaviors` is projected down
to `user_id, article_ids_clicked, split`; `history` to
`user_id, article_id_sequence`; `articles` to `article_id, title, abstract`
— skipping columns not used here rather than loading `ebnerd_large`'s full
24.6M-row behaviors table and its unused `article_ids_inview` lists.

**Write-step OOM, two more iterations (not sidestepped by avoiding `pandas`
as originally expected)**: `bm25_topk.parquet` is built straight from Python
lists to `pl.DataFrame(...)`, never through `pandas` — but this still
crashed at `ebnerd_large` scale (821,111 rows × two 200-element list
columns, a ~2.6GB single allocation), because `polars` itself has to
materialize one large contiguous buffer per column regardless of whether
`pandas` is involved. Two fixes were needed, not one:

1. `write_topk_parquet_chunked` (same pattern as Q1's `write_parquet_chunked`):
   build and write each 50,000-row chunk to its own small parquet file
   instead of one `pl.DataFrame` covering all 821,111 rows at once.
2. The chunk *merge* step also crashed — `polars.scan_parquet(...).sink_parquet(...)`
   OOM'd combining just 17 chunk files, because this polars version's
   `sink_parquet` collects the full result into memory before writing
   rather than truly streaming (unlike what its name/Q1's original usage
   assumed). Left behind a truncated, unreadable parquet file on crash.
   Fixed by merging via `pyarrow.parquet.ParquetWriter` directly instead:
   read each chunk file as an Arrow table and `writer.write_table(table)`
   to append it as its own row group — genuinely bounded to one chunk's
   memory footprint regardless of the final file's total size, verified
   directly on synthetic data at the same 850,000-row/200-element-list
   scale before trusting it on the real (multi-hour) rerun.

Confirmed successful run: `ebnerd_large` — 821,111 users retrieved, 0
cold-start; recall@200 = 0.0053 (val) / 0.0063 (test). `mind_large` —
415,122 retrieved, 10,423 cold-start (val) / 11,270 (test); recall@200 =
0.0297 (val) / 0.0132 (test). Both `bm25_topk.parquet`/`bm25_metrics.json`
round-trip correctly.

**A further, non-obvious slowdown found while debugging Q3's copy of this
same write step**: the chunked writer's `gc.collect()` calls (added
defensively after each chunk write/merge, following Q1's `write_parquet_chunked`
convention) turned out to cost minutes *per call*, not the near-zero cost
`gc.collect()` normally has — because these notebooks keep a large amount
of state alive throughout (BM25 indexes, the full `user_topk` dict, corpus
matrices), and a forced `gc.collect()` scans the *entire* live object graph
looking for reference cycles, not just the object just `del`eted. Since
`chunk_df`/`table` are plain, non-cyclic objects, plain `del` already frees
them immediately via refcounting — the `gc.collect()` calls were pure
overhead. Removed from both `bm25_retrieval.ipynb` and
`embedding_retrieval.ipynb`'s chunked writers (confirmed directly:
`embedding_retrieval.ipynb`'s equivalent write step took ~2+ hours with
these calls in place and dropped to minutes once removed).

Same `BUILD_LARGE_ONLY` flag/convention as Q1: `DATASETS` is
`["ebnerd_large", "mind_large"]` when `True`, skipping
`ebnerd`/`ebnerd_small`/`mind` entirely (never read, never written) rather
than recomputing already-good results. Progress (dataset load, retrieval
cache building — logged every 50,000 users given `ebnerd_large`'s ~800K+
eval-user population, recall@K computation, output write) is appended to
the same `build_progress.log` Q1 writes to, so a single tailed file covers
the whole Q1-Q5 pipeline across separate notebook processes.

Two tests were adjusted so they don't silently pass vacuously under
`BUILD_LARGE_ONLY`: the null-abstract corpus-alignment check no longer
hardcodes `"mind"` (which isn't in scope when `DATASETS` is large-only) —
it searches `DATASETS` for whichever dataset actually has null abstracts.

# Q3 — Semantic Candidate Generation (Embeddings)

## 1. Embedding source

One uniform method for both datasets — not EB-NeRD's provided pretrained
artifacts (which would leave MIND on a separate, incomparable code path and
vector space regardless, since MIND has no provided article embeddings at
all, only unrelated KG entity embeddings already excluded from the Q1
schema). Same "shared code, separate runs per dataset" pattern as Q1/Q2.

Model: `paraphrase-xlm-r-multilingual-v1` (XLM-RoBERTa-based, 768-dim, via
`sentence-transformers`) — handles Danish and English in one model, matches
the assignment's "BERT/XLM-RoBERTa" suggestion directly, and produces
genuinely semantic (not lexical) vectors, which matters for item 5's
lexical-vs-semantic comparison to be meaningful.

**Computed on Kaggle Notebooks on a GPU, not locally.**
`sentence-transformers` + `torch` are a materially heavy dependency (hundreds
of MB to ~1GB+), and CLAUDE.md's own tech-stack note already says model
training/inference-heavy work belongs on a hosted GPU notebook, not the local
environment. The split:

- `src/compute_embeddings_kaggle.ipynb` — a standalone notebook, **not** part
  of the local one-command pipeline and **not** executed by any local
  `*.py` wrapper. Run on Kaggle (GPU accelerator, internet enabled): each
  dataset's `articles.parquet` (renamed to `{dataset}_articles.parquet`) is
  attached as a Kaggle Dataset input — any subset of `ebnerd`/`ebnerd_small`/
  `mind` present is auto-discovered by filename pattern (`ebnerd_small`
  matched and excluded from the plainer `ebnerd` pattern first, so
  `ebnerd_small_articles.parquet` is never ambiguously double-counted as an
  `ebnerd` match), which lets a re-run upload only the dataset that actually
  changed rather than all three every time. The notebook encodes
  `title + " " + abstract` with the model above, and writes the resulting
  `{dataset}_article_embeddings.parquet` per attached dataset to
  `/kaggle/working/`, downloaded from that run's Output tab. A GPU makes
  runtime a non-issue at these corpus sizes (11,777 / 20,738 / 65,238
  articles), so no local speed benchmark is needed for this step — unlike
  Q2's `rank_bm25` story, the constraint here is dependency weight and
  environment (Kaggle has a GPU and disposable install; the local dev
  environment doesn't), not raw throughput.
- The downloaded files are placed at
  `data/processed/{dataset}/article_embeddings.parquet` by hand (same
  manual-prerequisite pattern as Q1's raw dataset downloads — Part 0 of the
  assignment already requires a manual download step before the one-command
  rebuild can run).
- Everything downstream (#2–#7 below) runs locally with **zero new
  dependencies** — `numpy`/`pandas`/`pyarrow` (already in `pyproject.toml`)
  are sufficient once the embedding vectors already exist as a parquet file;
  the local repo never imports `torch` or `sentence-transformers`.

## 2. ANN index

Brute-force, not FAISS. At `dim ∈ {300–768}` and corpus sizes 11,777
(EB-NeRD demo) / 20,738 (EB-NeRD small) / 65,238 (MIND), a batched dense `numpy` matmul
(`user_vectors @ corpus_matrix.T`) plus `np.argpartition` top-K, measured
directly: ~7–12s for the full MIND val/test population (65,173 users) at the
matmul step, ~19–40s for top-K selection — under two minutes total, and
proportionally faster for EB-NeRD. FAISS would add a real dependency to
solve a problem plain numpy already solves in seconds at this scale. The one
real requirement is batching users (e.g. 2,000–5,000 per batch) — the full
similarity matrix at MIND scale is ~17GB and must never be materialized at
once.

## 3. User representation

Mean-pool the embeddings of a user's most recent `RECENT_N_CLICKS = 20`
clicks from `history.article_id_sequence` — same window Q2 uses for BM25
query construction (`sequence[-20:]`), kept identical rather than tuned
separately, so the lexical-vs-semantic comparison in #5 holds the input
click window constant and only varies the scoring method. Cold-start users
(empty `article_id_sequence`) produce no vector and are excluded from
recall@K, reusing Q2's already-computed `coldstart_users` sets (0 EB-NeRD
demo / 0 EB-NeRD small / 1,770 MIND) rather than recomputing. Retrieval is cached once per val/test
user, identical rationale to Q2's caching (query depends only on fixed
pre-window history).

## 4. Recall@K

Same `K ∈ {50, 100, 200}`, same fractional multi-relevant definition as Q2
(`|clicked ∩ top-K| / |clicked|`, macro-averaged over non-cold-start
impressions per split) — retrieval-method-independent, reused directly
rather than redefined.

## 5. Lexical vs. semantic comparison

A comparison table reading both `bm25_metrics.json` and
`embedding_metrics.json` — `recall@{50,100,200}` × `{bm25, embedding}` ×
`{val, test}` × `{cold-start-excluded, warm-only}`, reusing Q2's
`coldstart_users` sets directly. Both EB-NeRD tracks' 0 cold-start users
make that slice degenerate there (state this plainly, don't hide it); MIND's
1,770-user cold-start population makes the slice meaningful.

## 6. Persistence

Schema-parallel to Q2's artifacts (deliberately identical shape so Q4 can
treat both methods uniformly):

```
data/processed/{dataset}/embedding_topk.parquet
  user_id, dataset, n_retrieved
  retrieved_article_ids  list[str]    # score-descending (cosine similarity)
  retrieved_scores       list[float]  # parallel, cosine similarity in [-1, 1]
data/processed/{dataset}/embedding_metrics.json
  schema_version, build_timestamp
  hyperparameters: {embedding_method, embedding_dim, recent_n_clicks, topk_max}
  recall_at_k: {val: {50, 100, 200}, test: {50, 100, 200}}
  n_impressions: {val: {total, evaluated, excluded_coldstart}, test: {...}}
  scope: "val_test_users_only"
data/processed/{dataset}/article_embeddings.parquet
  article_id  str
  dataset     str
  embedding   list[float32]   # aligned to articles.parquet order
```

`article_embeddings.parquet` has no Q2 equivalent — BM25's index rebuilds
cheaply from `articles.parquet` in seconds, but Q4's re-scoring adapter needs
raw embedding vectors (not just top-200 candidates) to score arbitrary
`article_ids_inview` items outside any user's cached top-200.

## 7. Implementation shape

`src/compute_embeddings_kaggle.ipynb` — the Kaggle-only notebook from #1.
Prerequisite artifact, run manually before anything below; not part of the
local one-command pipeline.

`src/cs4406m26_assignment1c1/embeddings.py` — a new local module, same
rationale as `bm25.py` (reusable, real performance requirement — the
batching in #2, not the embedding computation, which happened on Kaggle).
Functions: `mean_pool(article_ids, embedding_lookup) -> np.ndarray`,
`batched_top_k(query_matrix, corpus_matrix, doc_ids, k, batch_size)`,
`cosine_similarity_subset(query_vector, corpus_matrix, doc_ids, subset_ids)`
(reused by Q4's re-scoring adapter).

`src/embedding_retrieval.ipynb` + `embedding_retrieval.py`, mirroring
`bm25_retrieval.ipynb`'s cell sequence:

1. Setup — imports, load feature store, constants. Load
   `article_embeddings.parquet` per dataset; fail with a clear message
   pointing at `compute_embeddings_kaggle.ipynb` if missing.
2. Load article embeddings per dataset + test — shape, no-NaN, alignment
   with `articles.parquet` row order.
3. Build corpus embedding matrices + test — mirrors `test_corpus_alignment`.
4. Mean-pooling user representation + test — cold-start → no vector; window
   is the *last* N clicks, not the first N.
5. Batched brute-force top-K retrieval + test — self-similarity ≈1.0 sanity
   check, sorted-descending, nesting invariant (`top200[:50] == top50`),
   empty query → `[]`.
6. Per-user retrieval cache, restricted to val/test users + test — mirrors
   `test_user_retrieval_cache`.
7. Recall@K evaluation + test — monotonic, bounded, count-consistent.
8. Lexical-vs-semantic comparison (#5) + test — reloaded values match both
   persisted `*_metrics.json` files.
9. Persist `embedding_topk.parquet` + `embedding_metrics.json` +
   `article_embeddings.parquet` + round-trip test.

# Manual Review upto here

## 10. Scale: `ebnerd_large`/`mind_large`

Same `polars`/`BUILD_LARGE_ONLY` treatment as Q2 (see Q2 #10): column
projection at load (`articles` → `article_id` only, since title/abstract
aren't needed once embeddings exist; `behaviors` →
`user_id, article_ids_clicked, split`; `history` →
`user_id, article_id_sequence`), `DATASETS` swapped to
`["ebnerd_large", "mind_large"]` under `BUILD_LARGE_ONLY`, progress appended
to the shared `build_progress.log`. Requires
`data/processed/ebnerd_large/article_embeddings.parquet` and
`data/processed/mind_large/article_embeddings.parquet` to already exist —
i.e. `compute_embeddings_kaggle.ipynb` must be run on Kaggle for these two
catalogs first (its `DATASET_PATTERNS`/`EXPECTED_PREFIXES` dicts were
extended to discover `ebnerd_large_articles.parquet`/
`mind_large_articles.parquet`, matched-and-excluded before the plainer
`ebnerd`/`mind` patterns, same ordering trick already used for
`ebnerd_small`).

**Write step**: same two-part fix as Q2 #10 (`write_topk_parquet_chunked` +
`pyarrow.parquet.ParquetWriter` merge), since `embedding_topk.parquet` has
the identical shape (one row per retrieved user, two 200-element list
columns) and hit the identical OOM at the identical scale. Also where the
`gc.collect()` slowdown documented in Q2 #10 was actually *found*: this
notebook's write step took ~2+ hours with `gc.collect()` calls in the
chunk-write/merge loop and dropped to under 2 minutes once they were
removed — confirmed by direct comparison on the same run.

**`batched_top_k` results-list accumulation (a second, distinct OOM, not
covered by the write-step fix above)**: `batched_top_k` processes queries in
small internal batches, but accumulates *all* results into one Python list
before returning. At `ebnerd_large` scale (821,111 queries × 200-item
results ≈ 164M tuples), that list alone consumed enough memory that a
*later* batch's own `np.argpartition` scratch array (`(BATCH_SIZE, n_docs)`
int64, a few GB by itself) failed to allocate — `MemoryError`. Fixed two
ways:
1. The notebook now calls `batched_top_k` in `QUERY_CHUNK_SIZE = 50_000`-row
   outer chunks instead of one call over all 821,111 queries, merging each
   chunk's results into the running `user_topk` dict and discarding the
   chunk's own result list before the next chunk starts.
2. `BATCH_SIZE` (the notebook constant controlling `batched_top_k`'s
   *internal* batching) was reduced from 2000 to 500: `ebnerd_large`'s
   125,541-doc corpus makes the `argpartition` scratch array ~2x bigger than
   what 2000 was originally sized for against the smaller datasets (max
   65,238 docs) this constant predates.

**Kernel-transport crashes (`WinError 10055` / `OSError: [WinError 10055]`,
unrelated to memory)**: on this Windows machine, long-running Jupyter
kernels intermittently died with a low-level ZeroMQ socket error (`No
buffer space available` / `error not defined`) — not a Python exception,
not correlated with any specific cell, and reproducing at the exact point
several separate runs otherwise succeeded. Root cause: the default asyncio
event loop on Windows (`WindowsProactorEventLoopPolicy`) doesn't implement
`add_reader`, so `ipykernel`/`tornado` falls back to an extra selector
thread for ZMQ — a known source of socket-handling flakiness under
prolonged use. Fixed by launching `nbconvert` through a small wrapper
(`_run_nbconvert_selector_loop.py`) that calls
`asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`
before invoking `nbconvert`'s own entrypoint — used for every Q3-Q5
`nbconvert --execute` invocation from this point on. Not airtight (one run
still needed a retry), but eliminated the crash in every run that
previously hit it reliably.

Confirmed successful run: `ebnerd_large` — 821,111 retrieved, 0 cold-start
users; recall@200 = 0.0029 (val) / 0.0021 (test). `mind_large` — 415,122
retrieved, 10,423 cold-start users (11,393 excluded val impressions / 11,270
excluded test impressions); recall@200 = 0.0199 (val) / 0.0152 (test). Both
`embedding_topk.parquet`/`embedding_metrics.json` round-trip correctly.

# Q4 — Offline Evaluation Harness

## 1. Candidate-generation vs. re-ranking — the central design fork

AUC, MRR, nDCG@5, and nDCG@10 require a full ranking over a candidate *set*
with known relevance labels — the only such set that exists per impression
is `article_ids_inview` (median 9 EB-NeRD / 24 MIND items), re-ranked by the
retrieval method's score. This is a different framing from Q2/Q3's
recall@K, which retrieves top-K from the whole catalog (11,777 / 65,238
articles):

| | Q2/Q3 recall@K | Q4 AUC/MRR/nDCG |
|---|---|---|
| Candidate set | Retrieval method's own top-K from the whole catalog | The impression's own `article_ids_inview` |
| Question | Can this method find the clicked article at all, among everything? | Given what was actually shown, does this method rank the clicked one(s) near the top? |
| Framing | Candidate generation | Re-ranking |

This matches how MIND's and EB-NeRD/RecSys2024's own official challenges
define these metrics. It also means Q4 cannot just consume the persisted
top-200 lists for ranking metrics — MIND's recall@200 is only 1.6–3.4% (from
Q2), so the clicked article is usually outside the cached top-200 entirely,
and a plain top-200 lookup would leave most rankings undefined.

Q4 needs a re-scoring adapter, one implementation per method, same
signature: `score_inview(dataset, method, user_id, article_ids_inview) ->
dict[article_id, float]`.
- BM25: rebuild the index (cheap, seconds) and call `get_scores` once per
  user (~5ms, per Q2's benchmark), subset by `article_ids_inview`.
- Embedding: cosine similarity of the user's mean-pooled vector against only
  the inview embeddings (trivial given inview sizes of 2–299).

The persisted top-K artifacts aren't wasted — they're the correct input for
coverage (#2) and the Q3 comparison table, which are legitimately
candidate-generation-framed; ranking metrics use on-the-fly inview
re-scoring instead. This split is the key reconciliation between Q2/Q3 and
Q4's framings.

## 2. Metric formulas

Binary relevance, `article_ids_clicked` ⊆ inview:

- **AUC** (per-impression rank-sum form): rank inview items by score;
  `AUC = (sum_of_ranks(positives) - n_pos*(n_pos+1)/2) / (n_pos * n_neg)`.
  Undefined only if `n_pos == 0` or `n_neg == 0` — verified this never
  happens (no zero-click impressions in either dataset; minimum inview size
  is 2).
- **MRR**: `1 / rank_of_first_clicked_item` in the score-descending inview
  ranking (standard IR definition — one value per impression even with
  multiple clicks).
- **nDCG@K** (binary relevance): `DCG@K = Σ_{i=1}^{K} rel_i / log2(i+1)`
  over the score-descending ranking; `IDCG@K` from the ideal ordering (all
  `min(n_pos, K)` positives first); `nDCG@K = DCG@K / IDCG@K`. Computed for
  `K ∈ {5, 10}`.

Each macro-averaged over evaluated impressions per `(dataset, method,
split)`.

## 3. Beyond-accuracy metrics

- **Intra-list diversity**: over the top-10 reranked inview list (matches
  nDCG@10's window). Category-based distance — `1 - same_category(i,j)`
  averaged over all pairs — since `category` exists for every article
  regardless of method, keeping Q4 runnable on BM25-only results without a
  hard Q3 dependency, and comparable across methods.
- **Novelty**: inverse train-split popularity,
  `novelty(item) = -log2(pop(item))` where
  `pop(item) = clicks_train(item) / total_train_clicks`. 90.2% (MIND) /
  91.8% (EB-NeRD) of the catalog never appears in train clicks — zero-click
  items get add-one-smoothed popularity
  `1 / (total_train_clicks + n_articles)` to avoid `log2(0)`. List-level
  novelty = mean over the same top-10 list used for diversity.
- **Coverage**: catalog coverage from the persisted top-K artifact, not the
  reranked list — `coverage@200 = |union of retrieved_article_ids across all
  evaluated val/test users| / |articles in that dataset|`. Directly reuses
  Q2/Q3's persisted artifacts.

## 4. Slicing

Cold-start vs. warm as the required slice — zero extra engineering, reuses
Q2's `coldstart_users` sets directly (0 EB-NeRD demo / 0 EB-NeRD small /
1,770 MIND). Head vs. tail as an optional addition — train-split click
counts computed from `article_ids_clicked.explode()` on the `train` split
(no dependency on EB-NeRD's `total_pageviews`, not in the unified schema).
Verified skew: MIND's top 20% of ever-clicked articles account for 90.2% of
train clicks (median 2 clicks/article, max 4,316); EB-NeRD demo is more
moderate (49.2% from the top 20%); EB-NeRD small sits in between (69.0%).
Head = top 20% by train-click-count among ever-clicked articles; tail =
everything else, including never-clicked articles.

## 5. Bootstrap 95% CI

Resample impressions (the natural per-impression evaluation unit here), not
users. Precompute the array of per-impression metric values once per
`(dataset, method, split, metric)`; for 1,000 iterations, draw `len(array)`
indices with replacement, take the mean, collect; report the 2.5th/97.5th
percentiles as the CI alongside the mean of the original array as the point
estimate. Computationally trivial at this scale (well under a second even
for MIND's ~70K-impression test split).

## 6. Uniform evaluation interface

One function/class, `evaluate(dataset, method, split, score_inview_fn) ->
dict`, iterating a split's impressions via the shared `score_inview_fn`
signature for ranking metrics, separately reading
`bm25_topk.parquet`/`embedding_topk.parquet` for recall@K and coverage
(zero method-specific branching there, since the two are schema-identical),
slicing, then bootstrapping CIs. Only the `score_inview_fn` adapter differs
per method.

## 7. Anti-gaming (Q9) tie-in

Confirmed directly — `behaviors.parquet`'s columns are exactly
`impression_id, dataset, user_id, impression_time, article_ids_inview,
article_ids_clicked, session_id, split`; `history.parquet`'s are `user_id,
dataset, article_id_sequence, timestamp_sequence, read_time_sequence,
scroll_percentage_sequence`. No `next_read_time` / `next_scroll_percentage`
or other look-ahead field was carried into the unified schema (Q1 already
excluded them). `read_time_sequence` / `scroll_percentage_sequence`
describe past, pre-window clicks used for user representation, not the
current impression's outcome — legitimate features, not leakage. There is
nothing in the current schema for a "with vs. without unavailable features"
comparison to toggle; this is stated as a one-line confirmation in the
harness output, not built as a separate mechanism.

## 8. Implementation shape

`src/cs4406m26_assignment1c1/evaluation.py` — pure metric functions
(`auc_impression`, `mrr`, `ndcg_at_k`, `bootstrap_ci`, `intra_list_diversity`,
`novelty`, `coverage`), reusable/unit-testable like `bm25.py` but without a
raw-performance requirement, just correctness.

`src/evaluation_harness.ipynb` + `evaluation_harness.py`:

1. Setup — rebuild BM25 indexes, load `article_embeddings.parquet`.
2. Metric-formula smoke tests — hand-computed toy rankings with known
   expected AUC/MRR/nDCG@5/@10 values.
3. `score_inview` adapters for BM25 and embeddings + test — uniform
   signature, no NaN.
4. Per-impression ranking metrics + test — value ranges,
   `n_evaluated + n_excluded == n_total`.
5. Beyond-accuracy metrics + test — ILD ∈ [0,1] and 0 for an
   identical-category list; novelty ≥ 0; coverage ∈ [0,1].
6. Slicing + test — complete, non-overlapping partition.
7. Bootstrap CI + test — `lo ≤ point ≤ hi`.
8. Anti-gaming confirmation cell (#7) — schema-column assertion, not new
   engineering.
9. Persist `data/processed/{dataset}/eval_metrics.json`
   (`{method: {split: {slice: {metric: {point, ci_lo, ci_hi}}}}}`) +
   round-trip test.

## 9. Scale: `ebnerd_large`/`mind_large`

Same `polars`/`BUILD_LARGE_ONLY`/`build_progress.log` treatment as Q2/Q3
(see Q2 #10). This notebook's `behaviors` projection keeps
`article_ids_inview` (needed for the re-ranking framing itself, unlike
Q2/Q3) alongside `user_id, article_ids_clicked, split`; `articles` keeps
`category` too (needed for intra-list diversity). The ranking-metrics loop
logs progress every 200,000 impressions given the scale (`ebnerd_large`'s
val+test split alone is ~14.2M impressions × 2 methods).

The anti-gaming schema check (#7) was changed to read the schema straight
off disk via `pl.read_parquet_schema(...)` rather than
`feature_store[name]["behaviors"].columns` — the latter would only reflect
this notebook's own column projection (a memory optimization, not the true
persisted schema) and would have silently validated the wrong thing once
column projection was introduced.

**`evaluate_ranking`'s per-impression records, dicts → preallocated numpy
arrays**: the original implementation appended one `dict` per impression
(7+ keys: `auc`, `mrr`, `ndcg5`, `ndcg10`, `is_coldstart`, `is_head`,
`top10_ids`, plus the join columns) to a growing Python list, then built one
`pl.DataFrame` from that list. At `ebnerd_large`'s test-split scale (12.5M
impressions), a `dict` per row costs several GB of pure Python
object/dict-table overhead *beyond* the actual values — the same class of
problem as Q2/Q3's chunked-write fixes, addressed here at construction time
instead of at the write step. Fixed by preallocating one `numpy` array per
scalar metric column (`np.empty(n_rows, dtype=...)`, filled by index during
the scoring loop) and only using plain Python lists for the two genuinely
variable-shape columns (`user_id`, `top10_ids`) — `pl.DataFrame` is then
built once from these columns directly, no per-row dict ever constructed.

**`cosine_similarity_subset`'s hidden `O(n_docs)`-per-call cost — the
dominant cost of the whole embedding-scoring pass, found while debugging
why Q5's run (which shares this exact code path) wasn't progressing**: the
function rebuilt `id_to_idx = {aid: i for i, aid in enumerate(doc_ids)}` — a
dict over the *entire* article catalog — and re-normalized the requested
corpus subset, on *every single call*. This function is called once per
impression by the `embedding` method's `score_inview` adapter (unlike the
`bm25` adapter, which memoizes its own `id_to_idx` once per dataset outside
the per-impression closure). At `ebnerd_large` scale (12.5M+ calls against a
125,541-doc corpus), rebuilding a 125,541-entry dict per call is
`O(n_docs)` work that should be `O(1)`, dwarfing the actual similarity
computation (which only touches the small `article_ids_inview` subset).
Fixed by changing `cosine_similarity_subset`'s signature
(`cs4406m26_assignment1c1/embeddings.py`) to take a precomputed, row-normalized
`corpus_unit` matrix and a precomputed `id_to_idx` dict as parameters instead
of a raw `corpus_matrix`/`doc_ids` pair it re-derives internally — both are
now built once per dataset in `make_score_inview_adapters` (mirroring the
`bm25_fn` adapter's existing `id_to_idx` pattern exactly), reused across
every impression. `normalize_rows` (formerly `_normalize_rows`, private) was
made a public module function so callers can precompute the corpus
normalization themselves; `batched_top_k`'s own internal usage is
unaffected. Verified the new signature produces bit-identical output to the
old one on synthetic data (same `id_to_idx`/`subset_ids` resolution, same
edge cases — `None` query vector, an unresolvable subset ID) before trusting
it on a real run. Measured end-to-end via Q5 (see Q5 #6): a run using the
unfixed code was still on its *first* of eight `(dataset, split, method)`
scoring passes after 2h21m; the fixed version completed all four
`(dataset, method)` passes needed for Q5 (no `val` split there) in ~99
minutes total, including setup and the round-trip test.

**Combined-dataset kernel crashes and checkpointed re-scoring
(`ebnerd_large` + `mind_large` in one kernel)**: running this notebook
against both large datasets together left under 0.3GB free out of 15.7GB
total RAM before `ebnerd_large`'s 12.5M-row test split even started
scoring, and the kernel died intermittently (`WinError 10055`) at
inconsistent points across repeated runs — not tied to a fixed row count or
elapsed time (a 3,000,000-row and a 1,000,000-row checkpoint interval both
crashed at almost exactly their own chunk boundary despite very different
wall-clock durations to reach it). Windows Event Viewer confirmed this is
genuine system-wide memory exhaustion, not a Jupyter/ZMQ-specific quirk:
`dwm.exe`/`Explorer.exe` themselves crashed with
`STATUS_FATAL_MEMORY_EXHAUSTION` (`0xC00001AD`) at the same moments this
notebook's kernel died. Fixed with four independent, composable measures:

1. **`EVAL_DATASETS` env var** restricts a single invocation to one dataset
   (comma-separated; unset runs the full default list). `nbconvert` launches
   a fresh kernel per invocation, so running `ebnerd_large` and `mind_large`
   as two separate invocations means neither process ever holds both
   datasets' feature stores/BM25 indexes/embedding matrices at once.
2. **`dataset_fully_cached(name)`** checks whether all four `(split,
   method)` final checkpoints already exist for a dataset; when true, that
   dataset's BM25 index, embedding matrix, and `score_inview` adapters are
   never rebuilt (`bm25_index[name]`/`corpus[name]` set to `None`), since
   `evaluate_ranking` would return straight from checkpoint and never call
   `score_fn` again. `test_setup_aligned`/`test_score_inview_adapters` skip
   a fully-cached dataset (`if fully_cached[name]: continue`). A resumed
   run's setup cost is then proportional to what's left to do, not what's
   already done.
3. **Checkpointed, chunked `evaluate_ranking`**: each `(dataset, split,
   method)` scoring pass is split into `CHUNK_SIZE = 200_000`-row chunks,
   each written to its own file under `CHECKPOINT_DIR / dataset /
   f"{split}_{method}_chunks/chunk_{c:03d}.parquet"` immediately after being
   scored; an existing chunk is skipped on retry. Once every chunk for a
   pass is done, they're concatenated into `CHECKPOINT_DIR / dataset /
   f"{split}_{method}.parquet"` and the chunk directory is removed.
   `evaluate_ranking` checks for this final checkpoint first and returns it
   directly if present. All writes (per-chunk and the final merge) go
   through write-then-`os.replace`: a crash landing mid-write on the direct
   path twice produced a checkpoint that read back as corrupt ("File out of
   specification" / "must end with PAR1") on the next resume; `os.replace`
   is atomic on both Windows and POSIX, so the visible path is always either
   absent or fully valid.
4. **Redundant `.astype(np.float32)` removed** in
   `make_score_inview_adapters`: `emb_matrix` is already `float32` (cast
   once when `corpus[]` was built), so calling `.astype(np.float32)` on it
   again unconditionally copies the full `(n_docs, 768)` matrix (~385MB at
   `ebnerd_large` scale) before normalizing, for no reason. `normalize_rows`
   is now called directly on the shared array (it returns a new array,
   `matrix / norms`, and never mutates its input in place).

A **duplicate-process race** was found and fixed operationally, not in
code: killing a retry-wrapper's parent process via `Stop-Process` does not
kill an already-spawned child process on Windows — orphaned children
survive independently — which once let two full `evaluation_harness.ipynb`
kernels run simultaneously against the same checkpoint directory, corrupting
a checkpoint. Recovered by enumerating and killing the entire process tree
(`Get-CimInstance Win32_Process` + `Stop-Process`, with a delayed re-check
for late spawns) instead of the top-level process alone. An automatic
retry wrapper (`_run_nbconvert_with_retries.py`) was tried as a mitigation
for `WinError 10055`'s unpredictability, then deliberately discontinued in
favor of a single-shot run → inspect → fix → rerun cycle: checkpointing
already makes a manual rerun resume from exactly where it left off, and
automatic retries made it harder to tell whether a fix actually worked
versus just getting lucky on a later attempt.

**`top10_ids` dropped once consumed**: after computing `ild`/`novelty` from
it, `top10_ids` (a `List[str]` column of 10 article IDs per impression) is
dropped from `ranking_results`, since nothing downstream reads it again
(`compute_coverage` reads from Q2/Q3's own persisted `{method}_topk.parquet`
files, not from `ranking_results`). At `ebnerd_large`'s ~28.5M-row combined
val+test `ranking_results`, this is several GB; found necessary after a
Rust/polars allocator panic (`memory allocation of 80000000 bytes failed`)
during the bootstrap-CI step immediately after, on a machine already under
confirmed genuine memory exhaustion.

**`compute_bootstrap_metrics` — per-column filtering, not per-slice
`DataFrame` filtering**: `group_by(["dataset", "split", "method"])` selects
only the columns the function touches beforehand (`slim = ranking_results
.select([...])`), rather than carrying every column (including `user_id`,
never read here) into each group. For each slice, only the one metric
column being bootstrapped is filtered (`group[metric].filter(mask)`),
instead of filtering the whole multi-column `group` DataFrame per slice as
an earlier version did — that version also wastefully duplicated `group` in
full for the `"overall"` slice, whose mask
(`pl.Series([True] * df.height)`) is a literal all-`True` no-op filter.
`bootstrap_ci`'s `max_chunk_cells` parameter is also lowered from its 200M
default to `20_000_000` at this call site, bounding a `(1000, n_rows)`-shaped
resample-index allocation that would otherwise spike into multiple GB at
`ebnerd_large`'s test-split scale; per `bootstrap_ci`'s own docstring, chunk
size doesn't change the numerical result (`numpy`'s `Generator` produces the
same stream regardless of batch size) — confirmed via a synthetic-data
equivalence test before trusting it on real data.

**Standalone metrics finisher (`_finish_eval_metrics_standalone.py`)**: even
with every fix above and all four `(split, method)` checkpoints already
safely written to disk, the notebook's remaining downstream cells
(beyond-accuracy metrics, bootstrap CI, `eval_metrics.json` write) kept
hitting the same intermittent kernel death inside Jupyter/`nbconvert`. Since
the checkpoints already carry every column those remaining steps need
(`auc`/`mrr`/`ndcg5`/`ndcg10`/`is_coldstart`/`is_head`/`top10_ids`), a plain
script (`uv run python _finish_eval_metrics_standalone.py <dataset>`) loads
them directly and reproduces the notebook's exact remaining logic (same
`category_lookup`/`novelty_lookup` construction, the same leaner
per-column-filtering `compute_bootstrap_metrics`, the same
`eval_metrics.json` schema and round-trip check) with no Jupyter,
`nbconvert`, or ZMQ involved at all, sidestepping the unreliable kernel
layer entirely for this last stretch. It deliberately does not delete the
checkpoint directory on success (unlike the notebook's own
`write_eval_metrics`), since the checkpoints represent many hours of
compute across many crash/retry cycles — cleanup is a manual step once the
output has been checked.

Confirmed successful run — `ebnerd_large`, from `eval_metrics.json`: bm25
val (AUC 0.509, nDCG@10 0.454), bm25 test (AUC 0.501, nDCG@10 0.435),
embedding val (AUC 0.559, nDCG@10 0.483), embedding test (AUC 0.552,
nDCG@10 0.465); coverage bm25 0.987, embedding 0.778 — the same direction as
every smaller dataset track (embedding beats bm25 on ranking AUC/nDCG, bm25
covers more of the catalog).

# Q5 — Codabench Submission

## 1. Competitions

- MIND: `codabench.org/competitions/13967`
- RecSys 2024 Challenge (EB-NeRD): `codabench.org/competitions/2469`

Both competition pages are JS-rendered and require a logged-in session to
view directly (confirmed: fetching either URL returns only navigation
chrome, no competition-specific content).

## 2. Submission file format

**MIND — confirmed directly from the competition's own Submission
Guidelines page** (`codabench.org/competitions/13967`, Participate tab):

- Zip containing exactly one file, `prediction.txt`, at the zip **root**
  (no subfolder; no `__MACOSX/` entries from Mac zip tools).
- Each line: `ImpressionID [Rank-of-News1,Rank-of-News2,...,Rank-of-NewsN]`,
  one line per impression, ranks are **integers starting from 1**.
- **Row order in the file must match the original impressions file's row
  order** — not re-sorted by `ImpressionID` or anything else.
- Max **one submission per day**. Participants may also submit **validation-
  set** predictions during the development phase, separate from the final
  test-set submission, to sanity-check without spending the daily test-set
  quota.
- Process: Participate tab → (optional) description → "Submit / View
  Results" → upload the zip → wait for status Finished/Failed → optionally
  publish the score to the leaderboard.

This matches, independently, what two reference implementations write:
EB-NeRD's own starter repo
(`ebrec.utils._python.write_submission_file`/`rank_predictions_by_score`,
`github.com/ebanalyse/ebnerd-benchmark`) and the MIND reference NRMS example
(`recommenders-team/recommenders`,
`examples/00_quick_start/nrms_MIND.ipynb`): `rank_i` is the 1-indexed rank
(1 = highest predicted score) of the *i*-th article in that impression's
`article_ids_inview`, in its **original** order — `argsort(argsort(-scores))
+ 1`. `impression_id` is the dataset's **native** (non-namespaced) ID: for
MIND, the trailing integer of the unified schema's
`mind_<split>_<native_id>` (equivalently, that row's 1-indexed position
within `MINDsmall_dev/behaviors.tsv`); for EB-NeRD, the trailing integer of
`ebnerd_<native_id>`.

**EB-NeRD's own Submission Guidelines page** (`codabench.org/competitions/2469`)
is not yet directly confirmed — assumed identical by the source-code match
above (RecSys Challenge conventions typically mirror MIND's scheme) — worth
a final visual check before the real submission.

## 3. Still unverified

**MIND — the earlier "resolved" note here was wrong, corrected after a real
failed submission.** A first submission (BM25, generated over MINDsmall's
provider `dev/`, treated as this project's `test` split) failed on
Codabench with an `IndexError` inside their `evaluate.py` — a candidate-set
length mismatch for at least one impression between our local data and
Codabench's ground truth. Root-caused via the official MIND evaluation
script (`github.com/msnews/MIND/blob/master/evaluate.py`): truth and
submission rows are matched by line position with only an impression-ID
sanity check, so a shape error (not an ID error) at a matched line means
Codabench's ground truth has a *different* candidate set for that
impression than MINDsmall_dev provides. MIND's Codabench competition
almost certainly scores against `MINDlarge_test` (the real, separate,
unlabeled held-out set), not MINDsmall_dev — confirmed by the existence of
`download_mind_large_test.py` at the repo root, which fetches exactly that
file from a gated Hugging Face repo. **Not yet resolved**: that script has
not been run yet (dependencies and auth are being set up first); Q1's
temporal split and this section's `generate_predictions` still target
MINDsmall_dev and need to be re-pointed at `MINDlarge_test` once it's
downloaded — real, separate follow-up work (a different-scale, unlabeled
article catalog), not a small fix.

**EB-NeRD — confirmed to be the same problem as MIND.** A real submission
(the embedding zip, predicting over `ebnerd_demo`'s `validation/` split)
failed on Codabench with `ValueError: line-1: Inconsistent Impression ID
144772 and 6451339` — this time an outright ID mismatch (not a shape
mismatch like MIND's), meaning Codabench's ground truth's very first
impression isn't even in `ebnerd_demo` at all. Root cause confirmed
directly: `https://ebnerd-dataset.s3.eu-west-1.amazonaws.com/ebnerd_testset.zip`
exists (verified via `curl -I`, `200 OK`, 1,631,004,285 bytes / ~1.6GB — the
same public bucket `download_ebnerd.py` already downloads `ebnerd_demo.zip`/
`ebnerd_small.zip` from), confirming a dedicated, much larger,
Codabench-specific test bundle exists and is what must actually be
predicted over — exactly mirroring `MINDlarge_test` vs. MINDsmall_dev.
**Not yet fixed**: `download_ebnerd.py` (per #`download_mind_large_test.py`'s
sibling script) only supports `"demo"`/`"small"` bundles so far; needs a
`"testset"` option added, then Q1's pipeline and this section's
`generate_predictions` re-pointed at it once downloaded — same shape of
follow-up work as MIND's, not yet started.

EB-NeRD's Submission Guidelines page itself (filename: singular
`prediction.txt` like MIND, or the starter repo's own plural
`predictions.txt` default) is also still unconfirmed — `generate_predictions`
currently uses the plural form, inferred from
`ebrec.utils._python.write_submission_file`'s own default argument, not
from a direct read of the competition's guidelines.

## 4. Prediction generator

`generate_predictions(dataset, method, split="test") -> Path`, implemented
for all three dataset tracks (`src/generate_predictions.ipynb` +
`generate_predictions.py`) — `ebnerd_small`'s zip is generated for local
completeness only and is **not** submitted to Codabench, since it isn't a
separate competition track (see #3's `ebnerd_testset.zip` finding — the real
EB-NeRD competition scores that, not `ebnerd_small`). Reuses Q4's `score_inview_fn` adapter per
impression (same re-ranking framing as Q4's AUC/MRR/nDCG, not Q2/Q3's
full-catalog retrieval), computes per-position ranks via
`argsort(argsort(-scores)) + 1` over `article_ids_inview`'s original order,
strips the dataset namespace prefix from `impression_id` to recover the
native ID, and writes the dataset's submission filename (`prediction.txt`
for MIND, `predictions.txt` for EB-NeRD — see #2/#3) + zips it. Ranks are
computed in a `user_id`-sorted order for the BM25 adapter's cache efficiency
(same trick as Q4's
evaluation loop), but written back out in `behaviors.parquet`'s **existing
row order** (itself unmodified from the raw MINDsmall files by Q1's
pipeline) — row order must match the source file exactly, per #2's
confirmed guideline. `method` selects whichever of
embeddings, on both datasets), or both if the design note wants to show a
comparison.

## 5. Registration

Manual, one-time action per competition — not implementable. Leaderboard
screenshots go into the design note (Q6) once submitted.

## 6. Scale: `ebnerd_large`/`mind_large`

Same `polars`/`BUILD_LARGE_ONLY`/`build_progress.log` treatment as Q2-Q4
(see Q2 #10), plus one further optimization specific to this notebook: since
Q5 only ever needs the `test` split (never `train`/`val`), `behaviors` is
read via a lazy `pl.scan_parquet(...).filter(pl.col("split") == SPLIT)
.select([...]).collect()` instead of an eager read-then-filter — the
predicate and column projection are pushed down at scan time, so
`ebnerd_large`'s ~12.2M non-test rows are never materialized in memory at
all. `TXT_FILENAME` was extended with `ebnerd_large`/`mind_large` entries,
each reusing its family's filename convention for local-format consistency
only — neither is its own separate Codabench track (`ebnerd_large` is built
from EB-NeRD's larger provider bundle, not `ebnerd_testset.zip`;
`mind_large` from `MINDlarge_train`/`MINDlarge_dev`, not the real held-out
`MINDlarge_test`), so **do not submit these two zips**, same caveat as
`ebnerd_small` already carries (#3).

The row-order-preservation trick (#4: compute in user-sorted order for the
BM25 adapter's cache, write back in the source file's original order) is
implemented via `pl.DataFrame.with_row_index("row_idx")` instead of pandas'
implicit integer index — `row_idx` is added once right after the
(already-order-preserving) scan/filter above, so it recovers the original
file order exactly, then a `user_id`-sorted copy is used only to drive the
scoring loop before writing back out keyed by `row_idx`.

**Shares Q4's `cosine_similarity_subset` fix (see Q4 #9)** — this notebook's
`embedding_fn` adapter is the same code shape as Q4's, so it carried the
identical `O(n_docs)`-per-call bug. This is in fact where the bug's real-world
impact was first *measured*: an earlier run of this notebook (unfixed) was
still scoring its first `(dataset, method)` pair after 2h21m elapsed, with no
way to tell whether it was progressing or stuck, because
`generate_predictions`'s scoring loop originally had no intermediate progress
logging at all (unlike Q2-Q4's per-N-impressions `log_progress` calls). Fixed
both problems together: added the same `log_progress` cadence (every 200,000
impressions) to `generate_predictions`, then applied Q4 #9's
`cosine_similarity_subset` fix. The corrected run completed all four
`(dataset, method)` combinations — ~12.9M impressions scored total across
`ebnerd_large`'s and `mind_large`'s `test` splits — in ~99 minutes.

## 7. `mind_large_test` — the real, submittable population

`MINDlarge_test.zip` (downloaded separately, gitignored, extracted to
`./MINDlarge_test/`) is the actual Codabench-scored blind test set for
`codabench.org/competitions/13967` — unlike `mind_large` (built from
`MINDlarge_train`/`MINDlarge_dev`, never submittable, see #6), this **is**
the real held-out population. Handled by a standalone notebook,
`src/mind_large_test_submission.ipynb`, rather than a sixth track through
`build_pipeline.ipynb`/`bm25_retrieval.ipynb`/`embedding_retrieval.ipynb`/
`evaluation_harness.ipynb`: its `behaviors.tsv` carries **no click labels at
all** (`impressions` is a plain space-separated candidate list, no
`-0`/`-1` suffix — the defining feature of a genuine blind test, confirmed
by direct inspection), so Q2/Q3's recall@K and Q4's ranking metrics are
undefined for it. Only Q5's re-ranking task applies.

**Schema**: matches `mind_large`'s unified `articles`/`behaviors`/`history`
schema exactly, with one deliberate exception — `article_ids_clicked` is
left out of `behaviors` entirely rather than null-filled. This was a
judgment call worth stating precisely: other MIND-only-null columns
(`body`, `published_time`, `session_id`, `history`'s three sequence
columns) are null because the *MIND format itself* never carries them, true
for `mind`/`mind_large` too. `article_ids_clicked` is different in kind —
`mind_large`'s own `behaviors.parquet` has real click data; its absence
*here* is specific to this one file being a genuine blind competition test,
not a MIND-format limitation. Null-filling it would visually blend a
load-bearing fact (there is no ground truth for this population, which is
*why* Q2-Q4 don't apply) into the same bucket as incidental format gaps.
`split` is set to the constant `"test"` (accurate — this whole file *is*
the held-out population, not something derived via a temporal cutoff, so
recording it as `"test"` costs nothing extra and matches the vocabulary
other tracks use). Initially shipped with a much-reduced schema
(`article_id`/`title`/`abstract` and `impression_id`/`user_id`/
`article_ids_inview` only) on the reasoning that nothing else reads this
directory — corrected after direct pushback: `dataset`, `category`/
`subcategory`, and `impression_time` all exist in the raw files for free
and were dropped only because this notebook's own scoring code doesn't
need them, which trades a consistent `data/processed/` contract for no
real savings.

**Embeddings**: `MINDlarge_test`'s 120,961-article catalog overlaps
94,733/120,961 with `mind_large`'s already-embedded catalog; the other
26,228 exist only in this file and need a dedicated Kaggle pass
(`compute_embeddings_kaggle.ipynb`'s `DATASET_PATTERNS`/`EXPECTED_PREFIXES`
extended with a `mind_large_test_new` entry, matched before the plainer
`mind_large`/`mind` patterns). Only the missing 26,228 are re-encoded, not
the full 120,961 — the embedding model is frozen/pretrained, so an
already-computed embedding for unchanged article text is exactly reusable;
re-encoding it would waste GPU time for identical output, not just be
slower. Encoding *is* required for the missing 26,228 specifically because
an embedding only exists once the model has actually run over that
article's text — nothing about using a test article's own text this way
leaks click-label information, since the model is never fit to any of this
project's data at all (see PROMPTS.md for the fuller discussion). The
notebook verifies this reuse directly, not just asserts it: after merging,
an overlapping article's embedding is checked byte-identical against
`mind_large`'s own stored vector, catching a merge bug that silently
re-encodes everything instead of actually reusing anything.

The notebook is designed to run in two sittings around this Kaggle step
(a markdown cell marked **PAUSE HERE**) — verified directly that the first
sitting's cells (parsing, gap-detection, and their tests) execute and
persist correctly on their own, failing fast with a clear message exactly
at the merge-embeddings cell when the Kaggle output isn't present yet,
rather than partway through some other cell.

## 8. `ebnerd_testset` — the real, submittable population

`ebnerd_testset.zip` (downloaded separately, gitignored, extracted to
`./ebnerd_testset/`) is EB-NeRD/RecSys 2024's actual Codabench-scored blind
test set (`codabench.org/competitions/2469`) — same relationship to
`ebnerd_large` as `mind_large_test` has to `mind_large` (#7): its
`test/behaviors.parquet` has no `article_ids_clicked` column at all, so
Q2-Q4 don't apply, only Q5's re-ranking. Handled by a standalone notebook,
`src/ebnerd_testset_submission.ipynb`.

**No Kaggle embeddings round needed**, unlike MIND's real test set — direct
set-equality comparison (`test_raw_ids == existing_raw_ids`) found
`ebnerd_testset/articles.parquet`'s 125,541 articles are *exactly*
`ebnerd_large`'s existing, already-embedded catalog: zero missing, zero
extra. This is a genuine structural difference from MIND, not an
inconsistency in how the two are handled — EB-NeRD shares one static
article pool across every split by design, while MIND's splits are
time-windowed slices of a continuously-published pool (old articles still
candidates in a later window; new articles published after an earlier
window closed), so MIND's real test introduces 26,228 genuinely new
articles where EB-NeRD's doesn't. `ebnerd_large`'s `articles.parquet`/
`article_embeddings.parquet` are reused directly (no re-parsing, no
re-encoding), with a hard `test_catalogs_identical` invariant test that
fails loudly if a future zip revision ever breaks this assumption, rather
than silently scoring candidates with no embedding.

**`is_beyond_accuracy` bug, found twice**: `test/behaviors.parquet` carries
13,536,710 total rows, of which 200,000 are flagged `is_beyond_accuracy=True`
— RecSys 2024's separate diversity-focused track. All 200,000 share the
single literal `impression_id=0` (a sentinel, not a real per-impression ID —
each row has its own genuine `user_id`/`session_id`, but the same
placeholder impression ID) and one fixed 250-article `article_ids_inview`
candidate list, confirmed by direct inspection.

The first version of this notebook excluded these 200,000 rows from
scoring/`predictions.txt` entirely, reasoning (wrongly) that the shared
sentinel ID broke the one-line-per-impression format, and that since this
pipeline doesn't implement diversity-specific re-ranking, submitting
nothing for that population was the safe default. This produced a real
Codabench submission failure inside their `score.py`
(`ValueError: Length of values (0) does not match length of index
(200000)`) — Codabench builds a 200,000-row lookup for the beyond-accuracy
population and pulls the submitted ranks for it; submitting zero rows for
that population is exactly what produced a length-0 result there. Confirmed
against `ebnerd-benchmark`'s own reference example
(`examples/beyond_accuracy/make_beyond_accuracy.ipynb`'s "Make a Submission
file" cell: `pl.concat([df_behaviors, df_beyond_accuarcy])` before writing
one `predictions.txt`) that there is no separate beyond-accuracy submission
format — Codabench scores diversity/coverage/serendipity/novelty on top of
whatever ranking is submitted for that population, using the same file.
Fixed by removing the exclusion: `behaviors_final` is now `behaviors_all`
unfiltered (200,000 more rows scored per method, with the same
`score_inview` adapters, no special-casing needed — their
`article_ids_inview` field already holds a valid, if shared, candidate
list). The round-trip test's `impression_id` uniqueness check was narrowed
to the accuracy-track rows only, since the beyond-accuracy rows' shared
sentinel ID is now a deliberately-asserted invariant, not treated as a
uniqueness violation.

**`bm25`/`embedding` split across two `nbconvert` invocations**: this
notebook has no checkpointing (unlike `evaluation_harness.ipynb`'s
per-chunk checkpoints, Q4 #9), and scoring both methods sequentially in one
kernel over 13.5M+ rows is a multi-hour session exposed to this machine's
intermittent, still-unexplained `WinError 10055` kernel death (Q4 #9) for
that entire duration — a crash partway through would lose both methods'
progress, not just one. A `METHODS` env var (comma-separated, same
convention as `evaluation_harness.ipynb`'s `EVAL_DATASETS`) restricts a
single invocation to one method, so `bm25` and `embedding` run as two
separate, shorter-lived kernels (`nbconvert` launches a fresh kernel per
invocation): `METHODS=embedding uv run python
_run_nbconvert_selector_loop.py src/ebnerd_testset_submission.ipynb 10800`,
then the same with `METHODS=bm25`. The two invocations are run
sequentially, not in parallel — each independently rebuilds its own copy of
the BM25 index and embedding matrix from scratch, so running them
concurrently would double that memory footprint for no benefit, unlike
running both methods inside one already-loaded kernel (which shares the
index/matrix build regardless of method count).

**Even split, `generate_predictions` still needed checkpointing**: the
`METHODS` split alone wasn't enough — the `embedding` run crashed to the
same `WinError 10055` kernel death at 13,400,000/13,536,710 impressions
(99% through), losing the entire pass since nothing had been persisted yet.
Confirmed via Windows Event Viewer as the same genuine memory-exhaustion
class as Q4 #9 (`dwm.exe` crashing with `STATUS_FATAL_MEMORY_EXHAUSTION`,
`0xC00001AD`, at the same moment), not a new failure mode. Fixed with the
same pattern as `evaluate_ranking` (Q4 #9): ranks are computed in
`CHUNK_SIZE = 200_000`-row chunks (in the same user-sorted scoring order,
for BM25 cache efficiency), each written to its own file under
`data/processed/_predict_checkpoints/ebnerd_testset/{method}_chunks/` via
write-then-`os.replace` immediately after scoring; an existing chunk is
skipped on retry. Once every chunk for a method exists, they're
concatenated into one final `{method}_ranks.parquet` checkpoint (same
atomic-write pattern), and `generate_predictions` returns straight from
that checkpoint on a fully-resumed call without rescoring anything. This
merge step is unconditional — it runs every time the chunk loop completes
without crashing, regardless of how many separate invocations it took to
produce all the chunks, so no manual bookkeeping is needed across repeated
crash/retry cycles.

**Schema/embeddings/rest**: matches `mind_large_test`'s pattern exactly —
`article_ids_clicked` left out (not null-filled, same reasoning as #7),
`split` set to the constant `"test"`, `is_beyond_accuracy` added as the one
EB-NeRD-specific extra column. Final verified run: 13,536,710 total rows
parsed and scored (13,336,710 accuracy-track + 200,000 beyond-accuracy,
both submitted together), 807,677 distinct users, both `predictions.txt`
zips (`embedding`/`bm25`) round-trip with exactly 13,536,710 lines each —
both are real Codabench submissions for this competition (unlike
`ebnerd_large`'s/`ebnerd_small`'s zips, #3), so both get uploaded.

# Q6 — Design Note

Lives at `design_note.tex` → `design_note.pdf`, built with `latexmk -pdf`,
4 pages. Section cross-references use `Section~\ref{...}` (not `\S`), so
every reference is both spelled out and, via `hyperref`, clickable.

- **Introduction**: pipeline scope (both datasets, all variants) and the
  four stages (unified schema, BM25, embeddings, evaluation).
- **Design** (`Section 2`): a `Unified Schema` subsection (the three shared
  tables, null-over-fabrication policy, dataset namespacing, and Q9's
  anti-gaming enforcement at the schema level), one subsection per Q1–Q5
  each pulling its "why" directly from the corresponding `SPEC.md` section,
  and a `Code Optimizations` subsection — a bullet list, not a table, of
  every measured performance/memory fix made across the project in the
  order encountered, from Q2's BM25 rewrite through Q4's
  checkpointing/standalone-script fixes (Q4 #9 above).
- **Discussion** (`Section 3`): a `Results` subsection holding one table
  with every core metric (recall@200, catalog coverage, AUC, nDCG@10)
  across every dataset track and split; a `Lexical vs. Semantic Retrieval`
  subsection that discusses that table in prose rather than repeating its
  numbers; `Dataset Differences` (language, cold-start, popularity skew,
  text length); and `Scaling to the Full Datasets: A Real Incident` — the
  `WinError 10055` saga (Q4 #9), generalized to what a real 10x scale-up
  would additionally need (full vectorization of Q1–Q3's per-user loops, a
  real ANN index in place of the brute-force similarity matrix, a real
  feature store in place of single-machine parquet I/O).
- **Leaderboard screenshots** (end of the Q5 subsection): MIND's real,
  scored `MINDlarge_test` leaderboard result for both methods (embedding
  AUC 0.6174, rank 55; bm25 0.5797); EB-NeRD's submission shown as
  accepted-and-queued, since Codabench's own evaluation queue had not
  returned a score at writing time.

# Q7 — Deliverables

Checklist against Q7's four required items, tracking what already exists:

1. Code (GitHub Classroom): reproducible pipeline (`build_pipeline.py`),
   retrieval/eval code (`bm25_retrieval.py`, plus `embedding_retrieval.py` /
   `evaluation_harness.py` once Q3/Q4 are implemented), prediction files
   (Q5), `README.md` with one-command-reproduce sections per stage (already
   the pattern for Q1/Q2, extend per stage as it lands). `.gitignore`
   excludes `data/` and raw dataset directories (done in Q1).
2. Design note: `design_note.tex`/`.pdf` (skeleton exists; content per Q6).
3. Leaderboard screenshots: pending Q5 (manual, post-submission).
4. AI usage log: `PROMPTS.md` (already being maintained throughout this
   project as each significant prompt lands).

# Q8 — Git Commit Policy

Already followed: commits are per logical unit of work with descriptive
messages, `.gitignore` excludes large/generated files (`data/`, raw dataset
directories, `__pycache__/`), and no force-pushes have occurred. No
additional engineering needed — noted here only for completeness against
the assignment's checklist.

# Q9 — Anti-Gaming

Two requirements, both already satisfied by existing work rather than
needing new engineering:

- **No future-click leakage**: enforced and tested in Q1 (temporal split
  boundary test + the EB-NeRD history-timestamp / MIND history-consistency
  leakage tests, both passing on real data).
- **Report metrics with/without serving-time-unavailable features**: per
  Q4 #7's anti-gaming tie-in, the unified schema never carries EB-NeRD's
  look-ahead fields (`next_read_time`, `next_scroll_percentage`) in the
  first place, so there's nothing to toggle — stated as a confirmation in
  Q4's harness output, not a separate mechanism.

# Assignment 2 Spec

Builds a trained re-ranker (Stage 2 of a retrieve-then-rank pipeline) on top
of Assignment 1's unchanged Stage-1 retrieval, learned from click labels,
plus a reproduced neural baseline and an extended evaluation harness. Reuses
Assignment 1's unified schema, `evaluation.py`, `embeddings.py`, and
`score_inview` adapter pattern unchanged unless stated otherwise below.

# A2 Q1 — Click-History & Session Features

## 1. Goal

Produce a per-(impression, candidate-article) feature table
(`reranker_features.parquet`) from behavioural signals already present in
the unified schema (`history.timestamp_sequence`/`read_time_sequence`/
`scroll_percentage_sequence`, `behaviors.session_id`) that A1 built but never
consumed. This is Stage 1 input for Q2's re-ranker; Q2 additionally joins in
`bm25_score`/`embedding_score` (from the existing `score_inview` adapters)
and `in_bm25_top200`/`in_embedding_top200` (from the existing
`{method}_topk.parquet` artifacts) — neither belongs here, since both are
retrieval-method-specific rather than intrinsic behavioural signals.

## 2. Output schema

One row per `(impression_id, article_id)` pair, `article_id` ranging over
that impression's `article_ids_inview`:

| Column | Type | Notes |
|---|---|---|
| `impression_id`, `dataset`, `user_id`, `article_id`, `split` | string | join keys |
| `clicked` | bool | training target — `article_id in article_ids_clicked` |
| `click_count` | int | `len(history.article_id_sequence)` for this user |
| `weighted_category_affinity` | float | see §4 |
| `weighted_read_time` | float, nullable | null for MIND (never had dwell-time data) |
| `weighted_scroll_percentage` | float, nullable | null for MIND |
| `weighted_embedding_similarity` | float, nullable | see §5; null for empty history |
| `position_in_impression` | int | 1-indexed position in `article_ids_inview`'s original order |
| `clicks_earlier_in_session` | int, nullable | null for MIND (no session concept); see §6 |
| `session_impressions_so_far` | int, nullable | null for MIND |
| `popularity` | float | `train_popularity_lookup` (§7), shared with Q4's novelty metric |
| `freshness_hours` | float, nullable | `impression_time − published_time`; null for MIND (`published_time` always null) |
| `category_match` | bool | candidate's category ∈ this user's history category set |

Per-dataset metadata (`recency_weight_basis`, `has_session_data`,
`has_dwell_time`, `has_freshness`, row counts, the train-sample cap actually
applied) is written to `feature_metrics.json` alongside the parquet, not as
repeated per-row string columns — the same shape as `bm25_metrics.json`/
`embedding_metrics.json`.

**Deliberately excluded** (A2 Q9 content): the *current* impression's own
`read_time`/`scroll_percentage`. These were correctly never unified into
`behaviors` in A1 (Q1 §2) — they are the outcome of the very impression
being scored, not a pre-impression signal, so adding them now would be
leakage. Reported as a with/without-serving-time-features comparison in Q9,
not toggled here.

## 3. Recency weighting — per (user, impression), not per user

A history click's recency weight is relative to *this* impression's
`impression_time`, not a single fixed "now" per user — even though a user's
`history.article_id_sequence` is itself a fixed, pre-collection-window
snapshot reused across all of that user's val/test impressions (A1 Q1 §2).
A click made 3 hours before the eval window's earliest impression has
decayed further by the time a user's last test-split impression is scored
days later; treating recency as a per-user constant would silently misprice
that. Weight formulas (exponential half-life decay, closest to how
recommendation systems commonly decay dwell/click signals):

- **EB-NeRD** (`recency_weight_basis = "elapsed_time"`): real elapsed time is
  known (`history.timestamp_sequence` is populated). `Δh = (impression_time −
  timestamp_i).total_seconds() / 3600`; `weight_i = exp(−ln2 · Δh /
  HALF_LIFE_HOURS)`, `HALF_LIFE_HOURS = 72.0` (a 3-day half-life — EB-NeRD's
  history window is short, so a shorter half-life differentiates "yesterday"
  from "last week" more than a multi-week one would).
Capability flags are detected from **null counts, not column dtypes**. The
two MIND tracks write the same semantically-absent columns with different
types — `mind` as `Null`, `mind_large` as `String`, both 100% null (94,057
and 750,434 rows respectively) — so a `dtype != pl.Null` test classified
`mind_large` as having real timestamps and dwell-time data and derived
elapsed-time recency weights from timestamps that do not exist. It surfaced
as an `AttributeError` on a null row in `HistoryStore`, but the silent
mislabeling was the actual defect. `test_setup` now asserts both MIND tracks
resolve to identical MIND flags, and that an all-null column reads as "no
data" under either dtype. Checked across all five tracks: only `mind_large`
differed between the two detection methods, so no other output was affected.

- **MIND** (`recency_weight_basis = "ordinal_proxy"`): MIND's raw data has no
  per-click timestamps at all, ever (A1 Q1 §2) — only click *order* is
  known. `rank_i` = position from the most recent click (0 = most recent);
  `weight_i = exp(−ln2 · rank_i / HALF_LIFE_CLICKS)`, `HALF_LIFE_CLICKS =
  5.0`. Never presented as an elapsed-time quantity in any output or plot —
  `recency_weight_basis` is written to `feature_metrics.json` specifically
  so this distinction survives into the design note.

Computed once per impression (not cached per user, since the weight vector
itself is impression-time-dependent) from a per-user history lookup dict
(id/timestamp/read-time/scroll-percentage arrays, built once per dataset —
same shape as Q4's `history_lookup` in `evaluation_harness.ipynb`). Empty
history (cold-start) short-circuits to `click_count = 0`,
`weighted_category_affinity = 0.0` for every candidate,
`weighted_read_time`/`weighted_scroll_percentage`/`weighted_embedding_similarity`
= null, `category_match = False` — a well-defined value, not an excluded
row, consistent with Q4's cold-start-is-a-slice-not-an-exclusion framing.

Individual `read_time_sequence`/`scroll_percentage_sequence` *entries* can
be null even within a non-null, non-empty history — a real EB-NeRD data
fact (16,510/18,827 `ebnerd_small` users have at least one such entry), not
a pipeline bug. `weighted_read_time`/`weighted_scroll_percentage` average
only the non-null entries against their matching recency weights; null only
when *every* entry for that user is null (no usable dwell-time signal at
all), not per-entry.

## 4. `weighted_category_affinity`

Per impression: `cat_weight[c] = Σ weight_i` over history items whose
category is `c`; per candidate row: `weighted_category_affinity =
cat_weight.get(candidate_category, 0.0) / Σ weight_i` — the fraction of a
user's recency-weighted attention spent on the candidate's category,
mathematically in `[0, 1]` (a ratio of a subset-sum to the full sum of the
same weights, so floating-point summation order can push it a hair above
1.0 — observed max `1.0000000000000004` on `ebnerd_small`, checked with a
`1e-9` tolerance rather than a strict bound). Distinct from `category_match`
(§2), which is an unweighted
set-membership check; both are kept since they answer different questions
("how much" vs. "at all").

## 5. `weighted_embedding_similarity` and `embeddings.weighted_mean_pool`

`embeddings.py` gains `weighted_mean_pool(article_ids, weights,
embedding_lookup) -> np.ndarray | None`, a weighted generalization of the
existing `mean_pool` (uniform weights must reduce to bit-identical output —
enforced by a regression test in `feature_engineering.ipynb`, since this is
the only thing standing between a subtle sign/normalization bug and every
downstream feature that depends on it). Per impression, `weighted_mean_pool`
over the user's full history (ids + this impression's recency weights)
produces one pooled vector; `weighted_embedding_similarity` per candidate
row is that vector's cosine similarity to the candidate's own embedding.

The pooled vector itself is **not** persisted as a column — at
`ebnerd_large` scale, a 768-float column repeated over every inview
candidate would dominate the table's size for no benefit downstream (only
the scalar similarity is ever consumed by the re-ranker). This differs from
Q3/Q4's `embedding` adapter, which pools only the most recent
`RECENT_N_CLICKS` clicks with uniform weights — `weighted_embedding_similarity`
is a genuinely different feature (full history, recency-weighted), not a
duplicate, and both are legitimately available to the Q2 re-ranker (the
`embedding` adapter's score is joined in separately, per §1).

## 6. Session features — vectorized, not a per-row loop

`clicks_earlier_in_session` and `session_impressions_so_far` are computed
directly from `behaviors` (`session_id`, `impression_time`,
`article_ids_clicked`) with `polars` window functions over
`(user_id, session_id)` ordered by `impression_time` —
`session_impressions_so_far = cum_count() - 1` and
`clicks_earlier_in_session = cum_sum(article_ids_clicked.list.len()).shift(1).fill_null(0)`,
both `.over(["user_id", "session_id"])`. Unlike §3's history-based features,
this needs no per-user Python-level lookup or per-impression recomputation —
it is a property of the impression stream itself, computed once for the
whole split in a single vectorized pass, then broadcast to every candidate
row of that impression (same value for all of an impression's candidates).
For MIND (`session_id` entirely null, `has_session_data = False`), both
columns are null rather than computed against a meaningless single implicit
session.

## 7. `popularity` and `evaluation.train_popularity_lookup`

`evaluation.py` gains `train_popularity_lookup(article_ids,
train_clicked_lists) -> dict[str, float]`, factored out of what was
inline logic in `evaluation_harness.ipynb`'s novelty-lookup cell (Q4 §3):
add-one-smoothed `clicks_train(item) / total_train_clicks` for ever-clicked
items, `1 / (total_train_clicks + n_articles)` for never-clicked items.
`popularity` here is that same dict's raw value; Q4's `novelty` metric is
`-log2(popularity)` — both now computed from one function so the harness and
this notebook can never silently disagree on the formula. `evaluation_harness.ipynb`'s
Q4 cell was refactored to call this function instead of duplicating the
computation; verified bit-identical against `ebnerd_small`'s real train
split (`max|old_novelty − new_novelty| == 0.0` over all 20,738 articles)
rather than by rerunning the full `ebnerd_large`/`mind_large` harness for
this refactor alone.

## 8. `HistoryStore`: per-user history access without full materialization

Per-user history access is served by a `HistoryStore` holding a
`user_id -> row index` map plus the four `history` sequence columns as
polars `Series`, slicing one row on demand and caching the most recent
user. Two prior implementations were measured and rejected against real
data, in this order:

1. **`iter_rows(named=True)`** (one Python dict per row via polars'
   row-iteration path): 0.76s for `ebnerd_small`'s 18,827 users, and at
   `ebnerd_large`'s 974,791 users it had not finished after 8+ minutes.
2. **Column-wise `.to_list()` + `zip`** into a fully-materialized dict:
   0.07s on `ebnerd_small` — a 10.6x speedup over (1), byte-identical
   output — but it fixed only construction *time*, not the *memory* the
   result occupies, which is the binding constraint at scale.

The materialized dict costs **182 bytes per history element** (`tracemalloc`,
`ebnerd_small`: 445MB for 2,560,542 elements — Python `str`/`datetime`/`float`
objects and their list containers, not the compact Arrow buffers the parquet
holds). Applied to the real per-dataset element counts:

| dataset | users | history elements | materialized |
|---|---|---|---|
| `ebnerd_small` | 18,827 | 2,560,542 | 445MB (measured) |
| `mind_large` | 750,434 | 13,742,917 | ~2.3GB |
| `ebnerd_large` | 974,791 | 131,918,897 | **~22.4GB** |

`ebnerd_large` exceeds this machine's total RAM, and did so in practice: the
first full-scale attempt was killed at 10.3GB resident and climbing, mid-way
through building that dict, with a subsequent `Start-Process` call failing
as `Starting the CLR failed with HRESULT 80004005` — the machine could not
allocate for a new .NET runtime. This is the same genuine memory-exhaustion
class as Q4 #9's `WinError 10055`, reached deterministically rather than
intermittently.

`HistoryStore` keeps only the index map (2.1MB per 18,827 users, so ~110MB
projected at `ebnerd_large`) and materializes a single user's four sequences
per `get()` (~58µs measured), bounding memory by history *length* instead of
user *count*. The single-entry cache mirrors the BM25 adapter's last-user
cache in `evaluation_harness.ipynb` and is effective for the same reason:
`generate_features` iterates each split sorted by `user_id`, so a user's
impressions arrive consecutively and only the first pays extraction cost —
one extraction per *user* (~975K), not per *impression* (~16.2M).
`test_setup` asserts `HistoryStore.get()` returns exactly what the
materialized column would have, on both the cold and cached paths, plus the
absent-user path.

### Measured cost of every candidate at `ebnerd_large` scale

Each step below was measured in isolation (peak RSS of the worker process,
polled externally; `estimated_size()` for frames). Attribution mattered
because the expensive steps mask each other: with the `.over()` session
computation in the pipeline, sorted and unsorted source builds both measured
~11.7GB and the sort looked free; with the sort present, adding the session
join changed nothing and the join looked free. Only after making each step
cheap in turn did the others' real costs appear.

| step | peak | note |
|---|---|---|
| resident Arrow frames | 13.04GB | `behaviors` 7.83 (of which `article_ids_inview` 5.47), `history` 4.49, `embeddings` 0.72 |
| `meta` projection (5 cols + `list.len()`) | 4.2GB | result is only 1.80GB |
| session features via `.over()` | 9.34GB | 12.7s, result 0.68GB |
| session features via sort + `forward_fill` | 6.26GB | 3.7s — **−3.1GB, 3.4x faster** |
| split source: filter + sink | 7.48GB | baseline |
| split source: + `sort("user_id")` | 11.18GB | **+3.7GB** |
| split source: + session join (24.6M rows) | 11.48GB | **+4.0GB** |

So both whole-split operations are pipeline breakers that materialize the
split, and neither is worth its cost: the sort only feeds `HistoryStore`'s
last-user cache (~58µs/impression, measured ~11% of throughput once removed:
865 → 770 impressions/s), and the join is replaceable by joining each 200k
chunk against the persisted session file, where polars hashes the small side.

**The peaks stack.** Measured in isolation the source build peaks at 7.48GB,
but inside the notebook it runs with `history` (4.49GB) and the embedding
lookup already resident, and the observed process peak is 11.14GB against
15.7GB of RAM. Building every split's source file *before* the per-user
lookups are constructed would decouple the two (~7.5GB then ~5.5GB rather
than ~11GB once); the current implementation does not, and the ~4GB of
headroom is why the run survives rather than why it is safe. It did survive:
the completed `ebnerd_large` run held a flat 11.14GB peak across all three
source builds — the spike is dominated by scanning `behaviors.parquet`'s
list columns, which is identical work regardless of split size, so the
12,566,385-row test split cost no more than the 2,000,000-row train one —
and sat at ~6-7GB for the ~4.5 hours of chunk processing in between. This
is the change to make first if the dataset or the machine gets any larger.

The same Arrow-to-Python materialization trap appears twice more in
`generate_features`, and both are fixed the same way — keep data in Arrow,
convert only what a chunk needs:

- **Session features are persisted to a parquet, not held in a dict or
  joined per split.** A `impression_id -> (clicks_earlier,
  impressions_so_far)` dict costs 159 bytes per entry (`tracemalloc`,
  `ebnerd_small`: 72MB for 477,534 impressions), i.e. ~3.65GB over
  `ebnerd_large`'s 24,630,275 impressions, and covered the whole `behaviors`
  table rather than only the rows a split processes (`train` is capped at
  2,000,000 of 10,384,901). Joining them into each split's source instead
  cost +4.0GB (table above). They are written once to
  `_session_features.parquet` and joined per 200k chunk.
- **The session computation avoids partitioned windows.** Sorting by
  `(user_id, session_id, impression_time)` makes a group boundary a
  row-to-row comparison, so a global `cum_sum`/row index, forward-filled
  from each group's first row and subtracted, reproduces `.over()` exactly
  at −3.1GB and 3.4x the speed. The comparison must be `ne_missing`, not
  `!=`: `null != null` is null under three-valued logic while `.over()`
  groups nulls together, so `!=` would split MIND's all-null `session_id`
  into one group per row. Verified against the `.over()` reference on
  `ebnerd`/`ebnerd_small`/`mind` and on a toy fixture covering a multi-row
  session, a session boundary, and the all-null case.
- **Per-chunk `.to_list()`, not per-split.** `article_ids_inview` averages
  ~11.9 article-id strings per impression and the Arrow-to-Python conversion
  interns nothing across rows (the same effect that forced
  `evaluate_ranking`'s canonical-string pool, Q4 #9), so converting a whole
  split up front would materialize ~150M Python strings (~9GB) for
  `ebnerd_large`'s 12,566,385-impression test split. Slicing the split to
  the current chunk first bounds this to ~2.4M strings, freed as soon as the
  chunk parquet is written. It also means an already-checkpointed chunk
  costs no conversion at all on a resume.

The final merge uses `scan_parquet` + `sink_parquet` rather than reading
every chunk eagerly and concatenating in memory, which would otherwise
undo the per-chunk bound at the last step.

Every file this notebook writes goes through write-to-`.tmp`-then-
`os.replace` (`sink_parquet_atomic` for the streamed ones). The chunk writes
always did; `_session_features.parquet` and `_source_{split}.parquet` did
not, and both are guarded by "the file exists" checks, so a process killed
mid-write would have left a truncated file that the next run silently
accepted as complete. `os.replace` is atomic on Windows and POSIX, so a
visible file is always either absent or whole.

Every rewrite in this section was verified output-identical against the
pre-refactor feature tables for all three small-scale tracks (`ebnerd`
583,054 rows, `ebnerd_small` 5,514,689, `mind` 8,584,442; all 17 columns),
compared after sorting on `(impression_id, article_id)` since dropping the
sort changes row *order*, which is immaterial when every row carries its own
keys.

## 9. Scale, checkpointing, and observed throughput

Validated end-to-end on `ebnerd` (583,054 output rows), `ebnerd_small`
(5,514,689 rows, ~9.3 minutes) and `mind` (8,584,442 rows, ~68 seconds)
before any large-scale run, per this project's standing scaling discipline.
The ~8x per-impression
throughput gap between the two (~700-900 impressions/s vs. ~3,500/s) traces
to a real data fact, not an inefficiency: EB-NeRD's `history.article_id_sequence`
averages 136 items/user (median 69) vs. MIND's 21.7 (median 12) — each
impression's `compute_impression_history_summary` does `O(history length)`
work (recency weights, category-weight accumulation, `weighted_mean_pool`),
and that work is correctly recomputed per impression (not cached per user)
because the recency weights themselves depend on that impression's own
`impression_time` (§3). Final measured builds:

| dataset | impressions | output rows | wall-clock | rate |
|---|---|---|---|---|
| `ebnerd` | 50,080 | 583,054 | ~1.5 min | ~600/s |
| `ebnerd_small` | 477,534 | 5,514,689 | ~9.3 min | ~850/s |
| `mind` | 230,117 | 8,584,442 | ~68 s | ~3,500/s |
| `ebnerd_large` | 16,245,374 | 190,850,352 | **4h 54m** | ~920/s |
| `mind_large` | 2,609,219 | 97,592,931 | **15m 17s** | ~2,850/s |

`ebnerd_large` (2,000,000 capped train + 1,678,989 val + 12,566,385 test)
produced a 3.17GB parquet and ran uninterrupted at a flat 11.14GB peak.
`mind_large` (1,801,231 train — under the cap, so unsampled — plus 431,517
val and 376,471 test) is ~6x smaller in impressions but only ~2x smaller in
output rows, because MIND averages ~37 candidates per impression against
EB-NeRD's ~11.9; its ~3x higher per-impression rate comes from far shallower
histories (13,742,917 elements over 750,434 users, mean 18.3, vs.
131,918,897 over 974,791, mean 135.3). A numpy-vectorized (`datetime64[us]`) rewrite of
the per-item elapsed-time subtraction was benchmarked and rejected — at
this array size (tens of items), numpy's per-call construction overhead
(~24µs/call) is slower than the plain Python `datetime` subtraction loop it
would replace (~4.5µs/call for 24 items); there is no cheap win here without
changing what gets recomputed per impression, which would trade away the
per-impression recency correctness the whole design is built around. Worth
revisiting at Q4's serving-latency stage as a real speed/precision tradeoff
(e.g. bucketing recency to coarser time granularity to allow caching), not
as a change to this offline feature-table build.

Full `val` + `test` splits (needed for Q3's offline evaluation regardless of
Q2 training), plus a capped, seeded sample of `train` for re-ranker
training: `TRAIN_SAMPLE_CAP = 2_000_000` impressions per dataset,
`TRAIN_SAMPLE_SEED = 0` (`polars.DataFrame.sample`, without replacement,
applied only when a split has more than the cap). At EB-NeRD's ~11
candidates/impression average, this bounds `train`'s exploded row count to
~22M/dataset; at MIND's ~37-40, ~74-80M/dataset — both in the low tens-of-GB
range on disk, not the ~100-370M-row table an unsampled `ebnerd_large`/
`mind_large` train split would explode to. Same chunked
(`CHUNK_SIZE = 200_000` impressions), atomically-written (`os.replace`),
resumable-on-crash checkpointing as every other long-running loop in this
project (`evaluate_ranking`, `generate_predictions`), plus a
`FEATURE_DATASETS` env var (mirrors `EVAL_DATASETS`) so `ebnerd_large` and
`mind_large` are never built in the same kernel.

## 10. Anti-gaming (Q9): recompute-from-truncated-input

`test_no_future_leakage_in_features` asserts, for a sample of impressions,
that every history item actually consumed has `timestamp_i <
impression_time` (EB-NeRD) — mechanically guaranteed already since
`history.article_id_sequence` is a pre-collection-window snapshot (A1 Q1
§2), but checked directly against the real weight computation here rather
than assumed. A second, stronger check: for one sampled user, manually
truncate their history to a prefix, recompute `click_count`,
`weighted_read_time`, and `weighted_scroll_percentage` by hand from that
truncated input, and diff against the notebook's own output for an
impression scored against the truncated history — must match up to
floating-point tolerance (a weighted average of a single point equals that
point mathematically, but `x*w/w` is not bit-exact for arbitrary `x, w` in
IEEE 754). Skipped (not failed) on a `FEATURE_DATASETS`-scoped run with no
elapsed_time-basis dataset present (e.g. MIND alone) — there is no
timestamp data at all to run this specific check against in that case; the
leakage check itself still runs for every dataset regardless of basis. This
is the "features unavailable at serving time" toggle A1 had nothing
analogous to (Q4 §7): the with/without comparison itself is deferred to
Q3's ablation (recency-weighted vs. uniform history) and Q9's own
with/without-session/dwell-time-features run, both of which reuse this
notebook's output rather than duplicating feature computation.

# A2 Q2 — Two-Stage Retrieve-Then-Rank

## 1. Goal

Stage 1 is Assignment 1's retrieval, unchanged: BM25 and embedding
`score_inview` adapters over each impression's own `article_ids_inview`.
Stage 2 is a LightGBM re-ranker trained on click labels that re-scores those
same candidates. "Before" is the Stage-1-only ranking already recorded in
`eval_metrics.json`; "after" is the identical impressions re-scored by the
re-ranker, so the comparison isolates the re-ranker rather than a change of
candidate set.

## 2. Feature set

Fifteen features, assembled positionally by `reranker.feature_matrix` from a
fixed `FEATURE_COLUMNS` order. Order is fixed deliberately: LightGBM
identifies features by position, so a booster trained on one column order and
served on another produces silently wrong scores rather than an error.

**Behavioural (11)** — from Q1's `reranker_features.parquet`:
`click_count`, `weighted_category_affinity`, `weighted_read_time`,
`weighted_scroll_percentage`, `weighted_embedding_similarity`,
`position_in_impression`, `clicks_earlier_in_session`,
`session_impressions_so_far`, `popularity`, `freshness_hours`,
`category_match`.

**Stage-1 retrieval (4)** — from `reranker_scores.parquet`: `bm25_score`,
`embedding_score`, `in_bm25_top200`, `in_embedding_top200`.

Nulls become NaN, which LightGBM treats as a first-class missing value and
routes at each split. That is what lets one feature set serve both dataset
families: MIND has no dwell-time, session or freshness data at all (A2 Q1 §2),
so five columns are entirely NaN there and simply yield no split gain — no
separate architecture, and no sentinel value a tree could mistake for a real
measurement. Models are trained **per dataset** regardless: the catalogs,
candidate counts (~11.9 vs ~37 per impression) and positive rates
(`ebnerd_large` 9.02%, `mind_large` 4.10%) all differ.

## 3. Retrieval scores: produced locally, on a sample

`bm25_score`/`embedding_score` exist nowhere on disk after A1 — Q4's harness
computes them live and keeps only per-impression metrics — so `A2 Q2` adds
`src/reranker_scores.ipynb`, which persists them per `(impression_id,
article_id)` into `reranker_scores.parquet`.

**Local, not Kaggle.** The BM25 index and embedding matrix are built here, and
Kaggle hosts only the GPU-bound training step — the same split used for the
embeddings themselves. Scoring is also the expensive half, and a multi-hour
loop fits a local machine better than a Kaggle session limit.

**Sampled: `SCORE_IMPRESSIONS = {train: 400_000, val: 100_000}`, seed 0.**
Every scored impression costs a BM25 query over the full catalog, and the
measured rates are 517 impressions/s (`ebnerd_large`) and 323/s
(`mind_large`). Scoring both splits in full would be ~2.0h and ~1.9h
respectively against ~16min and ~26min sampled — ~4h versus ~45min — for a
design matrix that is already 4,437,171 rows (`ebnerd_large`) and 14,721,197
(`mind_large`) against 15 features. `test` is deliberately not scored: the
serving adapter computes Stage-1 scores live, which is also what guarantees
training-time and serving-time features are identical.

The sample is uniform-random over impressions at a fixed seed, so it carries
no systematic bias and preserves the positive rate. It also cannot corrupt
the evaluation — the re-ranker is evaluated on the *full* val/test through the
live adapter, so an undertrained model shows up as a worse measured metric
rather than a hidden one.

**The sufficiency of 400,000 is measured, not asserted.** The training
notebook fits the same configuration on 100k/200k/400k-impression subsamples
and reports validation AUC for each. A curve that has flattened by 400k is
evidence that more scored impressions would not have helped; a still-rising
curve is evidence the cap should be raised. Either way the design note
reports the curve rather than a judgement call.

## 4. Determinism: `sorted(set(query_tokens))` in `bm25.get_scores`

`get_scores` accumulated its per-term contributions while iterating
`set(query_tokens)`. Python randomizes string hashing per process, so the set
iterated in a different order in every run, and float addition is not
associative: identical input produced BM25 scores differing by ~5e-16
relative across two processes (measured; within-impression rankings were
unaffected, but the values were not reproducible). Iterating `sorted(set(...))`
costs nothing on a query-sized token set and makes BM25 bit-reproducible —
verified by checksumming the score vector from two separate processes.

This was found by a feature-equivalence check in A2 that expected two runs to
agree exactly; it applies equally to Q2/Q3/Q4's already-persisted artifacts,
whose values were therefore reproducible only to ~1e-15 before this fix.

## 5. Measured memory findings

Same class of problem as A2 Q1 §8 — Arrow data materialized as Python
objects — found three more times in this stage, each measured in isolation
before being changed:

| structure | cost at `ebnerd_large` | fix |
|---|---|---|
| full `history_lookup` dict | 8.61GB | truncate to last 20 clicks in Arrow → 1.27GB |
| `top_k_membership` dicts | 164,222,200 ids **per method** | explode + left join in Arrow |
| embedding matrix via list comprehension | 4.80GB peak, 39x slower | `.list.to_array(dim).to_numpy()` |

Per-step peaks measured in isolated processes: history 6.05GB, BM25 index
0.51GB, embeddings 4.80GB, sampling 5.64GB. **They stack** when everything is
built before scoring, which is what produced a 12.13GB peak with free RAM at
0.3GB on a 15.7GB machine. Sampling is therefore performed *before* the
per-user lookups are constructed, so each transient occurs alone; the run
then peaks at 11.53GB (`ebnerd_large`) and 8.69GB (`mind_large`) during setup
and settles to ~4.4GB for the scoring loop itself. The residual setup
transient is the sampling step reading `behaviors`' 5.47GB
`article_ids_inview` column, which a per-chunk read would remove if this ever
needs to run on a larger catalog.

Every one of these rewrites was verified output-identical on the `ebnerd`
demo track before being run at scale — scores equal within 1e-12 and
membership flags bit-identical.

## 6. One adapter implementation, shared between training and serving

`bm25_score` and `embedding_score` are simultaneously *baselines* and
*features*. That dual role makes a duplicated implementation a correctness
risk rather than mere repetition: if the code that generated the training
values and the code that generates them at serving time diverge at all, the
input distribution shifts under a fixed model, silently and with no error.

`cs4406m26_assignment1c1.retrieval.build_stage1_scorers` is therefore the
single definition, used by `reranker_scores.ipynb` (training features),
`reranker_evaluation.ipynb` (serving) and available to
`evaluation_harness.ipynb`. It carries the memory shape established in §5:
history truncated to the last 20 clicks in Arrow, embeddings converted
columnar.

The two prior copies were not quite identical, and the difference is
recorded here because it decides which one the shared module follows.
`evaluation_harness.ipynb` built its embedding lookup with `np.asarray(v)`
over Python floats, so the *query* vector was pooled in float64 before being
compared against a float32 corpus; `reranker_scores.ipynb` pools in float32
throughout. Measured over 3,000 `ebnerd` val impressions the two differ by at
most **1.192e-07** (float32 epsilon), with **zero ranking-order flips** and
per-impression AUC equal to ten decimal places. The shared module follows the
float32 path — matching the distribution the booster was actually fitted on
matters more than matching the older harness — and A1's already-published
baselines are unaffected. BM25 scores are bit-identical between all three.

The adapter signature widens to `fn(user_id, article_ids_inview,
impression_id=None)`. The behavioural features are per-impression
(`position_in_impression`, `clicks_earlier_in_session`,
`session_impressions_so_far`, `freshness_hours`), so a two-argument contract
carrying no impression identity cannot express the re-ranker at all. BM25 and
embedding accept and ignore the third argument.

## 7. Evaluation population: common, sampled, and verified representative

All three methods are scored on one common set of `EVAL_IMPRESSIONS = 200_000`
impressions per split per dataset, drawn at `EVAL_SEED = 0`. Two independent
reasons:

1. **The paired CI requires it.** `paired_bootstrap_ci` (§8) resamples one
   index set and applies it to both methods' per-impression arrays. That is
   only meaningful if position *i* denotes the same impression in both.
2. **Full coverage is unaffordable on one of the two datasets.** The
   re-ranker consumes `bm25_score`/`embedding_score` as features, so
   evaluating an impression requires a full Stage-1 pass over it. After A1,
   those scores exist on disk for 500,000 sampled impressions only (400k
   train, 100k val) and for **no test impression at all**.

Throughput measured from the per-chunk checkpoint timestamps in
`build_progress.log`, restricted to 50,000-**impression** chunks (A1's
`evaluate_ranking` and `feature_engineering` log an identically-shaped line
for 200,000-**row** chunks, and mixing the two inflates the figure by ~2x):

| pass | `ebnerd_large` | `mind_large` |
|---|---|---|
| training-feature scoring (`reranker_scores`, train split) | 527 imp/s | 324 imp/s |
| evaluation scoring (`reranker_evaluation`, val/test) | ~430 imp/s | ~283 imp/s |

The evaluation pass is the slower of the two — it also materializes the click
labels, and val/test impressions carry more candidates than train's (11.95 vs
11.12 on `ebnerd_large`) — so it is the rate that governs this decision:

| dataset | val+test impressions | full-population Stage-1 cost | at 200k/split |
|---|---|---|---|
| `mind_large` | 807,988 | ~48 min | ~24 min |
| `ebnerd_large` | 14,245,374 | **~9.2 h** | ~16 min |

The sample is not *assumed* representative. `eval_metrics.json` holds BM25 and
embedding measured over every val and test impression, so
`write_reranker_eval_metrics` re-measures those same two methods on the sample
and asserts the sample's own 95% CI covers the full-population point estimate
— the correct direction, since the sample is the noisy measurement and the
full population is the reference. A skewed draw (toward short inview sets,
heavy users, a narrow time window) fails that assertion rather than hiding
inside the comparison. The check is recorded per split under
`sample_agreement` in `reranker_eval_metrics.json`.

## 8. `evaluation.paired_bootstrap_ci`

A2 Q3 requires a 95% CI on the baseline-vs-improved difference that excludes
zero. `bootstrap_ci` is single-sample and cannot express this: two independent
intervals that happen to overlap do **not** imply the difference is
insignificant. Per-impression difficulty is shared between methods — a
one-candidate impression is easy for both, a 40-candidate one hard for both —
and that shared variance cancels in the difference. Resampling one index array
and applying it to both is what makes it cancel; drawing two independent index
sets discards the pairing and degrades to the weaker unpaired test.

Implementation differences the resampling: `mean(b[idx]) - mean(a[idx])` and
`mean((b-a)[idx])` are identical because means are linear, and differencing
first halves both memory and fancy-indexing work. Chunked by
`max_chunk_cells` exactly like `bootstrap_ci`, for the same reason (a
single-shot `(1000, 12.5M)` index array would be ~100GB); because numpy fills
row-major, chunked and unchunked runs are bit-identical at a fixed seed.

Verified on synthetic data with a known +0.02 effect and shared
per-impression difficulty: the interval covers the true effect and excludes
zero; the paired interval is **6.7x tighter** than the unpaired one on the
same data; a no-effect pair yields an interval containing zero; chunked
equals unchunked exactly; shape mismatch and empty input raise.

## 9. Training-set size: measured, not asserted

The 400,000-impression training cap (§3) is justified by a learning curve
rather than by argument. `reranker_training_kaggle.ipynb` fits the same
configuration at 100k/200k/400k impressions on **nested** subsamples — the
100k set is a subset of the 200k set, which is a subset of the 400k set — so
successive points differ only by added data and the curve is not confounded
by disjoint draws. Validation AUC (per impression):

| training impressions | `ebnerd_large` | `mind_large` |
|---|---|---|
| 100,000 | 0.6701 | 0.6183 |
| 200,000 | 0.6698 | 0.6176 |
| 400,000 | 0.6655 | 0.6158 |

The curve is flat to slightly declining on both datasets: 400,000 is not
merely sufficient, it is past the point where added impressions help.
`best_iteration` lands at 53 and 45 against a 2,000-round budget with
50-round early stopping, so the models converge almost immediately. The
binding constraint on this stage is the **feature set**, not the sample size,
and the plotted curve is `reranker_learning_curve.png`.

## 10. Evaluation pipeline shape

`src/reranker_evaluation.ipynb` (wrapper: `reranker_evaluation.py`,
`RERANK_EVAL_DATASETS` to scope a run to one dataset per kernel).

1. Sample the evaluation population per (dataset, split); sort by
   `impression_id` **before** sampling, since polars' `unique` dedupes by hash
   with no ordering guarantee (§4), then re-sort by `user_id` so the BM25
   one-entry cache hits on consecutive impressions.
2. Stage-1 score, chunked at 50,000 impressions with atomic per-chunk
   checkpoints; attach top-200 membership columnar.
3. Join Q1's behavioural features (read back, never recomputed) and run the
   booster.
4. Per-impression `auc_impression`/`mrr`/`ndcg_at_k` — A1's functions
   unchanged, so baselines and re-ranker are scored by identical code.
5. Bootstrap CI per method, paired CI per (baseline, re-ranker) pair, the
   `sample_agreement` check of §7, all persisted to
   `reranker_eval_metrics.json`.

Peak-avoidance follows §5's rule that separately-cheap transients stack: the
BM25 index and embedding matrix are released as soon as scoring ends and
before the metric frames are built, and the Stage-1 frames are released once
the re-ranked frames (which contain every Stage-1 column) exist. A resume
whose `reranker_eval_{split}.parquet` already exists skips Stage-1 entirely
rather than loading scores it would discard.

## 11. Assertions that caught real properties of the data

Each of these failed on correct code and encodes something true about the
datasets rather than a bug that was fixed:

- **Duplicate clicks.** EB-NeRD lists the same article twice in one
  impression's `article_ids_clicked` when a user clicked it twice — 3,608
  such entries in `ebnerd_large` val, none in MIND. The per-candidate label
  is boolean, so the label count must be compared against *distinct* clicked
  ids. Every clicked article is in its impression's `article_ids_inview` on
  both datasets (checked separately: a positive outside the inview set would
  silently cap every metric).
- **nDCG@10 can be lower than nDCG@5.** `ndcg_at_k` normalizes by IDCG@k over
  `min(n_pos, k)` terms, so an impression with 6 clicks gets a 6-term IDCG@10
  against a 5-term IDCG@5 — the denominator grows while the numerator need
  not. A constructed 6-click case gives 1.000 vs 0.892. The monotonicity
  check holds only where `n_pos <= 5`.
- **uint32 -> uint64 -> float64.** polars' `len()` returns UInt32; numpy's
  `cumsum` promotes that to uint64; there is no common integer type for int64
  and uint64, so `np.concatenate([[0], np.cumsum(lengths)])` resolves to
  float64, which cannot be used as a slice index. The accumulator is pinned
  with `cumsum(dtype=np.int64)`.
- **Score-spread checks must not assume ensemble size.** A wrong feature order
  raises nothing; it produces a near-constant score. The check is that scores
  separate candidates *within* an impression, not that a fixed number of
  distinct values exists — the small-track smoke model has 4 trees and emits
  976 distinct values where the Kaggle-trained models have 45-53 trees.

## 12. Results

Per-impression AUC over 200,000 impressions per split, every method scored on
the identical impressions (`reranker_eval_metrics.json`):

| dataset | split | BM25 | embedding | re-ranker |
|---|---|---|---|---|
| `ebnerd_large` | val | 0.5088 | 0.5597 | **0.6664** |
| `ebnerd_large` | test | 0.5015 | 0.5511 | **0.6490** |
| `mind_large` | val | 0.5584 | 0.6102 | **0.6158** |
| `mind_large` | test | 0.5569 | 0.5944 | **0.6099** |

Paired bootstrap 95% CI on the difference against the stronger Stage-1
baseline (embedding), 1,000 iterations, same impressions on both sides. Every
interval excludes zero:

| dataset | split | Δ AUC | 95% CI | Δ nDCG@5 |
|---|---|---|---|---|
| `ebnerd_large` | val | +0.1066 | [+0.1050, +0.1082] | +21.6% |
| `ebnerd_large` | test | +0.0979 | [+0.0964, +0.0996] | +22.1% |
| `mind_large` | val | +0.0057 | [+0.0046, +0.0068] | +2.8% |
| `mind_large` | test | +0.0155 | [+0.0145, +0.0166] | +5.5% |

**Sample representativeness.** The check described in §7, run on all eight
(dataset, split, baseline) combinations, comparing the sampled 200,000-impression
estimate against A1's exhaustive measurement:

| dataset | split | method | sampled | full population | abs diff |
|---|---|---|---|---|---|
| `ebnerd_large` | val | bm25 | 0.5088 | 0.5087 | 0.0001 |
| `ebnerd_large` | val | embedding | 0.5597 | 0.5589 | 0.0008 |
| `ebnerd_large` | test | bm25 | 0.5015 | 0.5012 | 0.0003 |
| `ebnerd_large` | test | embedding | 0.5511 | 0.5518 | 0.0007 |
| `mind_large` | val | bm25 | 0.5584 | 0.5590 | 0.0005 |
| `mind_large` | val | embedding | 0.6102 | 0.6103 | 0.0001 |
| `mind_large` | test | bm25 | 0.5569 | 0.5565 | 0.0004 |
| `mind_large` | test | embedding | 0.5944 | 0.5939 | 0.0004 |

Maximum disagreement 0.0008, and every full-population value falls inside the
sample's own 95% CI. The ~9.2 hours of Stage-1 scoring that exhaustive
coverage would have cost on `ebnerd_large` buys no measurable change in the
comparison.

**The gap between the two datasets is the substantive finding.** The
re-ranker's advantage is roughly an order of magnitude larger on EB-NeRD
(+0.10 AUC) than on MIND (+0.006 to +0.016), and the feature importances say
why: seven of fifteen features carry zero split gain on `mind_large` against
two on `ebnerd_large`.

| zero-gain features | `ebnerd_large` | `mind_large` |
|---|---|---|
| `in_bm25_top200`, `in_embedding_top200` | both | both |
| `weighted_read_time`, `weighted_scroll_percentage` | — | zero |
| `clicks_earlier_in_session`, `session_impressions_so_far` | — | zero |
| `freshness_hours` | **48.1% gain (largest)** | zero |

Five of those are the columns MIND's raw data never contained (A2 Q1 §2), so
the re-ranker is working from eight usable features there against thirteen on
EB-NeRD — and the single most informative EB-NeRD feature, `freshness_hours`
at 48.1% of total gain, is exactly one of the absent ones. The gain is
therefore bounded by how much behavioural signal the log actually carries,
not by the model: the same architecture, features and hyperparameters applied
to a log without dwell-time, session or publish-time data recovers a small
though statistically unambiguous improvement, while the same pipeline on a
log that has them recovers a large one.

**The two top-200 membership features are dead weight on both datasets.**
Zero split gain everywhere, and not because the join failed: the flags are
`True` on 0.68%/0.39% of `ebnerd_large` rows and 0.59%/0.45% of `mind_large`
rows with no nulls. A user's corpus-wide top-200 simply almost never
intersects the specific candidates that user is shown, which is the same
candidate-set fork A1's Q4 already had to resolve (Q4 §1) reappearing as a
feature-level result. They are retained in `FEATURE_COLUMNS` because removing
them would invalidate the trained boosters' positional column order for no
measured benefit, but they should be dropped if the models are ever retrained.

# A2 Q3 — Baseline Reproduced, Then Beaten

## 1. Scope and shape

Two notebooks:

- `src/nrms_inputs.ipynb` (wrapper `nrms_inputs.py`, `NRMS_INPUT_DATASETS` to
  scope a run) — local, builds `data/kaggle_nrms/` from the A1 feature store.
- `src/nrms_baseline_kaggle.ipynb` — Kaggle, GPU + internet, runs all four
  parts of Q3 (baseline, improvement, ablation, paired CIs) and writes
  `nrms_metrics_{dataset}.json`, `nrms_{variant}_{dataset}.weights.h5`,
  `nrms_ablation.png`, `nrms_paired_ci.png`.

Inference is **not** local (unlike A2 Q2's re-ranker, and unlike the earlier
plan of a `tf2onnx` export plus local `onnxruntime` scoring). Q3 items 2–4
each require inference: the ablation needs three trained variants scored on
one common population, and the paired CI needs their per-impression metric
arrays aligned index-for-index. Keeping training and scoring in the same
kernel makes that alignment structural rather than something two separate
processes have to agree on, and removes the ONNX export from the critical
path entirely. The trained weights are still downloaded, so local scoring
remains possible without re-fitting.

Both datasets run through **one** code path: `NRMSDocVec` applied to
`ebnerd_large` and `mind_large` alike. The alternative — `ebnerd-benchmark`
for EB-NeRD, `recommenders-team/recommenders`' NRMS-on-MIND for MIND — was
rejected: it means two model implementations, a GloVe-tokenised title
pipeline for MIND instead of the document vectors A1 already computed, a
second dependency stack that expects raw `MINDsmall` files, and MIND numbers
that are not comparable to EB-NeRD's. The assignment's wording ("e.g. NRMS
from the ebnerd-benchmark repo, or the MIND baseline") admits either.

## 2. Baseline: the authors' code, pinned and unmodified

`NRMSDocVec` is imported from a clone of
`github.com/ebanalyse/ebnerd-benchmark` at commit
`5164e2ce7c92b99cbcb853d5f804cc95f0232b2f`, so "the baseline" names one
revision. `test_environment` asserts the checked-out HEAD equals that commit,
that `git status --porcelain` is empty (an unmodified working tree — a
reproduction, not a rewrite), and that `NRMSDocVec`/`AttLayer2`/`SelfAttention`
were imported from the clone's path rather than from anything shadowing it.

`hparams_nrms_docvec` keeps its published values (16 heads × 16 dims,
200-unit attention, `[512, 512, 512]` news encoder, dropout 0.2, Adam 1e-4,
categorical cross-entropy, `npratio` 4, batch 32); only `title_size` (768,
asserted against the embedding data) and `history_size` (20) are bound to our
inputs. Every variant is fitted with the identical hyperparameters.

`NRMSDocVec` consumes precomputed document vectors, which is why it is the
right baseline here: A1 Q3's `article_embeddings.parquet` is exactly its news
input, for both datasets, so the reproduction does not need a text encoder or
a vocabulary and both datasets stay in one vector space.

### Imported from the clone, not `pip install .`

`ebrec` pins `polars==0.20.8`, `numpy<1.26.1`, `torch<2.3` and
`transformers<4.37.3`. Installing it downgrades Kaggle's stack underneath a
running kernel (or fails to resolve), for dependencies this notebook does not
need: `nrms_docvec.py` and `layers.py` import nothing but `tensorflow` and
`numpy`. `sys.path` is extended to the clone's `src/` instead.

Their **dataloader** is the piece that actually needs the pinned polars —
`map_list_article_id_to_value` calls `Expr.replace(default=...)`, whose
`default` argument was removed in polars 1.0 — so batching is reimplemented
(§5) and checked against their semantics rather than being used from the
package.

### Legacy Keras is mandatory

`layers.py` is written against the Keras 2 backend API (`K.dot`,
`K.permute_dimensions`, `K.one_hot`, `K.squeeze`), all removed in Keras 3, so
under Kaggle's default TF the authors' layers cannot run at all. The setup
cell sets `TF_USE_LEGACY_KERAS=1` **before** the first `import tensorflow`,
installs `tf-keras` if absent, and registers `sys.modules["tensorflow.keras"]
= tf.keras` because `layers.py` does `import tensorflow.keras as keras` and
that module *path* is a lazy-loader shim whose importability varies by TF
version. `test_environment` asserts `tf.keras.__version__` starts with `2.`
and that the five backend functions used exist — without it the failure
surfaces much later, inside the first model build.

## 3. Improvement: a recency prior on the history attention

`NRMSDocVec` pools history with multi-head self-attention followed by
additive attention (`AttLayer2`). That pooling is order- and time-blind:
permuting a user's history leaves the user vector unchanged. The change adds
one term to the attention exponent,

```
a_i = exp(q . tanh(W h_i + b) + log w_i)      i.e.  a_i = w_i * exp(logit_i)
```

so recency multiplies the learned attention instead of replacing it, and
`log w_i = 0` recovers the authors' layer.

`log w_i = -ln2 * age_i / half_life`, then shifted so each row's maximum is 0
(exactly invariant, since the weights are renormalised immediately, and it
keeps `exp` away from underflow). Bases and half-lives are A2 Q1 §3's,
unchanged, rather than a third notion of recency:

| dataset | `recency_weight_basis` | `age_i` | half-life |
|---|---|---|---|
| `ebnerd_large` | `elapsed_time` | `impression_time − timestamp_i`, hours | 72 hours |
| `mind_large` | `ordinal_proxy` | clicks back from the most recent | 5 clicks |

Weights are per **(impression, click)**, not per user: the history is a fixed
pre-window snapshot, but a click decays further between a user's first and
last evaluated impression, and a per-user vector would misprice that.
**Log**-weights are what the data path produces and the layer consumes;
weights are never materialised, so EB-NeRD's older clicks cannot underflow.

`RecencyAttLayer2` subclasses `AttLayer2`, overriding `call` (and `build`,
which forwards the vector branch's shape so the weight shapes and
initialisers stay the parent's). It **adds no weights**, so all three variants
have identical parameter counts — asserted, and the reason a measured
difference cannot be capacity. `NRMSDocVecRecency` subclasses `NRMSDocVec`
and overrides only `_build_userencoder`/`_build_nrms`; the news encoder, loss,
optimiser and hyperparameter handling are inherited.

## 4. Ablation: three variants, because the improvement bundles two effects

A padded history slot is a zero document vector, and `AttLayer2` still
assigns it positive attention (`exp(logit)` of a zero vector is not zero).
`log w = -1e9` on padded slots removes them exactly — a real fix, but not the
recency signal. A two-way comparison would credit recency for it.

| variant | log-weights | isolates |
|---|---|---|
| `baseline` | (no such input) | the authors' model |
| `masked_uniform` | 0 on real slots, `-1e9` on padding | padding mask only |
| `recency` | §3's log-weights | padding mask + recency |

Three paired comparisons per split follow: `baseline_vs_recency` (the headline
claim), `masked_uniform_vs_recency` (the recency signal alone),
`baseline_vs_masked_uniform` (the mask alone). The point estimates decompose
exactly — the first is the sum of the other two, because every term is a mean
over the same impressions — which `test_payloads` asserts as an internal
consistency check on the ablation.

`test_recency_layer` carries the load-bearing assertion: with all-zero
log-weights and the parent's weights copied in, `RecencyAttLayer2` reproduces
`AttLayer2`'s output **bit for bit** (`np.array_equal`). Hence the same
`+ K.epsilon()` denominator as the parent rather than a numerically
"improved" softmax — a max-subtracting stable softmax would make the
reduction approximate, and an approximate reduction cannot distinguish a real
improvement from an accidental reimplementation difference. Three further
assertions: adding a constant to every log-weight cannot change the output
(renormalisation), a `-1e9` slot contributes exactly nothing (changing that
slot's vector leaves the output unchanged), and a large positive log-weight
pulls the pooled vector toward that slot.

Cold-start impressions are kept, not excluded (consistent with Q4 §4's
cold-start-is-a-slice framing): every slot is padding, so the improved
variants produce a zero user vector and a fully tied ranking, which every
metric handles.

## 5. Inputs, sampling, and why the evaluation population is Q2's

`nrms_inputs.ipynb` writes, per dataset:

```
data/kaggle_nrms/nrms_{dataset}_train.parquet   impression_id, user_id, impression_time,
data/kaggle_nrms/nrms_{dataset}_val.parquet     article_ids_inview, article_ids_clicked
data/kaggle_nrms/nrms_{dataset}_test.parquet
data/kaggle_nrms/nrms_{dataset}_history.parquet user_id, article_id_sequence[<=20],
                                                timestamp_sequence[<=20] (elapsed_time only)
data/kaggle_nrms/{dataset}_article_embeddings.parquet   (staged copy of A1 Q3's)
data/kaggle_nrms/nrms_inputs_manifest.json
```

Sampling has to happen locally: `ebnerd_large`'s `behaviors.parquet` is 24.6M
rows / 7.8GB, of which `article_ids_inview` alone is 5.47GB (A2 Q1 §8).

`val`/`test` are drawn by `sample_eval_impressions` — Q2's function verbatim,
`EVAL_IMPRESSIONS = 200_000` at `EVAL_SEED = 0`, including the sort-before-
sample detail that made it reproducible at all (A2 Q2 §4). So Q3's NRMS
numbers and Q2's BM25/embedding/re-ranker numbers describe the same
impressions and can be quoted in one table. This is asserted, not inferred
from the shared seed: where `reranker_eval_{split}.parquet` exists,
`test_eval_population` compares the two impression-id lists element by
element. `train` is a 400,000-impression seeded sample, the cap A2 Q2 §9
already measured a learning curve for.

History is truncated to `HISTORY_SIZE = 20` and restricted to the users the
three impression files actually reference (`ebnerd_large`'s `history.parquet`
holds 974,791 users; the rest would be dead weight in the upload).
`timestamp_sequence` is carried only for datasets that really have it, decided
by **null count, not dtype** — the two MIND tracks write the same
semantically-absent column with different types (`mind` as `Null`,
`mind_large` as `String`, both 100% null), and a dtype test classified
`mind_large` as having timestamps (A2 Q1 §3).

The Kaggle notebook auto-discovers whichever `nrms_*_train.parquet` files are
attached (same pattern as `compute_embeddings_kaggle.ipynb`), so a session can
be scoped to one dataset when the GPU budget is tight, and finds
`{dataset}_article_embeddings.parquet` anywhere under `/kaggle/input` so an
existing A1 upload can be reused instead of re-staged.

### Everything columnar, nothing materialised as Python objects

The same trap A2 Q1 §8 and Q2 §5 document, avoided by construction here:
article-id to matrix-row mapping is an explode + left join in polars, history
matrices come out via `list.to_array(width).to_numpy()` (A2 Q2 §5 measured
that conversion at 39× a list comprehension), and candidate sets are stored
CSR-style — one flat `cand` array plus `offsets` — rather than padded to
MIND's maximum in-view size of 299. Right-alignment with zero padding matches
`truncate_history(padding_value=0)`, and index 0 is the article matrix's
zero/unknown row, exactly as `create_lookup_objects` defines it;
`test_inputs` checks our index and matrix against that function directly on a
500-article sample, so the layout is verified against the authors' own
definition rather than assumed.

### Negative sampling

Wu et al. (2019): one training sample per **distinct** clicked article, that
positive plus `NPRATIO = 4` negatives drawn with replacement from the same
impression's non-clicked candidates, shuffled, labelled one-hot over 5
positions — which is what the softmax head and categorical cross-entropy
expect. Distinct matters: EB-NeRD lists the same article twice in one
impression's `article_ids_clicked` when it was clicked twice (A2 Q2 §11).
Reimplemented in numpy at a fixed seed because their
`sampling_strategy_wu2019` needs the pinned polars; `test_training_samples`
verifies every sampled group against its source impression (the positive is
clicked, the negatives are not), asserts bit-identical output on a re-run, and
cross-checks their function on a small fixture when it imports.

Early stopping runs on the **last calendar day** of the training sample,
mirroring `ebnerd_nrms_docvec.py`'s own `last_dt` rule, with a chronological
90/10 fallback for a track whose train split spans a single day. Our `val`
split is therefore never used for model selection: it is reported, not tuned
against.

## 6. Scoring: user vectors once per impression, not once per candidate

`ebnerd_nrms_docvec.py` scores through `model.scorer.predict(dataloader)`,
which flattens every (impression, candidate) pair into its own row and
re-encodes the user's whole 20-click history **once per candidate**. That is
redundant by construction: `NRMSDocVec` scores by a dot product between a
user vector that depends only on the history and a news vector that depends
only on the article. So:

- the news encoder runs once over the whole catalogue (125,541 / 104,151
  articles, padding row included) per (dataset, variant), reused for both
  splits;
- the user encoder runs once per impression, chunked at `USER_BATCH = 1024`;
- the score is their dot product — the same number the scorer's final `Dot`
  layer produces, before a sigmoid that cannot reorder anything.

This removes a factor of ~11.9 (EB-NeRD) to ~37 (MIND) of news-encoder work
per split, and it is why the improvement was chosen to keep the user vector
candidate-independent: a candidate-aware user encoder (the obvious
alternative "attention over history" change) would reintroduce that factor at
serving time as well as offline.

`test_scoring_equivalence` checks the shortcut against
`model.scorer.predict` on 128 impressions per variant: `sigmoid(dot)` matches
their scorer within 1e-4, ranking flips are counted (tolerance 1 per 100
impressions — a flip is only possible where two candidates sit closer than
float32 noise, ~1e-6, which cannot move a reported metric), and the measured
speedup is printed. The one-off catalogue encoding is excluded from both
timings and amortises over every impression of both splits.

## 7. Metrics and significance

`auc_impression`, `mrr`, `ndcg_at_k`, `bootstrap_ci` and
`paired_bootstrap_ci` are restated from
`src/cs4406m26_assignment1c1/evaluation.py` because Kaggle has no access to
the repo, and must stay identical — A1 and A2 Q2's numbers came from them.
`test_metrics` pins them to hand-computed values, including the two
tie-handling details that are silently wrong if changed (average ranks for
AUC ties, stable argsort elsewhere) and the case where nDCG@10 falls *below*
nDCG@5 (A2 Q2 §11): six positives at ranks 1–5 and 7 of eight candidates give
nDCG@5 = 1.000 against nDCG@10 = 0.993078. It also reproduces A2 Q2 §8's
paired-CI checks (covers a known +0.02 effect, excludes zero, ≥4× tighter than
the unpaired interval on the same data, chunked equals unchunked at a fixed
seed) and cross-checks the mean AUC against ebrec's own `AucScore` when their
evaluation module imports — asserted outside the `try`, so a real
disagreement fails instead of being reported as a skipped check.

`nrms_metrics_{dataset}.json` mirrors `reranker_eval_metrics.json`'s shape
(`hyperparameters`, `population`, `ranking_metrics`, `paired_comparison` with
an `excludes_zero` flag per metric) so both files can be read by the same
code. A claimed gain counts only where `excludes_zero` is true, and the
design note quotes the interval rather than the point estimate.

## 8. Gotchas that were designed around, not discovered late

- **`metrics=["AUC"]` breaks early stopping after the first model.** Keras
  auto-names metrics per session, so the second and third model built in one
  kernel get `auc_1`/`auc_2`, and `EarlyStopping(monitor="val_auc")` then
  silently monitors nothing (it warns and continues). Every variant is
  compiled with `tf.keras.metrics.AUC(name="auc")` instead.
- **The clone lives in `/tmp`, not `/kaggle/working`.** Everything under
  `working` is packaged as the notebook's downloadable output, and the repo
  carries ~2GB of example notebooks and plots.
- **One variant resident at a time.** Each is built, fitted, scored, saved
  and released (`clear_session`) before the next, so three models plus a
  125,541 × 768 article matrix and an encoded catalogue are never resident
  together — A1 Q4 §9 and A2 Q1 §8 are a long record of what happens when
  separately-affordable transients are held at once.
- **BatchNormalization defeats the naive smoke test.** The one-batch
  learning check compares `train_on_batch`'s own training-mode losses, not
  `evaluate()`: the news encoder's BN moving statistics have barely moved
  after 20 steps, so an inference-mode comparison measures BN warm-up rather
  than learning.

## 9. Results

Run on Kaggle (GPU T4 x2), three variants per dataset, every variant scored on
the same 200,000 impressions per split. All three carry **1,304,720
parameters** on both datasets, asserted at runtime, so nothing below is a
capacity difference. Per-impression AUC:

| dataset | split | baseline | masked_uniform | recency |
|---|---|---|---|---|
| `ebnerd_large` | val | 0.5701 | 0.5773 | 0.5757 |
| `ebnerd_large` | test | 0.5835 | 0.5836 | **0.5845** |
| `mind_large` | val | 0.6316 | 0.6323 | **0.6396** |
| `mind_large` | test | 0.6307 | 0.6261 | **0.6349** |

### The improvement holds on MIND and does not hold on EB-NeRD's test split

Paired bootstrap 95% CI on `recency - baseline`, 1,000 iterations, identical
impressions on both sides:

| dataset | split | Δ AUC | Δ MRR | Δ nDCG@5 | Δ nDCG@10 |
|---|---|---|---|---|---|
| `mind_large` | val | **+0.0080** [+0.0071, +0.0090] | **+0.0109** | **+0.0090** | **+0.0083** |
| `mind_large` | test | **+0.0042** [+0.0033, +0.0051] | **+0.0087** | **+0.0084** | **+0.0070** |
| `ebnerd_large` | val | **+0.0056** [+0.0046, +0.0066] | **+0.0032** | **+0.0033** | **+0.0032** |
| `ebnerd_large` | test | +0.0011 [−0.0000, +0.0021] | **−0.0021** | −0.0001 | **−0.0013** |

Bold marks an interval that excludes zero. On `mind_large` all eight
intervals exclude zero and all are positive: the improvement is confirmed on
both splits, on every metric. On `ebnerd_large` the val split agrees, but the
**test split does not**: AUC and nDCG@5 are indistinguishable from zero, and
MRR and nDCG@10 are significantly *negative*. The honest statement is that
this improvement is confirmed on one of the two datasets, and the assignment's
"CI excludes zero" bar is met for MIND (both splits) and for EB-NeRD's val
split only.

### What the three-variant ablation attributes the gain to

This is why the middle variant exists. Isolating the recency signal from the
padding mask (`recency - masked_uniform`):

| dataset | split | Δ AUC | verdict |
|---|---|---|---|
| `mind_large` | val | **+0.0073** [+0.0064, +0.0083] | recency signal carries it |
| `mind_large` | test | **+0.0088** [+0.0078, +0.0097] | recency signal carries it |
| `ebnerd_large` | val | **−0.0016** [−0.0025, −0.0008] | recency *subtracts*; the mask carries it |
| `ebnerd_large` | test | +0.0010 [−0.0003, +0.0021] | indistinguishable |

And the mask alone (`masked_uniform - baseline`): `mind_large` +0.0007 (ns) on
val, **−0.0046** on test; `ebnerd_large` **+0.0072** on val, +0.0001 (ns) on
test. So the two datasets attribute the same headline change to opposite
causes:

- On **MIND**, masking the padded history slots does nothing or slightly hurts,
  and the ordinal recency prior is the entire effect.
- On **EB-NeRD**, the val-split gain is the padding mask (+0.0072), with the
  elapsed-time recency prior removing 0.0016 of it. A two-variant experiment
  would have reported "+0.0056, CI excludes zero, improvement confirmed" here
  and attributed it to recency, which the decomposition shows is wrong.

Point estimates decompose exactly (means are linear over the same
impressions), asserted by `test_payloads`: e.g. `ebnerd_large` val
+0.0072 + (−0.0016) = +0.0056.

### A methodological artifact that weakens the EB-NeRD result specifically

`split_by_last_day` reproduces `ebnerd_nrms_docvec.py`'s own rule (fit on
everything before the training sample's last calendar day, monitor on that
day). That rule interacts badly with A1's EB-NeRD cutoff. EB-NeRD's train
split ends at **07:00**, so its last calendar day holds only 7 hours of
impressions; MIND's ends at **midnight**, so its last day is a full one:

| dataset | early-stopping samples | share of training sample |
|---|---|---|
| `ebnerd_large` | 15,056 | **3.8%** |
| `mind_large` | 152,891 | 25.4% |

Epoch selection visibly mattered on EB-NeRD and not on MIND. EB-NeRD's
grouped val AUC *declines* after the first or second epoch
(`masked_uniform` 0.6722 → 0.6519 → 0.6409), so `restore_best_weights` picked
epoch 2 for the baseline and epoch 1 for both variants — three models stopped
at different points on the basis of a 15,056-sample signal. MIND's rises
monotonically and all three variants ran the full three epochs. The EB-NeRD
val/test disagreement above is therefore consistent with a noisy epoch
choice rather than with a property of the model, and that possibility cannot
be separated from the data with this run alone.

The fix, if this is revisited, is to carve the early-stopping set by a time
*quantile* of the training sample rather than by calendar day — the
`split_by_last_day` fallback already implements a chronological 90/10 cut and
currently only triggers when the calendar-day rule degenerates entirely. That
would make the two datasets' early-stopping sets comparable in size, at the
cost of departing from the authors' exact protocol.

### Cost

Per variant, on one GPU session: `ebnerd_large` ~374-382s to fit and ~155s to
score both splits; `mind_large` ~480-502s to fit and ~170s to score. Six fits
and twelve scoring passes fit comfortably inside one session, which is what
the user-vector-per-impression scoring path (#6) buys — the authors'
per-candidate path would have multiplied the scoring half by ~11.9 and ~37.

# A2 Q4 — Serving & Scale Analysis

## 1. What is measured, and on what

The **served two-stage pipeline** of A2 Q1/Q2: BM25 and frozen-embedding
retrieval scoring each impression's `article_ids_inview`, feeding the LightGBM
re-ranker. That is the path A2 Q2 evaluated and Q5 submits. Q3's NRMS is a
baseline for comparison, not the served system, and is not timed; serving it
locally would need its Keras weights plus a runtime this environment does not
have (`tensorflow-cpu` publishes no `cp314` wheels).

Q4 is a single-machine measurement by construction — index memory, p99
latency and a cost/QPS figure only compose into an argument if they describe
the same host — so `src/serving_benchmark.ipynb` captures the machine
specification into its output rather than assuming it:

| | |
|---|---|
| host | Windows-11-10.0.26200-SP0 |
| CPU | 13th Gen Intel Core i5-13500 — 20 logical cores |
| RAM | 15.7 GB |
| stack | Python 3.14.6, numpy 2.5.1, polars 1.43.2, lightgbm 4.7.0 |

This is the same machine whose `WinError 10055` and
`STATUS_FATAL_MEMORY_EXHAUSTION` incidents A1 Q4 §9 and A2 Q1 §8 document, so
§5's 10× argument continues a measured history rather than opening a
hypothetical one.

Wrapper: `serving_benchmark.py`; `SERVING_DATASETS` scopes a run to one
dataset per kernel. Output: `data/processed/{dataset}/serving_metrics.json`.
`benchmarks/verify_a2q4_claims.py` prints every figure quoted below from
those files and re-asserts the consistency they rely on.

## 2. Index memory: byte-accounted, not estimated

`sys.getsizeof` on a dict returns the hash table only — not keys, values, or
the numpy buffers the values point at, which for `BM25Index.postings` is
essentially all of it. `deep_nbytes` walks containers and adds `.nbytes` for
arrays, and de-duplicates shared buffers through a `_seen` set: a view is
redirected to its `.base`, and without de-duplication `embedding_lookup`'s
125,541 views into one block would be reported as
125,541 copies of the matrix. Both properties are
asserted on probe objects before any real structure is measured.

The feature table is measured on a 200,000-row slice and extrapolated.
Reading `reranker_features.parquet` whole to measure it would reproduce the
memory exhaustion this section characterises.

| dataset | BM25 index | embedding matrix (+ unit copy) | LightGBM | **resident serving set** | feature table on disk | feature table if resident |
|---|---|---|---|---|---|---|
| `ebnerd_large` | 83.8 MB (2,719,463 postings) | 367.8 MB × 2 | 374 KB (53 trees) | **0.80 GB** | 9.56 GB | 190,850,352 rows × 157 B = **27.90 GB** |
| `mind_large` | 85.2 MB (3,864,307 postings) | 305.1 MB × 2 | 320 KB (45 trees) | **0.68 GB** | 4.00 GB | 97,592,931 rows × 111 B = **10.11 GB** |

Two things the table settles. The **resident serving set is under a
gigabyte** on both datasets, and 90% / 88% of it is the
embedding matrix and its unit-normalized copy — the BM25 index and the booster
are rounding error beside it. And the **offline feature table does not fit in
this machine's RAM even at 1× on `ebnerd_large`**: 27.9 GB against
15.7 GB. That is not a projection; it is why A2 Q1 and Q2 had to be
built as streaming, chunked passes, and it is the measured form of the
incidents cited above.

## 3. Latency: every stage of one request, separately and end to end

`LATENCY_REPS = 1000` sampled requests from A2 Q2's scored test population,
after `WARMUP_REPS = 50` untimed requests absorb BLAS thread-pool spin-up and
page-in. The 99th percentile of 1,000 samples is the 10th-largest value — an
order statistic with real support, not a single outlier.

Excluded from every per-request figure: index construction, embedding
normalization and the feature-store load. They are startup costs, reported
in §2; charging them to a request would report a latency no served system
has.

Stage 1's fresh `bm25_score` and `embedding_score` overwrite the persisted
columns before the booster runs, because at serving time those two features
are computed, not read.

| stage (mean / p99, ms) | `ebnerd_large` | `mind_large` |
|---|---|---|
| `query_build` | 0.17 / 0.23 | 0.16 / 0.26 |
| `bm25_inview` | 3.64 / 5.24 | 5.44 / 9.48 |
| `embedding_inview` | 0.06 / 0.11 | 0.09 / 0.26 |
| `feature_assembly` | 0.16 / 0.23 | 0.17 / 0.27 |
| `reranker_predict` | 0.34 / 0.41 | 0.34 / 0.42 |
| **`served_end_to_end`** | **4.36 / 6.09** | **6.20 / 10.43** |
| `candgen_bm25_top200` | 4.72 / 9.06 | 6.81 / 14.56 |
| `candgen_embedding_top200` | 7.34 / 8.12 | 6.10 / 6.89 |
| `candgen_embedding_top200_batchfn` | 291.09 / 310.90 | 241.39 / 274.35 |
| candidates per request (mean / max) | 11.9 / 73 | 34.0 / 254 |

### The served path meets a 100 ms p99 with an order of magnitude to spare

p99 of **6.09 ms** on `ebnerd_large` and
**10.43 ms** on `mind_large`. The difference
between the two is almost entirely candidate count (11.9 vs
34.0 per request) acting on the BM25 stage.

### BM25 in-view scoring is the served path

`bm25_inview` is **83%** of the served mean on `ebnerd_large` and
**88%** on `mind_large`, for a stage whose output is ~12–34 numbers.
The reason is structural: `get_scores` is an inverted-index traversal that
allocates an `n_docs`-length array and accumulates every posting of every
query term — it scores the whole catalogue, and the in-view subset is then
read out of that. That is the right shape for corpus-wide top-K (§3's
`candgen_bm25_top200` costs barely more than `bm25_inview`, which is the
proof) and the wrong shape for re-scoring a dozen known documents, which a
**forward index** (document → term frequencies) would do in microseconds.
The index choice that made A1's candidate generation fast is the one thing
holding the served path above a millisecond. Everything else — query build,
embedding cosine over the subset, feature gathering, and 45–53 trees of
LightGBM — sums to well under a millisecond.

### Two candidate paths, because Q4's wording and the served system differ

Q4 asks for "candidate generation + re-ranking". The served path scores the
in-view set (A1 Q4 §1 records why: Codabench requires a permutation of it,
and recall@200 caps any corpus-wide pipeline at 0.2–3%). Corpus-wide top-200
retrieval is what "candidate generation" names, so it is measured too. The
embedding version is measured **twice**, and the gap between the two rows is
a finding about API shape rather than about the model:

- `candgen_embedding_top200` — serving-shaped. The unit corpus is precomputed
  once (it is the "+ unit copy" in §2) and a request is one matvec plus
  `argpartition`. 8.1 / 6.9 ms p99.
- `candgen_embedding_top200_batchfn` — `embeddings.batched_top_k` called per
  request. That function normalizes the whole corpus **inside every call**,
  because it amortizes the cost over 2,000 queries in A1 Q3's offline pass.
  Per request it re-normalizes `n_docs × 768` floats for one query:
  **40× / 40×** slower, at
  311 / 274 ms p99 — which would have
  shown the system **breaching the SLA at 1×** had the offline function been
  reused as the serving function. It is measured deliberately, so the design
  note can state the cost of that mistake rather than assert it.

## 4. Cost and QPS at the SLA

Throughput is derived from the **mean** service time and the SLA check from
the **p99**: a queue's service rate is set by the mean, while the tail is what
breaches. Using p99 for both would understate capacity by the width of the
tail.

Stated assumptions, recorded in the output beside the figures they produce:
one request occupies one process; processes scale linearly across vCPUs; and
a price of `$0.0425` per vCPU-hour. The first two are optimistic — numpy's
BLAS may already use several threads inside one request, so a "process" is
not cleanly one core, and real deployments lose headroom to queueing well
before full utilisation.

The price is a plug-in, and its provenance should be read as such: it is
approximately the AWS `c5.large` on-demand rate in `us-east-1` (~$0.085/h for
2 vCPUs), taken from general knowledge rather than a quoted price sheet, and
not re-verified for this write-up — cloud list prices change and vary by
region, and a reserved or spot rate would be several times lower. It was
chosen because it is a round, recognisable compute-optimised figure, not
because it is authoritative. What makes the conclusion robust is that cost
scales *linearly* with this one number while the measured CPU-seconds do not
move: at any list price between `$0.02` and `$0.10` per vCPU-hour, a thousand
queries still cost between two and twenty thousandths of a cent. The
measured quantity is `cpu_seconds_per_1000_queries`, which is what the JSON
carries; the dollar figure is that number times whichever price the reader
prefers. This is a back-of-envelope, which is what the assignment asks for.

| dataset | served mean (ms) | served p99 (ms) | p99 < 100 ms | QPS / process | processes for 1,000 QPS | USD / 1,000 queries |
|---|---|---|---|---|---|---|
| `ebnerd_large` | 4.36 | 6.09 | meets (16.42×) | 230 | 5 | $0.000051 |
| `mind_large` | 6.20 | 10.43 | meets (9.59×) | 161 | 7 | $0.000073 |

At these service times the re-ranking stage is not where money goes. A
thousand queries cost a fraction of a cent of CPU, and a single mid-range
desktop sustains the order of a thousand QPS. Cost at this scale is dominated
by keeping the serving set and — far more — the feature pipeline resident,
which is §5's subject.

## 5. What breaks first at 10×

Arithmetic on §2's measured footprints, with each component labelled by how
it actually scales — because that is what decides the answer:

- the embedding matrix and its normalized copy scale **linearly with the
  catalogue**, and both must be resident for brute-force cosine;
- BM25 postings scale with catalogue × mean document length — also linear;
- the feature table scales with **impressions × candidates**, the term that
  grows fastest under "10× the load": 10× traffic is 10× the table even over
  an unchanged catalogue;
- the re-ranker scales with **neither** — a fixed 53–45 trees — which is why
  it never appears in the answer.

Latency projections multiply §3's serving-shaped candidate-generation p99s:
brute-force cosine is O(n_docs × dim) per query, and the inverted-index
traversal is O(postings touched), both linear in the catalogue.

| dataset | scale | serving set (GB) | feature table (GB) | both fit in 15.7 GB | BM25 top-200 p99 (ms) | embedding top-200 p99 (ms) |
|---|---|---|---|---|---|---|
| `ebnerd_large` | 1× | 0.8 | 27.9 | **no** | 9.1 | 8.1 |
| `ebnerd_large` | 2× | 1.6 | 55.8 | **no** | 18.1 | 16.2 |
| `ebnerd_large` | 5× | 4.0 | 139.51 | **no** | 45.3 | 40.6 |
| `ebnerd_large` | 10× | 8.0 | 279.02 | **no** | 90.6 | 81.2 |
| `mind_large` | 1× | 0.68 | 10.11 | yes | 14.6 | 6.9 |
| `mind_large` | 2× | 1.36 | 20.21 | **no** | 29.1 | 13.8 |
| `mind_large` | 5× | 3.4 | 50.54 | **no** | 72.8 | 34.5 |
| `mind_large` | 10× | 6.79 | 101.07 | **no** | 145.6 | 68.9 |

### The order in which things break

**First, and already: the offline feature table.** It exceeds this machine
at 1× on `ebnerd_large` (27.9 GB) and at 2× on `mind_large`
(20.21 GB). This is the measured form of every memory incident
in this project's history. The mitigation is also already built — every pass
over it streams in `CHUNK_SIZE` slices with atomic checkpoints — but the 10×
figures (279 / 101 GB) say that streaming from local
disk stops being a strategy and becomes a distributed feature store or a
recomputation-on-demand design. The distinction matters for serving: the
table measured here is the **offline** training/evaluation artifact. A live
system does not look these features up for a new impression; it derives them
from the user's history and the article metadata, both of which are in the
resident serving set. The `feature_assembly` stage timed in §3 is therefore a
**lower bound** on serving-time feature cost — it measures gathering
precomputed rows, not computing the eleven behavioural features from history
— and that gap is the largest thing this benchmark does not measure.

**Second, at roughly 10×: brute-force embedding retrieval.** The serving set
grows to 8.0 / 6.8 GB — half this machine — and the
embedding top-200 p99 reaches 81 / 69 ms,
still inside the 100 ms SLA on its own but with none left for the rest of the
request. This is the point at which an approximate index (HNSW or IVF-PQ)
stops being an optimisation and becomes a requirement, trading the exactness
that A1's `batched_top_k` verified against a full sort for a sub-linear query.

**Third, and it breaches: BM25 corpus-wide top-K.** At 10× the projected p99
is 91 ms on `ebnerd_large` and **146 ms on `mind_large`** — the
latter over the SLA before re-ranking has run. MIND's longer documents give
it 37 postings per document against EB-NeRD's
22, so its traversal is longer per query at every scale. The
standard remedies — impact-ordered postings with early termination
(WAND/BMW), or a sharded index — are the same ones that would also fix §3's
in-view finding, since both stem from scoring the whole catalogue to read out
a few hundred documents.

**What does not break: the re-ranker.** 374 KB,
0.41 ms p99, and neither figure moves with catalogue or
traffic. The stage that A2 added is the cheapest one in the system.
