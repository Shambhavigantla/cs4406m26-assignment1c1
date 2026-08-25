# PROMPTS.md

Log of prompts that materially shaped the project's design or implementation, per
`CLAUDE.md`. Each entry: the prompt (paraphrased where long), why it mattered, and
what was done in response.

---

### "read the @assignments/ folder and look at the assignment there. Understand the tasks we have to do before the 27th Aug deadline."

Kicked off the project. Claude read `assignments/Assignment1_v1.pdf` in full and
produced a roadmap covering all of Q1–Q9 (data pipeline, BM25, embeddings, eval
harness, Codabench submissions, design note, git/anti-gaming policy), then asked
one clarifying question about build order (both datasets together vs. one dataset
fully first) before locking in a plan.

### "doesnt the assignment require us to build a common pipeline for both datasets in Q1 and then combine them both and then do Q2-Q6? I am not quite sure, just verify once"

Important correction-seeking prompt. Re-reading Q1's exact wording ("unified
schema") together, we confirmed the assignment wants **one shared schema/codebase**
that's run separately per dataset — not a merged corpus — since MIND and EB-NeRD
have disjoint languages/users/IDs and Q5 requires two separate Codabench
submissions. This reshaped the whole Q1 design: dataset-namespaced IDs, per-dataset
output directories, generic pipeline code parameterized by dataset.

### "ok lets focus on Q1 for now, create a plan and write the details to SPEC.md for Q1 only"

Scoped the work down to Q1 only and asked for a written spec (`SPEC.md`) instead of
just an in-chat plan. Claude designed the unified schema (three tables:
`articles`/`behaviors`/`history`), computed the actual temporal-split cutoffs by
reading real timestamps off both datasets' raw files, and defined the feature-store
layout and one-command-rebuild mechanism, all written to `SPEC.md`.

### "Should we leave the body column for now and proceed with the assignment or do we have to scrape the data manually as well...?" (re: MIND's missing article body text)

Confirmed MIND's `body` field should stay permanently null (not scraped) — Q2/Q3
only require title+abstract, MSN's article URLs are dead, and scraping would break
Q1's reproducibility requirement. `SPEC.md`'s `articles` schema already modeled
`body` as nullable for exactly this reason.

### "Start implementing SPEC.md then"

Implemented `SPEC.md` end-to-end: built `src/build_pipeline.ipynb` (unify → split →
leakage tests → write feature store, following the project's markdown/feature/test
cell convention) and `build_pipeline.py` as the one-command rebuild entrypoint.
While validating the design against real data, found and fixed two issues the spec
hadn't anticipated: (1) the originally-planned MIND leakage check (history vs.
inview disjointness) doesn't hold on real data — ~11% of users legitimately have
overlap — so it was replaced with the invariant that does hold (one consistent
`history` string per user); (2) MIND's `train`/`dev` files both restart
`impression_id` at 1, so concatenating them without a source tag silently created
duplicate IDs — fixed by namespacing on `source_split` too. Ran the full pipeline
to completion against real data; all cell-level tests pass and
`data/processed/{ebnerd,mind}/` was produced correctly.

### "wait for a lot of these tables, I can see that the values are either NA or None, why are they different? also if the values are NA or None, why add them in the final schema at all?"

Good catch on an actual inconsistency: MIND's `body`/`session_id` were built with
pandas' `"string"` extension dtype (missing → `<NA>`), while MIND's history
sequence columns were plain `object` (missing → `None`) — two different missing
markers for the same underlying reason (dataset-wide absence), with no real
justification for the difference. Standardized on plain `None` everywhere (kept
`NaT` for `published_time`, which is the legitimate, standard datetime-missing
marker). Also explained why these all-null-for-one-dataset columns stay in the
schema at all: they're not null in general, only null in MIND's instance of a
shared schema — dropping them would break the "one unified schema, run per
dataset" design from the earlier Q1-scope clarification, and `session_id` /
`timestamp_sequence` map directly to the assignment's "session context" and
"recency/decay" requirements.

### "wait you didnt modify @build_pipeline.ipynb with this None edit"

Caught a real mistake: the fix above was made in the notebook-generator script and
the *parquet output* was re-verified as correct, but the actual notebook source
cells hadn't been regenerated yet — the parquet round-trip through
`pd.read_parquet` silently downcasts the `"string"` extension dtype's `<NA>` back
to plain `None`, which is what made the stale notebook's output look already
fixed. Re-ran the generator and confirmed the notebook source itself, not just the
downstream parquet file, now reflects the fix; re-executed the full pipeline to
confirm. Lesson: when verifying a source-code fix, check the source (or its
directly executed output), not a downstream artifact that can independently mask
the same symptom.

### "update SPEC.md with Q2 from the assignment"

Extended `SPEC.md` from Q1-only to also cover Q2 (BM25 lexical retrieval), design
only (no code yet). A Plan agent produced a fully hand-rolled BM25 design (own
inverted index, IDF, scoring) verified against real data — tokenization behavior
on Danish text, null rates, click-count distributions, per-split user counts.
Asked the user to choose between that hand-rolled approach (matches the
assignment's literal "build an inverted index" wording, no new dependency) and
using a library; **the user chose the `rank-bm25` library** instead, so the spec
was rewritten around `BM25Okapi`, with an explicit honest note that the library
doesn't expose a true sparse inverted index internally (dense per-term numpy
scoring instead) — mitigated by adding an inspection step that surfaces the
library's internal `idf`/`doc_freqs`/`doc_len`/`avgdl` attributes as the index
artifact, rather than hiding the gap between the assignment's wording and the
chosen implementation.

### "don't add context like this in the SPEC.md. It should only contain the details of the implementation... this like current work, what the plan agent did, responses to AskUserQuestion, etc are not part of SPEC.md"

Important standing correction to how `SPEC.md` should read: it's a pure technical
spec, not a narrated log of the planning process. Rewrote the Q2 plan/content to
strip all meta-narrative ("the user chose", "a Plan agent verified", "this task
does X") and state every design decision as plain fact, matching Q1's existing
tone exactly. This distinction — process narrative belongs in the plan file or
`PROMPTS.md`, never in `SPEC.md` itself — applies to all future spec edits.

### "Start implementing Q2"

Implemented the (then rank-bm25-based) Q2 spec: added the dependency, built
`src/bm25_retrieval.ipynb`, and ran it. It never finished — killed after 10
minutes. Benchmarked the actual bottleneck rather than guessing: a single
`BM25Okapi.get_scores` call on MIND's 65k-article corpus took ~2.9 seconds,
because the library does a Python-level dict lookup across every document per
query token instead of a sparse postings lookup — at ~70,000 required calls
(once per val/test user), that's 40+ hours. Fixed by building a real
postings-list inverted index (`term -> (doc_idx, tf)` arrays, scored via
`numpy`'s `np.add.at`), sourcing `idf`/`doc_len`/`avgdl` from the fitted
library object for cross-checking — measured at ~5ms/call, a ~1000x speedup.

### "ok do one thing, dont use rank_bm25, do a simple from scratch implementation of bm25, in module format, and see if it is faster or not"

Given the library was already reduced to just supplying statistics (the actual
scoring was hand-built for performance), the user asked to drop it entirely
and reimplement BM25 fully from scratch, as a proper importable module rather
than notebook cells — a deliberate exception to the project's usual
"all code in notebooks" rule for this one reusable, performance-sensitive
component. Built `src/cs4406m26_assignment1c1/bm25.py` (postings index, IDF,
scoring, top-K), benchmarked it standalone (~5ms/query on MIND, matching the
hybrid approach's speed), confirmed with the user before wiring it into the
notebook, then removed the `rank-bm25` dependency, rewrote
`src/bm25_retrieval.ipynb` and `SPEC.md`'s Q2 section around it, and reran the
full pipeline successfully (all test cells pass; recall@K monotonic and
bounded in [0,1] for both datasets).

### "Update SPEC.md with specs for all the other Qs in the assignment"

Extended `SPEC.md` from Q1+Q2 to cover Q3–Q9, design only (no code). A Plan
agent designed Q3 (embeddings) and Q4 (eval harness) together, verified
against real data throughout — e.g. it identified and measured that Q4's
AUC/MRR/nDCG can't reuse Q2/Q3's persisted top-K lists (candidate-generation
framing) and instead need an on-the-fly re-scoring adapter over each
impression's own `article_ids_inview` (re-ranking framing) — a real
reconciliation between the two question's evaluation setups, not just style
matching. The user was asked to pick Q3's embedding-source strategy (EB-NeRD
has provided pretrained artifacts, MIND has none) and chose one uniform
method for both datasets over an asymmetric or Colab-deferred approach.
Q5 (Codabench submission) needed external research — fetched both
competition pages directly rather than guessing a submission format; both
turned out to be JS-rendered SPAs requiring a login to see, so the spec
states that limitation explicitly instead of inventing a plausible-looking
format. Also noticed `design_note.tex`/`.pdf` already existed in the repo
(not created by this session) and grounded Q6's spec in that existing
skeleton rather than proposing a new location.

### "Start implementing Q3"

Before installing anything, asked whether to proceed with the planned
`sentence-transformers`+`torch` local benchmark (per SPEC.md's Q3 draft) or
skip to the lighter TF-IDF+SVD fallback. The user redirected entirely: don't
benchmark locally at all — build a Colab notebook that computes the
embeddings on a GPU there, downloaded back and placed locally, so the local
machine only ever does inference/retrieval math, never model
training/encoding. This matches `CLAUDE.md`'s own tech-stack note (heavy
compute belongs in Colab) better than the original local-benchmark plan did.
Built `src/compute_embeddings_colab.ipynb` (upload articles.parquet for both
datasets, encode with a GPU-loaded multilingual XLM-RoBERTa-based model,
download the resulting embeddings) with step-by-step usage instructions
inline and in `README.md`; syntax-checked every code cell since it can't be
executed locally (needs `google.colab` + a GPU). Rewrote SPEC.md's Q3 #1
around this split: Colab computes embeddings (no local speed constraint,
since GPU removes the concern that drove Q2's benchmark-first discipline),
local repo stays at zero new ML dependencies and only reads the resulting
parquet files.

### "why are the embeddings in .parquet format? shouldnt they be in .vec format?"

A genuine format-choice question, not a correction — explained the tradeoff
(parquet: consistent with every other artifact this pipeline produces,
typed/schema-enforced, carries the extra `dataset` column naturally; `.vec`:
the standard word2vec-style IR interchange format, human-greppable, and what
MIND's own provided KG embeddings happen to use — though that's just the
legacy format Microsoft's original TransE tooling exported, not a convention
this project chose, and those files aren't even used per Q3's design) and
asked whether there was a specific downstream interoperability reason (e.g.
loading into `gensim`) before proposing to actually change it. The user's
next message moved on to a different, larger change (Colab → Kaggle) instead
of answering this, so the format stayed parquet — worth re-raising if it
resurfaces.

### "ok nvm i wont use colab, i'll use kaggle, so modify everything accordingly"

Platform swap for Q3's hosted-GPU embedding step: replaced
`src/compute_embeddings_colab.ipynb` with `src/compute_embeddings_kaggle.ipynb`
(deleted the old file rather than leaving both). Worked out the real
mechanical differences rather than assuming Kaggle mirrors Colab's API —
Kaggle has no in-notebook upload/download calls (`google.colab.files.*`);
input comes from a Dataset attached via "+ Add Data" under
`/kaggle/input/...` before the notebook runs, and output is anything written
to `/kaggle/working/`, downloaded from the run's Output tab after "Save &
Run All". Also swapped GPU/internet setup instructions (Kaggle's Internet
toggle defaults off, unlike Colab, and is required for the `pip install` +
model download to work). Updated `SPEC.md` Q3 #1/#7 and `README.md`'s Q3
section to match, and grepped all three files afterward to confirm no
leftover Colab references remained.

### "I have dropped the output files at your specified location, now continue"

Verified the two Kaggle-computed `article_embeddings.parquet` files directly
before building anything on top of them (shape matches article counts, 768
dims, no NaNs, no duplicate IDs, article_id sets match `articles.parquet`
exactly) rather than assuming the hand-off worked. Built
`src/cs4406m26_assignment1c1/embeddings.py` (mean-pool, batched brute-force
cosine-similarity top-K) and benchmarked/sanity-checked it directly against
the real MIND embeddings before wiring it into a notebook — same discipline
as Q2. That benchmark surfaced a real, worth-understanding subtlety: a
same-query top-200 result and a separately-computed top-50 result didn't
match exactly. Root-caused it (not dismissed) — BLAS matrix multiplication
isn't bit-exact across different batch shapes, so near-tied cosine scores
(~6e-8 apart, float32 epsilon) can swap order between differently-shaped
calls; confirmed a single-call result matches a naive full sort exactly, so
the module itself is correct, and the real pipeline never compares across
separately-shaped calls anyway (it calls once at k=200, slices prefixes for
50/100). Documented the caveat in the function's docstring and designed the
notebook's nesting-invariant test to only ever compare same-shaped calls, so
it can't spuriously fail on this artifact. Built `src/embedding_retrieval.ipynb`
+ `embedding_retrieval.py` mirroring Q2's structure, including a cold-start
cross-check against Q2's already-persisted `bm25_metrics.json` (must match
exactly — same users, same criterion, independently recomputed in a separate
notebook) and a lexical-vs-semantic comparison table. Ran end-to-end
successfully; all 8 test cells pass, and the comparison table shows a
genuine mixed result (BM25 generally ahead, embeddings win on MIND's test
split at K=50) worth keeping for the design note.

### "modify the code based on updated CLAUDE.md" (re: new rule 4 — numeric claims need a one-command README verification)

`CLAUDE.md` gained a new rule: any numeric performance claim written into
`SPEC.md` must come with a command in `README.md` that reproduces it in one
shot. Audited `SPEC.md` for claims of that kind (a measured benchmark, not a
persisted metric already reproducible via the existing `build_pipeline.py`/
`bm25_retrieval.py`/`embedding_retrieval.py` commands) and found two: Q2 #1's
BM25 timing (`rank_bm25` vs. the from-scratch module) and Q3 #2's brute-force
matmul/top-K timing. Wrote `scripts/benchmark_bm25.py` and
`scripts/benchmark_embeddings.py`, ran both against the real feature store to
confirm the numbers are still in the right ballpark (BM25: ~2.8ms/query on
MIND, ~189s extrapolated; embeddings: 11.5s matmul + 19.0s top-K = 30.5s
total on MIND's full 65,173-user val/test population — both consistent with
`SPEC.md`'s claims), and documented both commands in `README.md` right after
their respective Q2/Q3 sections. The `rank_bm25` comparison itself isn't
re-run by the script since that dependency was deliberately removed; the
script benchmarks the shipped path only and notes how to re-add the library
if that specific comparison point needs re-verifying.

### "Finish Q4 in the spec"

Implemented Q4 (Offline Evaluation Harness) end-to-end from the design
already locked into `SPEC.md` — no new design decisions were open, so this
went straight to implementation rather than a plan/AskUserQuestion round.
Built `src/cs4406m26_assignment1c1/evaluation.py` (auc_impression, mrr,
ndcg_at_k, bootstrap_ci, intra_list_diversity, novelty, coverage — pure
functions, unit-tested against hand-computed toy values before touching real
data) and `src/evaluation_harness.ipynb` + `evaluation_harness.py`.

One real design gap had to be resolved during implementation, not just
transcribed from the spec: `score_inview` needs a defined score for
cold-start users (empty click history), but Q2/Q3's embedding path returns
nothing for a user with no mean-pooled vector. Resolved it by having both
adapters fall back to an all-zero score per inview item for a cold-start
user — BM25 already does this naturally (an empty query touches no
postings), so the embedding adapter was made to match. An all-zero vector
produces a well-defined but fully-tied ranking, which works out to exactly
AUC=0.5 by the rank-sum formula — confirmed on real data (MIND's cold-start
slice reports auc.point == 0.500 exactly, for both methods, both splits).
This is what makes cold-start-vs-warm a genuine *slice* for Q4's ranking
metrics (both groups get scored) rather than an *exclusion* like it is for
Q2/Q3's recall@K (a cold-start user literally has no query to retrieve
with). Also had to work out the efficient shape of `score_inview`: the outer
per-impression loop needed a uniform `(user_id, article_ids_inview) -> dict`
signature per SPEC.md, but a naive implementation would recompute BM25's
full-corpus `get_scores` on every impression; instead each split is
processed sorted by `user_id` and the BM25 adapter memoizes the last user's
score vector, so `get_scores` runs once per unique user (~72,591 total
across both datasets) rather than once per impression (~264K) — full
population caching was ruled out first (a full-corpus float vector per MIND
user would be ~26GB).

Ran the harness end-to-end (background, ~a few minutes given the per-user
BM25 rescoring volume) — all 11 test cells passed, including the cold-start
AUC=0.5 sanity check and a cross-check of head/tail popularity-skew figures
against SPEC.md's already-verified real-data numbers. A genuinely interesting
result for the design note: embeddings rank *better* than BM25 within each
impression's own inview candidates on both datasets (e.g. MIND test AUC
0.595 vs. 0.556), the opposite of Q2/Q3's recall@K where BM25 generally led
at full-catalog retrieval — the two framings measure different things
(finding vs. ranking) and don't have to agree.

Per `CLAUDE.md`'s numeric-claims-need-a-README-command rule, also wrote
`scripts/benchmark_bootstrap_ci.py` for Q4 #5's "well under a second" bootstrap
timing claim (measured: 0.47s for MIND's ~73K-impression test split, 1,000
iterations) and documented it in `README.md` alongside the new
"Run the offline evaluation harness (Q4)" section.

### "for Q5, i want to submit to the codabench leaderboards, give me the process to do that"

`SPEC.md`'s Q5 section had previously stated the submission file format
couldn't be verified since both Codabench competition pages are JS-rendered
and login-gated. Re-attempted verification using the assignment PDF's own
cited links (the EB-NeRD starter repo, `github.com/jppol-ai/ebnerd-benchmark`,
and the two Codabench competition URLs) rather than giving up at the first
failed fetch. The Codabench pages themselves were confirmed still
unreachable (only navigation chrome, as before), but following the starter
repo's README to `examples/quick_start/nrms_ebnerd.py` led to
`ebrec.utils._python.write_submission_file`/`rank_predictions_by_score` —
real, verifiable source code, not a guess. Cross-checked against the MIND
side independently via the reference `recommenders-team/recommenders`
NRMS-on-MIND example notebook, since the assignment's MIND competition has
no equivalent starter repo of its own; both implement the identical format
(`{impression_id} [{rank1,...,rankN}]`, one line per impression, N =
`len(article_ids_inview)`, ranks computed via `argsort(argsort(-scores))+1`
over the *original* inview order, zipped as a single file). Also checked our
own pipeline's actual `impression_id` values (e.g. `mind_dev_1`,
`ebnerd_144772`) to confirm the native (non-namespaced) ID needed for
submission is recoverable by stripping the dataset prefix. Rewrote `SPEC.md`
Q5 with this now-verified format and a narrowed, honest "still unverified"
note (only the exact hidden-test-set population remains unconfirmed, not
the file format itself). Did not implement `generate_predictions()` yet —
the user asked for the process, not the code; offered to build it next.

### User pasted MIND's actual Submission Guidelines page content (logged into Codabench)

Confirms the rank-encoding format independently derived from source code in
the previous prompt is exactly right, and adds facts that couldn't have been
guessed from source code alone: the zip must contain `prediction.txt` at its
**root** with no subfolder/`__MACOSX` entries; **row order in the file must
match the original impressions file's order** (not re-sorted); max one
submission per day; a separate validation-set submission is allowed during
development to avoid burning the daily test-set quota. Updated `SPEC.md`
Q5 #2 with these now first-party-confirmed MIND details, and narrowed #3's
"still unverified" note to the one thing that still isn't confirmed: MIND's
grading test set is very likely the original (never-released) MIND
challenge test set, not MINDsmall's provider `dev/` that this project has
been treating as its own `test` split — since this is the long-running
CodaLab-era MIND competition, not a from-scratch dataset. Flagged that
`generate_predictions` may need a competition-provided impressions file as
an extra input rather than reusing the existing feature store, pending a
check of the competition's own Data/Files tab. Also updated #4's
implementation note: the evaluation-harness pattern of sorting impressions
by `user_id` for BM25-cache efficiency (Q4) must NOT carry into the
submission file — row order there has to match the source file exactly.

### "there is no extra test data there. Do one thing, use the current local training data as train set, dev as test set and create the generate_predictions based on that"

Resolved Q5 #3's remaining open question: checked the MIND competition's
own Data tab directly — no separate hidden test file exists — so
`generate_predictions` reads straight from the existing feature store,
predicting over MIND's own `test` split (== MINDsmall's provider `dev/`),
exactly as Q1–Q4 already treat it. Implemented `generate_predictions(method,
split="test")` in `src/generate_predictions.ipynb` + `generate_predictions.py`
(MIND only — EB-NeRD's Submission Guidelines page is still unconfirmed),
reusing the same `score_inview` adapters as Q4. First run failed on the
round-trip test cell (`ValueError: invalid literal for int() with base 10:
'6]\r'`) — root-caused rather than patched around: `Path.write_text()` on
Windows silently translates `\n` to `\r\n`, leaving a stray `\r` glued onto
the last rank of every line once zipped and re-parsed, which `.strip("[]")`
doesn't clean up since `\r` sits outside the stripped character set. Fixed
by writing the file as raw UTF-8 bytes instead, matching what the reference
implementations (which run on Linux/Mac, so never hit this) actually
produce. Re-ran end-to-end: all 3 test cells pass, and a direct inspection of
the resulting zip confirms 73,152 lines (MIND's real test-split impression
count), no `\r` contamination, and every line's ranks are a valid 1..n
permutation. Generated submissions for both methods
(`submissions/mind/mind_{embedding,bm25}_test_prediction.zip`); embeddings
is the one to actually upload, per Q4's finding that it outperforms BM25 on
MIND's ranking metrics.

### User pasted a Codabench evaluate.py traceback after submitting the MIND BM25 zip

`IndexError: boolean index did not match indexed array along dimension 0;
dimension is 22 but corresponding boolean dimension is 16` inside their
`evaluate.py`'s `my_auc`. Root-caused rather than guessed at: fetched the
official MIND evaluation script (`github.com/msnews/MIND/blob/master/evaluate.py`,
found via web search once a direct URL wasn't in hand) and read its actual
matching logic -- truth and submission files are read line-by-line in
lockstep, with an impression-ID equality check per line. Since the error was
a *shape* mismatch, not the script's own "Inconsistent Impression Id" error,
the ID at that line matched but the candidate-set size didn't, meaning
Codabench's real ground truth has different data for that impression than
what we submitted. Verified our own local pipeline is innocent first, not
last: MIND's `test`-split native impression IDs are exactly 1..73,152 with
no gaps/duplicates, `behaviors.tsv`'s raw line count matches our parsed row
count exactly, and the file has zero `"` characters (ruling out a
pandas CSV-quoting misparse). Searched for the deployed dataset's official
download source and found (via web search) that Microsoft's own blob
storage for MINDsmall now returns 409/no public access -- a known, currently
open issue (`recommenders-team/recommenders#2133`) -- which is presumably
why the assignment pointed to a third-party Hugging Face mirror instead;
concluded the most likely explanation is a content difference between that
mirror and whatever Codabench's ground truth was actually built from, but
couldn't fully confirm without the truth file. Ended the turn by asking the
user to check Codabench's own scoring error log for more detail, rather than
guessing further blind.

### "i have provided 2 new scripts for download the correct datasets... modify them such that they run on my machine with my proper format, dont run them, also make sure that i can see the download progress in the terminal when i run them manually"

The user's two new root-level scripts (`download_ebnerd.py`,
`download_mind_large_test.py`) resolved the previous prompt's mystery:
`download_mind_large_test.py` fetches `MINDlarge_test.zip` -- MIND's real,
separate, unlabeled Codabench test set -- confirming the suspicion that
MINDsmall_dev was never the right population to submit against. Went into
plan mode to scope the fix (both scripts reference a foreign project's
conventions that don't exist here -- a `news_reco` package, `configs/*.yaml`,
a `scripts/` directory -- plus a real path bug in the MIND script,
`parent.parent` walking one directory above the actual repo root). Asked two
scoped questions via AskUserQuestion: **the user chose to add both
`requests` and `huggingface_hub` as new dependencies** (rather than a
stdlib-only rewrite), and confirmed **not yet authenticated with Hugging
Face**, so the plan called for an upfront fail-fast auth check. The user
rejected the plan at the approval step (did not explain why) and redirected
to a different, narrower task instead -- the two-script fix itself was not
implemented this turn.

### "now generate Q5 for EB-NeRD"

Generalized `src/generate_predictions.ipynb`/`generate_predictions.py` from
MIND-only to both datasets in one pass, following this project's established
"shared code, separate runs per dataset" pattern (same as Q1-Q4) rather than
a one-off EB-NeRD-specific notebook. The two competitions' confirmed/inferred
submission filenames genuinely differ (MIND: singular `prediction.txt`,
confirmed directly; EB-NeRD: plural `predictions.txt`, inferred from
`ebrec.utils._python.write_submission_file`'s own default, not yet confirmed
against EB-NeRD's own guidelines page) -- handled via a small per-dataset
filename lookup rather than assuming one format for both. Also corrected a
now-known-wrong claim left in `SPEC.md` from an earlier turn ("MIND --
resolved... no separate hidden test file exists") given the real submission
failure investigated two prompts ago -- rewrote it to state plainly that
this was wrong, why, and that it's not yet fixed. Explicitly flagged the same
unverified-population risk for EB-NeRD's new submission zip, rather than
silently repeating the mistake that just broke MIND's real submission.
Ran end-to-end: all 3 test cells passed for both datasets; directly
inspected the EB-NeRD zip too (not just trusted the test cell) --
25,356 lines matching EB-NeRD's real test-split impression count, correct
`predictions.txt` filename inside the zip, no CRLF contamination, valid
rank permutations. Cleaned up stale zip files left over from the prior
MIND-only run's different naming scheme.

### User pasted a Codabench score.py traceback after submitting the EB-NeRD embedding zip

`ValueError: line-1: Inconsistent Impression ID 144772 and 6451339` --
confirmed, rather than just suspected, that EB-NeRD has the exact same
problem just found for MIND: `generate_predictions` was predicting over the
wrong population. This time it's an outright ID mismatch (not a shape
mismatch like MIND's), meaning Codabench's very first ground-truth
impression isn't even present in `ebnerd_demo`. Root-caused directly rather
than assuming symmetry with MIND: searched for an official EB-NeRD test
bundle, then verified via `curl -I` against the same public S3 bucket
`download_ebnerd.py` already uses that `ebnerd_testset.zip` exists (200 OK,
~1.6GB) -- a dedicated, much larger, Codabench-specific test set, exactly
mirroring `MINDlarge_test` vs. MINDsmall_dev. Updated `SPEC.md` Q5 #3 with
this confirmed (not just suspected) finding. Not yet fixed: `download_ebnerd.py`
only supports the `demo`/`small` bundles so far and needs a `testset` option
added, then Q1's pipeline and this section's `generate_predictions` re-pointed
at it once downloaded.

### "i just downloaded ebnerd_small, do Q1 to Q5 on ebnerd small and generate me the submission zip"

First attempt at this repointed `build_pipeline.ipynb`'s single `EBNERD`
constant from `ebnerd_demo` to `ebnerd_small` in place, which would have
silently destroyed the already-committed demo-based Q1-Q4 results the moment
the pipeline was rerun.

### "ok no hangon, you are modifying ebnerd to change it from demo to small. I dont want that, keep both the demo and small ones" (stated twice, first message got cut off)

Critical correction — caught an in-place overwrite of an established dataset
before it landed. Two real design decisions were resolved via
`AskUserQuestion` rather than guessed: (1) naming — keep `ebnerd` pointed at
demo, unchanged, and add a wholly new `ebnerd_small` track alongside it
(chosen over renaming both to something else); (2) sequencing — restore the
demo-based pipeline first, verify it, then build `ebnerd_small` (chosen over
building small first). `build_pipeline.ipynb` was restructured so every
EB-NeRD builder function (`build_ebnerd_articles`/`build_ebnerd_behaviors`/
`build_ebnerd_history`) takes a `prefix` argument and is called twice — once
per EB-NeRD track — rather than duplicating the notebook. Re-verified Q1 and
Q2 end-to-end for all three tracks afterward (`ebnerd` correctly restored to
demo scale: 11,777 articles/50,080 behaviors/1,935 users; `ebnerd_small`
built fresh: 20,738/477,534/18,827; `mind` unaffected). Standing lesson: never
silently repoint a shared, already-established dataset path in place to add
a new variant — treat it as additive, in its own namespace, unless
explicitly told to replace.

### "when i ran on kaggle, why did ebnerd small take less time than ebnerd demo? isnt' the small one larger?"

A genuine "why does the data not match intuition" question, not a task —
answered directly rather than guessed: `ebnerd_small`'s article catalog
(20,738 rows) is larger than demo's (11,777), so if raw `model.encode()`
throughput were the only factor, small should have taken longer. The more
likely explanation is that per-run *fixed* costs — `pip install
sentence-transformers`, downloading the ~1GB `paraphrase-xlm-r-multilingual-v1`
model weights from Hugging Face, CUDA/cuDNN initialization — dominate total
Kaggle notebook wall time far more than the actual encode step does at these
corpus sizes, so whichever run happened to hit a faster network pull or a
better-available GPU (T4 vs. P100, or a less-contended shared T4) can easily
finish faster despite having more rows to encode. Secondary candidate: total
tokens (not row count) drives `encode()` cost, so if `ebnerd_small`'s
titles/abstracts are shorter on average, it can process more rows in less
wall time.

### "the @ebnerd_small_articles.parquet file, is it just a renamed version of the articles.parquet in ebnerd_small/ directory?" / "no sorry sorry, i upload the file in data/processed/ebnerd_small/articles.parquet and renamed it. Is it different from the file in the repo root?"

Data-provenance question, verified by directly reading and diffing the
parquet files rather than reasoning from memory. First answer: no — the raw
`ebnerd_small/articles.parquet` (21 native EB-NeRD columns, int `article_id`)
is structurally different from the root `ebnerd_small_articles.parquet` (8
unified-schema columns, prefixed string `article_id`) that was actually
uploaded to Kaggle; confirmed by reading both files' schemas directly. Once
the user clarified they'd actually renamed a copy of
`data/processed/ebnerd_small/articles.parquet` (the *processed* file, not
the raw one), re-verified with `DataFrame.equals()` that it's byte-for-byte
identical to the prepared root copy — confirming the correct file was
uploaded.

### "ok then, article_embeddings.parquet is the vector file trained from kaggle. That part is done, you can now continute"

Unblocked Q3-Q5 for `ebnerd_small` once the Kaggle-computed
`article_embeddings.parquet` was placed at
`data/processed/ebnerd_small/article_embeddings.parquet`. Extended the
`DATASETS` list in `embedding_retrieval.ipynb` (Q3), `evaluation_harness.ipynb`
(Q4), and `generate_predictions.ipynb` (Q5) from `["ebnerd", "mind"]` to
`["ebnerd", "ebnerd_small", "mind"]` — mechanical for Q3 (fully generic
notebook, zero other code changes), but Q4 needed a real fix: its bootstrap-CI
test hardcoded `expected_none` assuming only one dataset (`ebnerd`) has zero
cold-start users, which would have silently doubled once `ebnerd_small`
(also zero cold-start users) joined and failed the assertion. Fixed by
computing the expected count of degenerate slices dynamically from
`coldstart_users` instead of a hardcoded constant. Also caught and corrected
a stale numeric claim while touching adjacent text in `SPEC.md`: MIND's
cold-start user count was cited as "2,122" in four places, but the real,
already-verified figure (cross-checked against `bm25_metrics.json` in the
harness's own test cell) is 1,770 distinct users — fixed all four occurrences
rather than propagating the error into new `ebnerd_small` figures alongside
it. Reran Q3/Q4/Q5 end-to-end for all three datasets and verified real
output (not just trusted test-cell "ok" prints): `ebnerd_small` embedding
recall trails BM25 the same way both other tracks do (Q3), embeddings beat
BM25 on ranking AUC the same way both other tracks do (Q4: 0.550 vs 0.501),
and `generate_predictions` produced a correctly-formatted (but
not-for-Codabench-submission, since `ebnerd_small` isn't a real competition
track) `predictions.txt` zip (Q5). Updated `SPEC.md` and `README.md`
throughout to describe three dataset tracks instead of two.
added before this can actually be resolved, same open follow-up as MIND's.

### "look bro, i have written some parts of the design_note on my own, write the rest pls :) keep the formal followed in the assignment. Don't use overly complex words, use simple ones and don't use em-dashes. Match the writing style already present in the design note so far" (interrupted, then "you were interrupted, continue pls")

Completed `design_note.tex` (Q6), which previously had only the Introduction
and a half-finished BM-25 Preliminaries subsection. Read the assignment PDF
and `SPEC.md` first, then pulled real numbers straight from the already
executed notebooks' saved cell outputs (`bm25_retrieval.ipynb`,
`embedding_retrieval.ipynb`, `evaluation_harness.ipynb`) instead of
re-deriving or guessing figures, since `data/processed/` itself is
gitignored and not present in the working tree. Finished the BM-25 formulas
(IDF, document length normalization, final score), added one subsection per
Q1-Q5 pulling each one's "why" from `SPEC.md`, and a Discussion section with
a real recall@200 table, the AUC reversal between candidate-generation and
re-ranking framings, dataset differences, and a 10x scale-breakdown list.
Q5's subsection reports the still-unresolved Codabench submission failures
honestly (candidate-set/impression-ID mismatches, root-caused to the wrong
test population) rather than presenting Q5 as complete.

The assignment caps the design note at 4 pages; the first full draft
compiled to 6. Cut prose by roughly a third across every subsection,
tightened margins and list spacing (no `enumitem`/`titlesec` available
locally, so list spacing was tightened via a manual `\@listI` redefinition
instead), and iterated by actually compiling with `latexmk` and checking the
rendered page count and per-page character distribution each time, rather
than guessing at length. Rendered each final page to a PNG for a visual
proofread pass before finishing.
