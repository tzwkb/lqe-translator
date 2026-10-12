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

New jobs default to `--acceptance-mode score_threshold --max-cycles 6
--max-seconds 5400`. Stages include baseline, incremental and final reviews;
they are not six repair attempts. For a bounded development trial, use
`--max-cycles 3 --max-seconds 1200` on a small representative sample. The total
wall-clock allowance starts at initialization and survives resume. `run` bounds
each worker wait by the remaining allowance and terminates its owned process
group on expiry. A manually connected worker must also honor that allowance;
the controller cannot cancel an external process it does not own.

An existing Agent can instead call `next`, perform its request, then `submit
--response /absolute/response.json`. No human translation step is required.
Interruption preserves the same pending request and published check packets.

## Stages

Every response copies the exact `request_id`.

**review:** Read the supplied `review_execution.json` first. A `small_multi_module`
assignment uses one fresh checker for all assigned dimensions (at most 30 segments,
6000 source/target characters, one native packet per dimension and 250 KB of
lossless reading input). `review_reading.json` factors identical fields and shared
resources; `common` plus `by_module[module]` exactly reconstructs the original
records. Its collection `order` preserves per-module segment order. No style guide,
semantic field, required dimension or native scoring rule is removed. Apply each
module-specific field to its own dimension. Larger jobs and specialized/strict
context retain the native module batches and evidence boundaries. This reduces
repeated context reading; it is not a measured latency or quality guarantee.

For a small assignment, forward the generated `checker_task.md` unchanged to one
fresh checker using synchronous delegation. Do not rebuild the task, inspect
implementation source or write a background polling script. The reading pack
includes `finding_contract`, including the native terminology confirmation
declarations. After the checker returns, bind its actual returned ID with
the command appropriate to the frozen execution plan:

- With `checker_view_sha256`, the checker reads the directly expanded
  `checker_view.md` (complete SG, language notes, module instructions, source/target
  and semantic evidence). It fills one `review_response.json` from
  `review_response.template.json`, preserving `assignment_id` and full
  `reviewed_ids_by_module`, and supplying `findings_by_module` and `decisions`.
  Run `lqe_review_execution.py submit-response --job <stage-job> --worker-id <actual-id>`.
  The program validates the assignment, coverage and all precheck decisions before
  generating native drafts; it copies model judgments unchanged and binds identity.
- Without that field, an older frozen assignment keeps its original task/reading
  pack and compact drafts. Run
  `lqe_review_execution.py bind-worker --job <stage-job> --worker-id <actual-id>`.

Both paths generate a fresh run ID; neither writes semantic verdicts or scores.
Never invent an ID or choose an uncertainty verdict to satisfy a schema. The full
lossless archive remains authoritative; its transport hashes are program-validated,
not a reconstruction task for the checker. Larger or specialized assignments keep
the native module-batch path. A smaller readable view is not a measured speed claim.

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

The structured response supplies the `decisions` list; the program copies it to
`precheck_decisions.json`. Older/batched assignments write that file directly. In
either case there is one decision per machine hint.
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
In `score_threshold` mode these requests cover Critical or unknown-severity
historical disagreements only. Unreported noncritical issues stay `disputed`
in the ledger; absence never means verified repair. They do not trigger a
separate adjudication or extra repair cycle. `--acceptance-mode strict` retains
the earlier all-disputes gate; frozen jobs without this field keep strict rules.

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
incremental review/sampling and then a new full final review. Unchanged evidence
is bound to text, context, resources, runtime and model configuration. Existing
reuse-drafts rules are unchanged. Repeated states, exhausted attempts and lack of
verified progress stop as unmet threshold; unlimited retries do not guarantee 98.
Current findings keep their native scoring weights. A passing final review ends
the workflow immediately: do not generate another repair candidate or rerun to
chase a higher score. Noncritical residual findings and historical disagreements
stay visible. Critical errors, unresolved Critical disagreements, unreviewed
changes and broken tags/variables still block acceptance. Hitting a time/stage
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
