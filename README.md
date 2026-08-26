# CS4.406 Assignment 1 — EB-NeRD & MIND News Recommendation

This repo builds a lexical + semantic retrieval pipeline over five news-recommendation
dataset tracks: **EB-NeRD (demo)**, **EB-NeRD (small)**, **EB-NeRD (large)**,
**MIND (small)**, and **MIND (large)** — plus the two real Codabench-scored test
populations (`MINDlarge_test`, `ebnerd_testset`), handled by their own dedicated
submission notebooks (see Q5 below). This document describes exactly how the raw
data is laid out on disk, file by file, column by column, as downloaded from the
sources in `assignments/Assignment1_v1.pdf`. EB-NeRD small/large share EB-NeRD
demo's exact file layout and column schema — only the row counts differ (a larger
article catalog and user base) — so they aren't documented as separate
column-by-column sections below; likewise MIND large shares MIND small's TSV layout.

## Directory layout

```
ebnerd_demo/
├── articles.parquet                 # all articles (shared across train/validation)
├── train/
│   ├── behaviors.parquet            # impression logs
│   └── history.parquet              # per-user click history
└── validation/
    ├── behaviors.parquet
    └── history.parquet

ebnerd_small/
└── (same layout as ebnerd_demo/ -- larger row counts, see table below)

MINDsmall_train/MINDsmall_train/
├── news.tsv                         # all articles referenced in this split
├── behaviors.tsv                    # impression logs (history + candidates + labels)
├── entity_embedding.vec             # TransE embeddings for knowledge-graph entities
└── relation_embedding.vec           # TransE embeddings for knowledge-graph relations

MINDsmall_dev/MINDsmall_dev/
└── (same four files as train)
```

Row counts (verified against the downloaded files):

| Dataset | File | Rows |
|---|---|---|
| EB-NeRD demo | `articles.parquet` | 11,777 |
| EB-NeRD demo | `train/behaviors.parquet` | 24,724 impressions (1,590 users, 12,944 sessions) |
| EB-NeRD demo | `train/history.parquet` | 1,590 (one row per user) |
| EB-NeRD demo | `validation/behaviors.parquet` | 25,356 impressions (1,562 users) |
| EB-NeRD demo | `validation/history.parquet` | 1,562 |
| EB-NeRD small | `articles.parquet` | 20,738 |
| EB-NeRD small | `train/behaviors.parquet` + `validation/behaviors.parquet` | 477,534 impressions (18,827 users) |
| EB-NeRD small | `train/history.parquet` + `validation/history.parquet` | 18,827 (one row per user, deduplicated) |
| MIND-small train | `news.tsv` | 51,282 |
| MIND-small train | `behaviors.tsv` | 156,965 (50,000 users) |
| MIND-small train | `entity_embedding.vec` | 26,904 |
| MIND-small train | `relation_embedding.vec` | 1,091 |
| MIND-small dev | `news.tsv` | 42,416 |
| MIND-small dev | `behaviors.tsv` | 73,152 (50,000 users) |
| MIND-small dev | `entity_embedding.vec` | 22,893 |

Note: the extracted `ebnerd_demo/__MACOSX/` and `ebnerd_small/__MACOSX/` folders are
macOS zip metadata (`._*` AppleDouble files), not data — safe to delete/ignore.

---

## EB-NeRD demo (Danish, Parquet)

Parquet files are columnar and typed — list-valued columns (e.g. `article_ids_inview`)
are native numpy arrays once loaded, no string parsing required.

### `articles.parquet` — one row per article (11,777 rows, 21 columns)

| Column | Type | Nulls | Description |
|---|---|---|---|
| `article_id` | int32 | 0% | Unique article identifier. |
| `title` | str | 0% | Headline. |
| `subtitle` | str | 0% | Sub-headline / dek — the closest analogue to MIND's `abstract`. |
| `body` | str | 0% | Full article text. **EB-NeRD includes this; MIND does not** (see below). |
| `published_time` | datetime | 0% | Original publish timestamp. |
| `last_modified_time` | datetime | 0% | Last edit timestamp. |
| `premium` | bool | 0% | Whether the article is behind Ekstra Bladet's paywall. |
| `article_type` | str | 0% | Editorial format, one of 12 values: `article_default`, `article_feature`, `article_opinionen`, `article_native`, `article_scribblelive`, `article_fullscreen_gallery`, `article_page_nine_girl`, `article_questions_and_answers`, `article_editorial_production`, `article_standard_feature`, `article_video_standalone`, `article_webtv`. |
| `url` | str | 0% | Canonical article URL. |
| `image_ids` | list[int] | 8% | IDs of images embedded in the article. |
| `ner_clusters` | list[str] | 0%* | Named-entity surface forms extracted from the text (empty array, not null, when none found). |
| `entity_groups` | list[str] | 0%* | Entity type tags parallel to `ner_clusters` (e.g. `PER`, `ORG`, `LOC`). |
| `topics` | list[str] | 0%* | Editorial topic tags (e.g. `Kriminalitet`, `Sport`, `Kendt`). |
| `category` | int16 | 0% | Numeric category ID (24 distinct values in the demo). |
| `subcategory` | list[int16] | 0%* | Numeric subcategory ID(s), can be more than one. |
| `category_str` | str | 0% | Human-readable category, one of: `nyheder`, `sport`, `underholdning`, `krimi`, `forbrug`, `penge`, `biler`, `ferie`, `sex_og_samliv`, `horoskoper`, `dagsorden`, `nationen`, `opinionen`, `plus`, `play`, `podcast`, `side9`, `vin`, `musik`, `auto`, `bibliotek`, `haandvaerkeren`, `incoming`, `om_ekstra_bladet`, `services`. |
| `total_inviews` | float64 | 36% | Aggregate # of times the article was shown to any user (site-wide, not per-impression). |
| `total_pageviews` | float64 | 36% | Aggregate # of pageviews. |
| `total_read_time` | float32 | 36% | Aggregate read time across all readers. |
| `sentiment_score` | float32 | 0% | Sentiment confidence score in [0, 1]. |
| `sentiment_label` | str | 0% | One of `Positive`, `Neutral`, `Negative`. |

\* these are empty-array-when-absent, not true nulls.

### `train/behaviors.parquet` and `validation/behaviors.parquet` — one row per impression

| Column | Type | Nulls | Description |
|---|---|---|---|
| `impression_id` | uint32 | 0% | Unique impression identifier. |
| `user_id` | uint32 | 0% | User who received this impression. |
| `session_id` | uint32 | 0% | Groups impressions belonging to the same browsing session. |
| `impression_time` | datetime | 0% | When the impression (front page / article list) was served. |
| `device_type` | int8 | 0% | Device code (3 distinct values: 1, 2, 3 — desktop/mobile/tablet per EB-NeRD's data description). |
| `article_ids_inview` | list[int32] | 0% | **Candidate set** — all articles shown in this impression. This is the retrieval target set. |
| `article_ids_clicked` | list[int32] | 0% | Subset of `article_ids_inview` the user actually clicked — the ground-truth label. |
| `article_id` | float64 | 70% | The single article the impression is anchored to (e.g. the article being read when related-articles were shown). Null for front-page-style impressions. |
| `read_time` | float32 | 0% | Seconds spent on `article_id` (or on the page) during this impression. |
| `scroll_percentage` | float32 | 71% | % scrolled on `article_id`. |
| `next_read_time` | float32 | 3% | Read time on the *next* article the user opened — a look-ahead field, must be excluded from features at serving time (see Assignment Q9 anti-gaming). |
| `next_scroll_percentage` | float32 | 11% | Same look-ahead concern as above. |
| `is_sso_user` | bool | 0% | Logged in via single-sign-on. |
| `is_subscriber` | bool | 0% | Paying subscriber. |
| `gender` | float64 | 93% | Self-reported gender code — mostly withheld for privacy. |
| `age` | float64 | 98% | Self-reported age — mostly withheld. |
| `postcode` | float64 | 99% | Self-reported postcode — mostly withheld. |

**Anti-gaming note**: `next_read_time` and `next_scroll_percentage` describe events *after*
the impression and must never be used as model input — only as later-stage labels/analysis.

### `train/history.parquet` and `validation/history.parquet` — one row per user

Each row holds a user's entire pre-collection-window click history as four
equal-length parallel arrays (verified: e.g. one user has 582 historical clicks).

| Column | Type | Description |
|---|---|---|
| `user_id` | uint32 | User identifier — joins to `behaviors.parquet.user_id`. |
| `article_id_fixed` | list[int32] | Sequence of clicked article IDs, chronological. |
| `impression_time_fixed` | list[datetime] | Timestamp of each historical click. |
| `read_time_fixed` | list[float32] | Read time for each historical click. |
| `scroll_percentage_fixed` | list[float32] | Scroll % for each historical click. |

---

## MIND-small (English, TSV)

Plain tab-separated files, **no header row** — columns must be named manually. Several
fields are strings that encode structured data (JSON, space-separated lists,
`id-label` pairs) and need explicit parsing.

### `news.tsv` — one row per article (8 columns)

| Position | Column (assigned name) | Type | Nulls | Description |
|---|---|---|---|---|
| 1 | `news_id` | str | 0% | Unique article identifier, e.g. `N55528`. |
| 2 | `category` | str | 0% | One of 17 values: `news`, `sports`, `finance`, `foodanddrink`, `travel`, `video`, `health`, `lifestyle`, `weather`, `entertainment`, `autos`, `tv`, `music`, `movies`, `kids`, `middleeast`, `northamerica`. |
| 3 | `subcategory` | str | 0% | Finer-grained topic, 264 distinct values (e.g. `lifestyleroyals`, `newsworld`). |
| 4 | `title` | str | 0% | Headline. |
| 5 | `abstract` | str | 5% | MSN editorial dek/summary — the closest analogue to EB-NeRD's `subtitle`. **There is no full-body column** — see note below. |
| 6 | `url` | str | 0% | Original MSN article URL (many are now dead; dataset is from 2019). |
| 7 | `title_entities` | JSON str | ~0% | JSON array of entities found in the title: `{Label, Type, WikidataId, Confidence, OccurrenceOffsets, SurfaceForms}`. `Type` is a single-letter code (`P`=person, `C`=concept, `G`=geo, `O`=org, ...). Empty list `[]` when none found. |
| 8 | `abstract_entities` | JSON str | ~0% | Same schema as `title_entities`, extracted from the abstract instead. |

**Why there's no `body` column**: MSN aggregates articles from many publishers and
doesn't own the underlying content, so Microsoft could not legally redistribute full
article text — only their own title/abstract dek. The `url` column is the only path
back to full text, and it's lossy since most links are dead by now. Treat `body` as a
genuinely-null field for MIND in any unified schema, not a parsing gap.

### `behaviors.tsv` — one row per impression (5 columns)

| Position | Column (assigned name) | Type | Nulls | Description |
|---|---|---|---|---|
| 1 | `impression_id` | int | 0% | Unique impression identifier. |
| 2 | `user_id` | str | 0% | User identifier, e.g. `U13740`. |
| 3 | `time` | str `MM/DD/YYYY H:MM:SS AM/PM` | 0% | Impression timestamp. |
| 4 | `history` | space-separated `news_id` list | 2% | User's clicked articles **before** this impression, chronological, oldest→newest. Null (no prior history) for cold-start users. |
| 5 | `impressions` | space-separated `news_id-label` tokens | 0% | The candidate set **and** the click label in one field, e.g. `N55689-1 N35729-0` → `N55689` was clicked (`1`), `N35729` was shown but not clicked (`0`). Split on space, then on `-`, to recover `article_ids_inview` (all tokens) and `article_ids_clicked` (tokens with label `1`) equivalent to EB-NeRD's two array columns. |

Unlike EB-NeRD, there is **no separate history table** (history lives inline in each
behaviors row as a single string with no per-click timestamp — only relative order is
known), **no session id**, and **no user demographics** at all.

### `entity_embedding.vec` / `relation_embedding.vec` — knowledge-graph embeddings

Tab-separated, no header, 101 columns each: a WikidataID followed by 100 float
dimensions (TransE-style KG embeddings, trained on the Wikidata subgraph touched by
entities in `news.tsv`'s `title_entities`/`abstract_entities`).

| Column | Type | Description |
|---|---|---|
| col 1 | str | `entity_embedding.vec`: Wikidata entity ID, e.g. `Q41`. `relation_embedding.vec`: Wikidata property ID, e.g. `P31`. |
| cols 2–101 | float | 100-dim embedding vector. |

---

## Key structural differences to account for in any unified pipeline

| | EB-NeRD demo | MIND-small |
|---|---|---|
| File format | Parquet (typed, native arrays) | TSV (flat strings, manual parsing) |
| Body text | present | **absent** (licensing) |
| Click history | separate `history.parquet`, per-user, with timestamps + read/scroll signal | inline string in `behaviors.tsv`, order-only, no timestamps |
| Candidates + labels | two array columns (`article_ids_inview`, `article_ids_clicked`) | one string field (`impressions`), needs split on space then `-` |
| Entities | surface-form strings (`ner_clusters`/`entity_groups`) | structured JSON with WikidataId + matching pretrained KG embeddings |
| Engagement / sentiment | present (`read_time`, `scroll_percentage`, `sentiment_score`) | absent |
| Session id | present | absent |
| User demographics | present, but 93–99% null | not collected |
| Language | Danish | English |

A unified schema (see assignment Q1) should normalize both into three tables —
`articles`, `behaviors`/impressions, and `history` — with dataset-namespaced IDs
(e.g. prefix `ebnerd_`/`mind_`) so joins across datasets can never silently collide,
and with fields that only exist in one dataset (`body`, `sentiment_score`, `session_id`,
per-click timestamps) kept nullable rather than dropped.

---

## Setup

```bash
uv sync                 # installs runtime + notebook deps (pandas, pyarrow, ipykernel, jupyter, nbformat)
```

**`uv run pytest` reports "collected 0 items" — this is expected, not broken.**
Per this project's convention, every feature cell in a notebook is followed by a
test cell (`def test_...(): assert ...` immediately called, printing `ok: ...` on
success — see any `src/*.ipynb`) rather than a standalone `test_*.py` file `pytest`
can discover. There are 59 such test cells across the nine notebooks in `src/`, and
they run as an integral part of executing each notebook top-to-bottom (via
`nbconvert` or Jupyter directly) — every command in the "Rebuild"/"Run"/"Generate"
sections below aborts loudly if any of its notebook's test cells fail, so a clean
run of those commands *is* the test suite passing. `pytest` itself only exists as a
declared dependency for tooling/IDE integration, not as this project's test runner.

Exploratory notebook: [`src/explore_datasets.ipynb`](src/explore_datasets.ipynb) loads
both datasets and displays the raw tables described above.

## Rebuild the feature store (Q1)

```bash
uv run python build_pipeline.py
```

Executes [`src/build_pipeline.ipynb`](src/build_pipeline.ipynb) end-to-end: cleans and
parses raw dataset tracks into the unified `articles`/`behaviors`/`history`
schema described in `SPEC.md`, assigns a time-based `train`/`val`/`test` split, runs the
Q9 no-future-click-leakage checks, and writes the result to
`data/processed/{ebnerd,ebnerd_small,mind,ebnerd_large,mind_large}/` (gitignored).
Every step's assertions must pass or the rebuild aborts — see `SPEC.md` for the full design.

The notebook's `BUILD_LARGE_ONLY` flag (top setup cell) controls scope: `True`
(re)builds/writes only `ebnerd_large`/`mind_large` and leaves
`ebnerd`/`ebnerd_small`/`mind` completely untouched (not read, not written);
`False` rebuilds all five tracks. See `SPEC.md` Q1 #5 for why (memory
management at `ebnerd_large`'s ~24.6M-row scale) and the same flag's use in
Q2-Q5 below.

## Run BM25 lexical retrieval (Q2)

```bash
uv run python bm25_retrieval.py
```

Requires the Q1 feature store to already exist. Executes
[`src/bm25_retrieval.ipynb`](src/bm25_retrieval.ipynb) end-to-end: builds a
from-scratch BM25 index per dataset (postings-list inverted index, in
[`src/cs4406m26_assignment1c1/bm25.py`](src/cs4406m26_assignment1c1/bm25.py) —
no third-party BM25 library, see `SPEC.md` for why), retrieves top-K
candidates per user from their pre-window click history, and writes
`bm25_topk.parquet` + `bm25_metrics.json` (recall@{50,100,200} on val/test) to
`data/processed/{dataset}/`. Same `BUILD_LARGE_ONLY` flag/scope as Q1 (see
above) — this and every notebook below (Q3-Q5) carry the identical flag.

Verify the from-scratch-vs-`rank_bm25` performance claim in `SPEC.md` Q2 #1
(the reason `bm25.py` is hand-built rather than a library call):

```bash
uv run python benchmarks/benchmark_bm25.py
```

Times `top_k` per query (built from a sample of val/test users' real click
history) against each dataset's real corpus and extrapolates to the full
val/test population. Only benchmarks the shipped `bm25.py` path — the
rejected `rank_bm25` comparison point (~2.9s/query) required a dependency
that was removed (`uv remove rank-bm25`) once the from-scratch module proved
faster; re-run that specific comparison only after `uv add rank-bm25`.

## Compute article embeddings (Q3, prerequisite — run on Kaggle)

Article embeddings are computed on a GPU on Kaggle, not locally — see
`SPEC.md` Q3 #1 for why. Steps:

1. Rename local copies of `data/processed/{dataset}/articles.parquet` to
   `{dataset}_articles.parquet` for whichever of
   `ebnerd`/`ebnerd_small`/`ebnerd_large`/`mind`/`mind_large` you need
   embeddings for (the notebook auto-discovers whichever subset is
   attached), then upload them together as one private Kaggle Dataset
   (Kaggle → New Notebook → **+ Add Data → Upload → New Dataset**).
2. Import [`src/compute_embeddings_kaggle.ipynb`](src/compute_embeddings_kaggle.ipynb)
   into a Kaggle Notebook (File → Import Notebook).
3. In the notebook's Settings (right sidebar): **Accelerator → GPU T4 x2**
   (or P100), **Internet → On**.
4. **Save Version → Save & Run All (Commit)**. Once finished, open that
   version's **Output** tab and download `{dataset}_article_embeddings.parquet`
   for each dataset you attached.
5. Move each into the local repo as
   `data/processed/{dataset}/article_embeddings.parquet`.

The local repo never installs `torch`/`sentence-transformers` — once these
files exist, everything downstream runs locally with the existing
numpy/pandas/pyarrow dependencies only.

## Run semantic (embedding) retrieval (Q3)

```bash
uv run python embedding_retrieval.py
```

Requires the Q1 feature store, Q2's `bm25_metrics.json` (for the comparison
table), and the Kaggle-computed `article_embeddings.parquet` per dataset
(see above) to already exist. Executes
[`src/embedding_retrieval.ipynb`](src/embedding_retrieval.ipynb) end-to-end:
mean-pools each user's recent click history into a query vector, retrieves
top-K candidates via batched brute-force cosine similarity (in
[`src/cs4406m26_assignment1c1/embeddings.py`](src/cs4406m26_assignment1c1/embeddings.py) —
no FAISS/ANN library, see `SPEC.md` for why brute-force is fast enough at
this scale), and writes `embedding_topk.parquet` + `embedding_metrics.json`
(recall@{50,100,200} on val/test, plus a lexical-vs-semantic comparison
against Q2's BM25 results) to `data/processed/{dataset}/`. Same
`BUILD_LARGE_ONLY` flag/scope as Q1.

Verify the brute-force-vs-FAISS performance claim in `SPEC.md` Q3 #2 (why no
ANN library is used):

```bash
uv run python benchmarks/benchmark_embeddings.py
```

Times the matmul and top-K-selection stages of `batched_top_k` separately,
over the real, full val/test population of each dataset (no sampling).

## Run the offline evaluation harness (Q4)

```bash
uv run python evaluation_harness.py
```

Requires the Q1 feature store, Q2's `bm25_topk.parquet`/`bm25_metrics.json`,
and Q3's `article_embeddings.parquet`/`embedding_topk.parquet` to already
exist. Executes [`src/evaluation_harness.ipynb`](src/evaluation_harness.ipynb)
end-to-end: re-ranks each impression's own `article_ids_inview` with a
`score_inview` adapter per method (in
[`src/cs4406m26_assignment1c1/evaluation.py`](src/cs4406m26_assignment1c1/evaluation.py)
— see `SPEC.md` Q4 #1 for why this is a different framing from Q2/Q3's
full-catalog recall@K), computes AUC/MRR/nDCG@{5,10}, intra-list diversity,
novelty, and coverage, slices by cold-start-vs-warm and head-vs-tail, and
bootstraps a 95% CI per `(dataset, method, split, slice, metric)`. Writes
`eval_metrics.json` to `data/processed/{dataset}/`. Same `BUILD_LARGE_ONLY`
flag/scope as Q1.

**At `ebnerd_large`/`mind_large` scale**, set the `EVAL_DATASETS` env var to
run one dataset per invocation (`nbconvert` launches a fresh kernel each
time, so this is the only way to avoid holding both large datasets' feature
stores/BM25 indexes/embedding matrices in one process at once — see
`SPEC.md` Q4 #9):

```bash
EVAL_DATASETS=ebnerd_large uv run python evaluation_harness.py
EVAL_DATASETS=mind_large uv run python evaluation_harness.py
```

(PowerShell: `$env:EVAL_DATASETS = "ebnerd_large"; uv run python evaluation_harness.py`)

Every `(dataset, split, method)` scoring pass is checkpointed to
`data/processed/_eval_checkpoints/{dataset}/` as it runs, so if a run is
interrupted (this machine hits an intermittent `WinError 10055` kernel
death at this scale, see `SPEC.md` Q4 #9), just re-run the same command —
it resumes from the last completed chunk instead of restarting. If the
notebook's final cells (bootstrap CI, `eval_metrics.json` write) keep
crashing even with every `(split, method)` checkpoint already written, skip
the notebook entirely for that last stretch:

```bash
uv run python _finish_eval_metrics_standalone.py ebnerd_large
```

Loads the four checkpoint files directly and reproduces the notebook's
remaining logic with no Jupyter/`nbconvert` involved — see the script's own
docstring and `SPEC.md` Q4 #9. It deliberately leaves the checkpoint
directory in place after writing `eval_metrics.json`; delete
`data/processed/_eval_checkpoints/{dataset}/` manually once you've checked
the output looks right.

Verify the bootstrap-CI timing claim in `SPEC.md` Q4 #5 (computationally
trivial even at MIND's ~70K-impression test-split scale):

```bash
uv run python benchmarks/benchmark_bootstrap_ci.py
```

Times `bootstrap_ci` (1,000 iterations) at each split's real impression
count.

## Generate a Codabench submission (Q5)

```bash
uv run python generate_predictions.py
```

Requires the Q1 feature store and Q3's `article_embeddings.parquet` for
every dataset in scope. Executes
[`src/generate_predictions.ipynb`](src/generate_predictions.ipynb)
end-to-end: re-ranks each dataset's `test` split with the same
`score_inview` adapters as Q4, and writes
`submissions/{dataset}/{dataset}_{embedding,bm25}_test_predictions.zip`,
each containing a single `prediction.txt` (MIND/`mind_large`) or
`predictions.txt` (EB-NeRD/`ebnerd_small`/`ebnerd_large`) — one line per
impression, `{impression_id} [{rank_1},...,{rank_n}]`, row order matching
the original file. Same `BUILD_LARGE_ONLY` flag/scope as Q1.

> **`ebnerd_small`/`ebnerd_large`/`mind_large`'s zips are not Codabench
> submissions at all** — generated for local completeness only. Each real
> competition scores a separate, real blind test population instead (see
> below): MIND scores `MINDlarge_test`, not `mind_large` (built from
> `MINDlarge_train`/`MINDlarge_dev`); EB-NeRD/RecSys 2024 scores
> `ebnerd_testset.zip`, not `ebnerd_small`/`ebnerd_large` (see `SPEC.md` Q5
> #3/#4/#6). Do not upload any of these three to Codabench.

### Generate the real MIND submission (`MINDlarge_test`)

Requires `MINDlarge_test.zip` downloaded separately and extracted to
`./MINDlarge_test/` (gitignored, not part of `data/raw`).

```bash
uv run python _run_nbconvert_selector_loop.py src/mind_large_test_submission.ipynb 10800
```

Executes [`src/mind_large_test_submission.ipynb`](src/mind_large_test_submission.ipynb)
end-to-end (runs in two sittings — pauses for a manual Kaggle embeddings
round for the 26,228 articles absent from `mind_large`'s existing catalog,
see the notebook's own **PAUSE HERE** cell) and writes
`submissions/mind_large_test/mind_large_test_{embedding,bm25}_predictions.zip`.
The notebook's own test cells verify every numeric claim in `SPEC.md` §7
as they run (schema parity, catalog-overlap counts, embedding-reuse
byte-identity, round-trip prediction counts) — a clean top-to-bottom run
*is* the verification.

### Generate the real EB-NeRD submission (`ebnerd_testset`)

Requires `ebnerd_testset.zip` downloaded separately and extracted to
`./ebnerd_testset/` (gitignored, not part of `data/raw`).

```bash
uv run python _run_nbconvert_selector_loop.py src/ebnerd_testset_submission.ipynb 10800
```

Executes [`src/ebnerd_testset_submission.ipynb`](src/ebnerd_testset_submission.ipynb)
end-to-end (no Kaggle step needed — reuses `ebnerd_large`'s article catalog
and embeddings directly, see `SPEC.md` §8) and writes
`submissions/ebnerd_testset/ebnerd_testset_{embedding,bm25}_predictions.zip`.
As above, the notebook's own test cells verify every numeric claim in
`SPEC.md` §8 (catalog identity, the `is_beyond_accuracy`
13,536,710-total/13,336,710-scored/200,000-excluded split, round-trip
prediction counts) as part of running it.

To submit either: register at
[codabench.org/competitions/13967](https://www.codabench.org/competitions/13967/)
(MIND) or
[codabench.org/competitions/2469](https://www.codabench.org/competitions/2469/)
(EB-NeRD/RecSys 2024), go to **Participate → Submit / View Results**, and
upload the `embedding` zip (embeddings scored better than BM25 in Q4's
comparison on every dataset track). MIND is limited to one submission per
day. Screenshot the resulting leaderboard score for the Q6 design note.

## Build the design note (Q6)

```bash
pdflatex -interaction=nonstopmode design_note.tex
pdflatex -interaction=nonstopmode design_note.tex
```

Run twice: the first pass writes `Section~\ref{...}` cross-references to
`design_note.aux`, the second reads them back so they resolve correctly.
Produces `design_note.pdf` (4 pages). Use plain `pdflatex`, not `latexmk` —
`latexmk` is a Perl script, and this machine's MiKTeX install has no `perl`
on `PATH` (`latexmk` fails with "MiKTeX could not find the script engine
'perl'"). If `latexmk`/Perl is available on your machine, `latexmk -pdf
design_note.tex` works too and additionally cleans up build artifacts.
Otherwise, delete `design_note.aux`/`.log`/`.out` manually afterward — only
`design_note.pdf` is a tracked deliverable.

## Dataset location

Raw datasets are gitignored and must be placed at the repo root before running anything,
matching the directory layout documented above: `ebnerd_demo/`, `ebnerd_small/`,
`ebnerd_large/`, `MINDsmall_train/`, `MINDsmall_dev/`, `MINDlarge_train/`, `MINDlarge_dev/`,
plus (for the real Codabench submissions) `MINDlarge_test/` and `ebnerd_testset/`.