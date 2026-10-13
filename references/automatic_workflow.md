# Automatic acceptance workflow v1

This is an opt-in controller protocol, separate from ordinary single-pass LQE and
the report-only reference-suggestion workflow. Initialize from a fresh native
`read --review-mode full` job; do not change an existing job's review policy.
The controller owns versions, coverage, issue history, scores and acceptance.
Workers must not edit state, policies, source files, manifests or final artifacts.

## Entry points

`scripts/lqe_workflow.py` provides `init`, `next`, `submit`, `run`, `status`,
`verify` and `report`. Every command takes `--workdir`.

Initialize with `init --state /absolute/native-job/state.json --runtime-config
/absolute/runtime.json`. The configuration requires `model` and, for unattended
`run`, `worker_command` as an argument array. This command runs a JSONL worker:
read one request per stdin line, write one response per stdout line, logs to
stderr. `run` keeps the orchestration process alive. Optional
`request_timeout_seconds` defaults to 1800. A declared model is not proof of the
remote model used; the adapter must honor the frozen configuration.

New standalone jobs use `--acceptance-mode strict --audit-rate 1.0`. Every
stage reviews the complete current document by default. There is no default
stage count or total time cap; repeated states, repair exhaustion and lack of
verified progress still stop the workflow as NOT ACCEPTED. Operators may set
`--max-cycles` and `--max-seconds` explicitly. Development model trials must use
representative samples and explicit limits that reserve a post-repair review and
a full final review. A configured budget persists across resume and never relaxes
acceptance when it runs out. `run` terminates only its owned worker process group;
manually connected workers must honor the same configured limits.

The controller preserves the supplied model/reasoning configuration. Integration
performance policies are not imported. Historical score-threshold records and
joint-review response parsers remain for provenance/compatibility; the CLI cannot
initialize new score-threshold jobs or select joint module execution.

An existing Agent can instead call `next`, perform its request, then `submit
--response /absolute/response.json`. No human translation step is required.
Interruption preserves the same pending request and published check packets.

## Stages

Every response copies the exact `request_id`.

**review:** Read the supplied `review_execution.json` and native batch plan.
New standalone jobs use `module_batches`, even for a tiny document. Assign separate
fresh checker contexts to terminology/precheck, accuracy, grammar and naturalness;
keep specialized contexts and module-specific evidence within their own packets.
A checker identity may not span different modules. Each new stage needs fresh
actual identities; the final checkers must not see earlier grades or verdicts.

Each checker returns its native compact drafts and dispositions for its machine
hints. Combine the dispositions into `precheck_decisions.json` without inventing
semantic decisions. Do not copy old drafts, fabricate worker IDs or silently
convert an already frozen execution contract. Runtime drift blocks resumption.

Follow every assigned packet's module instructions. Collect the completed compact drafts in
a directory containing only this stage's drafts, then publish them together with
`lqe_review_execution.py publish --job <stage-job> --input-dir <draft-directory>`.
It validates every precheck disposition before immutable publication, then delegates
to native `lqe_review.py publish-directory`. The native publisher validates the live generation once and validates all drafts,
and checks/skips already published valid receipts on retry. Avoid a per-packet
`publish` loop, which repeatedly rebuilds the same project context. Preparation and deterministic
auto-publication are already complete. Do not run read, apply-fixes, write, export
or finalize_job.sh. The controller verifies required coverage and native receipts.
Use fresh checker `worker_id` AND `run_id` values for every new stage. Never reuse
or migrate previous drafts. Within one stage, native batching and deduplication
remain valid. The orchestrator may persist; final checkers must not receive past
grades or issue verdicts. Submit `{"request_id":"..."}` when checks are published.

Write `precheck_decisions.json` with one decision per machine hint.
Each decision copies `module`, `chunk_id`, `id`, `precheck_ref`, then supplies
`decision` (retained/dismissed), `applicability`, a concise `reason` and literal
current `target_quote`. See the execution plan's schema. A retained terminology
finding requires same-sense evidence, not merely a source-string match. Ordinary
inflections, another sense and a partial name match do not establish a defect;
require an applicable explicit project rule before forcing an unnatural label.
The program checks coverage and agreement with the actual native findings; it
does not invent semantic decisions or change the score. A missing decision fails
validation rather than silently losing the hint. If there are no hints, the
program supplies the empty list without pretending a model judgment occurred.

**reconcile:** Only after blind review, inspect historical issues that were not
reported again. Return a fresh `worker: {worker_id, run_id}` and `verdicts` covering
exactly the requested issues. Each has `issue_id`, `decision`
(resolved/dismissed/retained/inconclusive), specific `evidence`, `rule_basis`, and
an exact current `target_quote`. Unchanged text cannot count as repaired; an old
false positive needs a reasoned dismissal. Do not alter the current findings.
Every unresolved historical issue, including Major, Minor and Neutral disputes,
requires an explicit evidenced verdict before acceptance. Omission in a new review
is not repair evidence. The old score-threshold policy is not available for new
standalone jobs; existing frozen records are never rewritten as stricter results.

**repair:** Return a fresh worker identity and `repairs` with `segment_key`,
candidate `target`, `reason`, and `addresses` containing all `issue_ref` values
for that segment in `repair_targets`. Nonempty proposals must cover all listed
penalized segments together. Preserve the current review's dismissed hints and
sense decisions; a literal substitution must not reintroduce a wrong sense.
Check each complete candidate against every dimension in the same generation;
do not add a separate paid self-score or candidate adjudication. Only active issue segments may change. Preserve
protected content and locked segments. Do not invent missing context or turn
reference-only terminology into authority. Candidates become a new unaccepted
revision and require independent checks. They are separate from report-only
`reference_suggestions.json`; do not promote that artifact to approval. An empty
list stops explicitly as unmet threshold if no defensible repair is available.

`attempts` preserves lifetime repair history. `attempts_since_resolution` counts
the current unresolved episode and controls repair escalation and exhaustion.
It restarts only when a previously verified or dismissed issue reopens; silence,
retained findings and inconclusive judgments do not reset it. Legacy records
without the new field conservatively use their lifetime count.

## Acceptance and artifacts

The default threshold is 98 with a mandatory Critical gate. Baseline 100 still
requires an independent full final review. Failed final reviews return to repair,
post-repair review and then a new full final review. Unchanged evidence
is bound to text, context, resources, runtime and model configuration. Existing
reuse-drafts rules are unchanged. Repeated states, exhausted attempts and lack of
verified progress stop as unmet threshold; unlimited retries do not guarantee 98.
Current findings keep their native scoring weights. A passing final review ends
the workflow immediately: do not generate another repair candidate or rerun to
chase a higher score. Residual findings remain visible and keep their native weights. Any unresolved
historical disagreement blocks acceptance, as do Critical errors, unreviewed
changes and broken tags/variables. Hitting a time/stage
budget stops as unmet threshold, never as accepted; it does not renew the budget
or launch a larger test automatically.
Before requesting another repair, reserve stages for both its incremental
verification and the full final review. If they cannot fit, stop immediately.

Intermediate stages save native check evidence without generating full-sentence
reference suggestions or formal workbooks. `report` creates a separate process
workbook and audit ZIP. Only after final acceptance does `delivery/` contain native
reports and source-format corrected files. `verify` rechecks the actual outputs.
SDLXLIFF/XLIFF sources, writeback and lock protection remain native; incremental
scope jobs cannot export an apparently complete corrected document.
