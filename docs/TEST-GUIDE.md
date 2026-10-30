# Print3DFlow test guide

Use this checklist with the [user guide](USER-GUIDE.md). This document defines tests to perform; an unchecked item is **not** a claim that the test has passed. Record PASS, FAIL, BLOCKED or NOT RUN for each case. A missing private profile or unavailable API is a blocked prerequisite, not evidence that a feature passed.

## Prepare a run

1. Record the commit under test (`git rev-parse --short HEAD`), browser and workspace URL.
2. Start the isolated workspace described in [User guide: test environment](USER-GUIDE.md#1-choose-your-test-environment). Use synthetic requests and the owned [sample STL](../samples/demo-block.stl).
3. Verify the workspace has no production jobs/reservations. Use synthetic pricing for public demos and before sharing quote totals externally.
4. Obtain your own owned/licensed single-color and component-assigned multicolor 3MF files if testing those paths. They are not bundled with the repository. Keep originals unchanged.
5. Record which prerequisites are present: Meta provider, native slicer, A1/A1 mini/X2D profiles, physical X2D status, camera and permitted light control.
6. Choose an explicit deadline at least three days ahead, including timezone in the request. Perform recovery tests before the proposed reservation starts; the scheduler can propose a slot only a few minutes ahead.
7. For baseline checks, note the selected quote, its total/currency, and each active reservation's printer/start/end. Recheck these after advice-only actions.

Suggested request: `Print 3 copies of this model in white PLA at the original size, as-printed, by [replace with exact future date, time and timezone].`

Live camera/Meta tests use accounts and devices from local configuration even in an isolated database. Light tests change a physical light and are optional operator actions. No test in this guide calls for remote printing. Keep private evidence local.

## A. Intake and geometry

### T01 - Required model

**Needs:** app only.

**Steps:** Open a new job, enter request text and quantity, leave the file empty, and attempt submission.

**Expected:** Job creation is disabled or rejected. Text alone does not create a job.

### T02 - Manual STL job

**Needs:** sample STL.

**Steps:** Upload the sample. Enter the material and color, confirm millimeters, enter three prints, choose As-printed, set a precise deadline and create the job without Meta extraction.

**Expected:** The actual sample geometry appears. Quantity is three; dimensions match the model and units, not three times its size. No reservation is created by intake.

### T03 - Meta intake and color parsing

**Needs:** Meta provider.

**Steps:** Upload the same sample and use the suggested request. Extract with Meta. Review quantity, material, color, units, finish and deadline before checking the review box and submitting.

**Expected:** Extraction alone creates no job. White PLA is interpreted as PLA plus white, not an unsupported material named `PLA white`. Missing information is clarified. Selected finish is not repeatedly requested. Model output is reviewed before creation.

### T04 - Specific-size clarification

**Needs:** Meta provider.

**Steps:** In a separate draft, request a `medium-sized` print without a numeric target dimension.

**Expected:** The draft requests a specific measurement or scale rather than silently applying an invented size. Check that the saved geometry and displayed dimensions have not silently changed.

### T05 - 3MF metadata and editable requirements

**Needs:** owned supported 3MF.

**Steps:** Upload a project with known units and assignments. Compare dimensions with Bambu Studio. Inspect suggested material/color, edit a suggested color, then continue the review.

**Expected:** Embedded units inform the dimensions. Only assigned slots suggest material/colors; unused palette slots are not treated as used. Manual edits remain available and preserved. Missing/conflicting assignments produce clarification rather than a fabricated mapping.

### T06 - Four-color detection and preview

**Needs:** owned supported component-assigned four-color 3MF.

**Steps:** Upload it, inspect the palette/assignments and rotate both sides of the model.

**Expected:** Up to four assigned slots are identified, with material and color names/swatches. Supported component colors appear on the real geometry. A generic sample block is not substituted. Unsupported paint or unresolved assignments remain flagged; preview appearance alone does not unlock quoting.

### T07 - Material and finishing safeguards

**Needs:** separate synthetic drafts.

**Steps:** Create an STL job requesting a material without a verified matching setup. Separately request custom finishing such as sanding or painting.

**Expected:** Requests can be recorded, but unsupported quoting remains blocked. Custom finishing has an additional-cost notice and requires review. Neither manual estimates nor Meta advice silently convert these to a standard PLA/as-printed quote. Use the currently displayed setup state; do not assume all PETG/ABS/ASA/TPU combinations are configured.

### T08 - Invalid or excessive files

**Needs:** a disposable invalid model or file exceeding the displayed limits.

**Steps:** Attempt upload without modifying any original owned project.

**Expected:** A validation/processing-limit message appears and no job is created from that invalid submission. Larger-model support remains bounded; it is not an unlimited-file promise. There is no repair-on-a-copy control in the current UI.

## B. Quoting, planning and approvals

### T09 - Native single-color quote

**Needs:** native slicer and one compatible configured PLA profile.

**Steps:** Use T02/T03, select Slice model, review settings and support information, confirm and slice. Compare the resulting report with Bambu Studio using matching model/settings.

**Expected:** Native provenance, material, time and breakdown are shown. Unknown support review stays unresolved. Quantity represents sequential copies, not automatic nesting. No reservation is created by slicing. Slicer consistency is not physical print calibration.

### T10 - Labelled manual estimate

**Needs:** eligible single-color PLA job; native slicer not required.

**Steps:** Select Manual estimate, enter invented reviewed grams/time and confirm its assumptions.

**Expected:** The result remains labelled as an operator estimate. It cannot bypass material, finishing or multicolor blocks. It is insufficient as native evidence for assisted execution review.

### T11 - Cross-printer candidates change nothing

**Needs:** at least two available supported profiles; all three for full A1/A1 mini/X2D coverage.

**Steps:** Note current quote/reservations, select profiles and reviewed support inputs, confirm and run Slice and compare selected printers.

**Expected:** Each eligible option has independently checked slice, quote and schedule facts. Failed/excluded profiles are identified. Candidate generation does not change the selected price or any reservation.

### T12 - Meta comparison requires separate data consent

**Needs:** T11 and Meta.

**Steps:** Leave quote-total sharing unchecked and inspect the advice button. Then grant permission and request Meta comparison.

**Expected:** Permission is required before sharing quote facts. Displayed recommendations/reasons reference supplied options. Advice does not select or approve an option. Customer files and full rate cards are not sent in this step.

### T13 - Production planner and verified tool trail

**Needs:** Meta; use a separate job with no comparison for the first step.

**Steps:** Grant planning-facts consent and Plan with Meta before a comparison. Then obtain current comparisons and run it again. Expand the Verified tool trail.

**Expected:** Missing comparison produces a request for verified comparison, not invented capacity. A ready case shows bounded read-tool results and a supported next step. Planning leaves selected price/reservations unchanged. Prices and customer text are excluded from planner facts.

### T14 - Explicit comparison approval

**Needs:** a current approvable comparison in the isolated workspace.

**Steps:** Select a radio option. Check that nothing changed. Read the exact price/currency and reservation. Check approval, then choose Approve price & reservation.

**Expected:** Only that explicit approval commits the comparison option. This UI control approves both its displayed price and reservation together. Do not mark an unapproved recommendation as scheduled.

### T15 - Stale advice

**Needs:** a planner result and an approved synthetic reservation.

**Steps:** Record the plan, approve a commitment or simulate a pre-start outage, then reload/revisit the planner. Request a new plan and fresh comparison when instructed.

**Expected:** Historical advice is marked stale and its recommendation is suppressed. Old approval evidence cannot bypass current checks. A refreshed request-comparison instruction is usable instead of inheriting obsolete advice.

### T16 - Outage recovery approval

**Needs:** approved test reservation that has not started.

**Steps:** Simulate printer outage, Propose recovery, optionally request Meta explanation, and review the option. Note original reservation before approval, then explicitly approve the chosen recovery path.

**Expected:** The outage is a database simulation, not a physical stop command. Before approval, the original reservation remains recorded. Approval atomically replaces the relevant reservation. Same-profile recovery may use a later slot on the same printer. No customer update is sent.

### T17 - Dedicated verified four-color quote

**Needs:** the narrow supported full X2D four-PLA project and reviewed AMS 2 Pro configuration described in the user guide.

**Steps:** Create a job from that file, select the same full reference in Verified X2D four-color quote, confirm settings and slice a candidate. Review reports, all slot/tool mappings, native grams and timing. Approve mappings/exact price; then find and separately approve a reservation.

**Expected:** Geometry/metadata mismatches and unsupported configurations are rejected. Candidate generation changes no selected price/reservation. Purge/tower material and change overhead are included once. Price approval alone creates no reservation. Standard manual/single-color/cross-printer routes cannot bypass multicolor verification. This is a separate workflow from T14.

## C. Optional physical-printer checks

### T18 - Correct printer identity and sampled telemetry

**Needs:** configured physical X2D.

**Steps:** Find the X2D on Printer schedule; refresh status. Compare with its screen. Also inspect a virtual/unconfigured printer panel.

**Expected:** X2D returns authenticated current status without exposing credentials. Other printer panels stay not configured; a demo job does not inherit the X2D connection. After sixty seconds without refreshing, the status is stale. A status of FINISH is not empty-bed proof.

### T19 - Camera start, sustained viewing and stop

**Needs:** local camera access working in Bambu Studio.

**Steps:** Start viewing the configured printer. Watch for at least thirty seconds. Stop viewing. Restart and, if practical, allow a full two-minute session to expire.

**Expected:** Video remains visible beyond the old five-second failure point. Stop/expiry prevents further frame retrieval; explicit restart is available. No video is saved, and camera/recording settings on the printer are unchanged. A normal expiry is distinct from a stream error.

### T20 - Optional light change

**Needs:** operator permission and fresh reported chamber-light state.

**Steps:** Record the original light state. Explicitly request the opposite state; observe the physical printer and reported confirmation. Restore its original state and refresh.

**Expected:** Only an explicit click changes the light. Unknown/stale state blocks the action. An unconfirmed result is not reported as success and is not automatically retried. No print, heater, motion or file-upload command is exposed. Mark BLOCKED if firmware disallows the action; do not claim physical switching based on simulated tests.

### T21 - Local capture and image-specific consent

**Needs:** active camera session.

**Steps:** Capture fresh bed image locally. Inspect the evidence. Leave image consent unchecked, then choose whether to grant it and request Meta assessment.

**Expected:** Capture/viewing alone does not send an image to Meta. Consent is required for that exact capture. The provider receives one JPEG and a fixed assessment prompt, not credentials, printer identifiers, customer text, prices or the stream URL. The UI shows capture time and model/provider for a successful result.

### T22 - Visual outcome and separate physical inspection

**Needs:** T21 and live vision access. Optional controlled empty/occupied scenes must be arranged manually on an idle printer by its operator.

**Steps:** Review the result against the actual scene. Where available, test empty, occupied and poor-view cases separately. For every case, inspect physically before recording an empty-bed observation. Clear the bed if necessary; never assert empty when it is not.

**Expected:** The model returns Appears empty, Object or print detected, or Uncertain with constrained reasons. Unclear visibility should not be treated as reliable empty proof. A model error is recorded as a test finding, not rationalized as success. Physical confirmation remains a separate operator action; current unconfirmed visual evidence blocks final readiness review. No price, reservation or print execution changes occur.

### T23 - Image expiry and replacement

**Needs:** local capture; Meta optional.

**Steps:** Capture an image and let sixty seconds pass, or capture a replacement before assessing the first. Revisit any earlier assessment and attempt confirmation after expiry.

**Expected:** The old image/assessment is stale and cannot be assessed/confirmed as current. Late model responses are rejected. Re-capture for a new assessment. Images are not persisted as reports; local metadata may remain. Restarting the server invalidates in-memory evidence too.

### T24 - Future-slot interpretation

**Needs:** comparison and optional bed check.

**Steps:** Inspect a current bed assessment alongside a future scheduling option.

**Expected:** The UI treats the image as current visual advice, not a forecast that the future slot is clear. It does not automatically select a printer or reserve it. Scheduling compatibility, deadline, capacity and approval requirements remain in force. Recheck near execution.

### T25 - Execution readiness and manual fallback

**Needs:** scheduled native-slicer-backed test job on the intended printer.

**Steps:** Check Reserved printer, Manual/Assisted policy, quote evidence, outages, telemetry and visual-review blockers. Complete valid physical confirmations and record readiness. Wait for relevant evidence or the ten-minute review period to expire.

**Expected:** Incomplete checks stay blocked. Configured assisted telemetry must be fresh. Model advice alone never approves readiness. Expired/changed evidence invalidates the review. Without current visual evidence, the labelled manual physical checklist remains available. Neither mode sends a print-start command; automatic execution is unavailable.

## D. Failure paths and privacy

### T26 - Provider unavailable

**Needs:** an isolated workspace with intentionally unavailable test credentials/provider, or automated mocks. Do not overwrite production credentials for a test.

**Steps:** Attempt an advice or bed-assessment request in that isolated setup.

**Expected:** A clear error/manual-review path, no fabricated result and no commitment changes. Never paste the failed credential or raw request headers into a report.

### T27 - Dependency or profile unavailable

**Needs:** a test setup without the optional native slicer/profile or printer connector.

**Steps:** Inspect its relevant controls and try an eligible available fallback.

**Expected:** Missing native/hardware support is explicit. Manual estimates stay labelled and do not unlock protected native/physical flows. Mark the optional test BLOCKED rather than inventing a result.

### T28 - Public evidence hygiene

**Steps:** Review the proposed report and any files intended for publication. Do not stage private evidence merely to run a scanner.

**Expected:** No API keys, LAN access code, serial/IP connection details, shop costs/rates, imported settings, private model files, certificate files, camera images or raw private reports enter a public commit. `scripts/check_public_files.py` can scan deliberately staged public files without printing secret values. An empty staged set is not proof that all local files are safe.

## Automated regression commands

Run in an installed development environment from the repository root. The standard suite uses isolated synthetic data and mocks for external model/device calls. Optional native slicing is explicitly opt-in; it does not physically print.

```powershell
$env:RUN_LIVE_SLICER = '0'
& .venv/Scripts/python.exe -m pytest backend/tests -q
pnpm --dir frontend build
```

Use a new PowerShell terminal so the opt-out setting is confined to that test session. Do not enable optional live integrations as a substitute for configuring and reviewing their prerequisites.

Focused camera/bed/approval checks:

```powershell
& .venv/Scripts/python.exe -m pytest backend/tests/test_bed_check.py backend/tests/test_printer_view.py backend/tests/test_printer_connector.py backend/tests/test_execution.py -q
```

At the time the visual-bed feature was added, the complete suite passed **205 tests with 2 optional tests skipped**, and the frontend build passed. That is a historical baseline, not an assertion about a new checkout or about the manual cases above. Live vision was checked with a synthetic image; camera capture and no-consent blocking were checked locally. Actual bed-detection accuracy and physical light switching require their own operator tests.

## Results template

Keep the completed report in an ignored local directory such as `output/user-tests/`. The blank template below is safe to copy; populated reports can contain private information.

```text
Run date/time/timezone:
Tester:
Commit:
Workspace URL / isolated database label:
Browser / operating system:
Meta provider/model (no key):
Available profiles (names only; no imported files):
Physical tests authorized: yes / no
Synthetic pricing used: yes / no / not applicable

Case ID:
Status: NOT RUN / PASS / FAIL / BLOCKED
Prerequisites present:
Steps performed:
Expected result:
Observed result:
Commitment baseline unchanged where required: yes / no / not applicable
Local evidence reference (do not attach private artifacts publicly):
Issue summary with sensitive details removed:

Final active test reservations / simulated outages reviewed:
Camera viewer stopped:
Original light state restored, if changed:
Test server stopped:
```

For each failure, record the case ID, reproduction steps, expected/actual behavior and a sanitized message. Include a screenshot only after checking it for private information. Use [the architecture guide](ARCHITECTURE.md) to identify the affected component; never include `.env` contents in a bug report.
