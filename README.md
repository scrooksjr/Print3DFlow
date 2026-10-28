# Print3DFlow

Manufacturing workflow assistant for **Print3DStore**, built for the Meta Global AI Developer Hackathon's Indie track.

Print3DFlow connects a customer request to a reviewed quote, a compatible printer reservation, and recovery when a printer becomes unavailable.

## Workflow

1. **Meta-assisted intake:** Muse Spark extracts a structured draft and asks about missing requirements. The operator reviews before creating a job.
2. **Geometry and quoting:** validate an STL, confirm units, preview the actual mesh, and obtain native Bambu Studio slice estimates or explicitly labeled manual estimates.
3. **Shop pricing:** versioned rate cards support material cost, waste policy, machine-time allowance, setup, markup, minimum charges, and reviewed support surcharges.
4. **Scheduling:** propose compatible capacity and commit reservations atomically after approval.
5. **Exception recovery:** inject a simulated pre-start outage, ask Meta to compare verified scheduling options, choose a proposal, and approve atomic replacement while preserving the quote.
6. **Cross-printer quote adviser:** independently slice selected imported A1, A1 mini and X2D profiles, calculate candidate quotes, and check each printer's schedule. After permission to share quote totals, Meta compares verified tradeoffs. You select an option and explicitly approve its exact price and reservation before anything is committed.

Meta handles intake and selects evidence-backed recovery reasons and a recommended option. The server validates every selected reason and renders text from verified facts; freeform model facts are not displayed. Quote arithmetic, scheduling constraints, recovery search, and the customer-update template remain deterministic application logic. No messages or printer commands are sent.

## Meta's runtime role — judge verification

Meta is part of the running product in **two operator-triggered workflows**, using `muse-spark-1.3` by default through the Meta Model API. These are real backend inference requests, not static demo responses.

| Runtime feature | Meta contributes | Application verifies and controls |
| --- | --- | --- |
| Job intake | Extracts structured requirements from customer text and identifies missing information. | Validates the response schema; the operator resolves missing fields and reviews before creating a job. |
| Outage recovery adviser | Recommends among supplied feasible options and selects relevant tradeoff reasons. | Computes compatible slots, validates every selected reason against scheduling facts, and renders factual explanations. Only explicit operator approval changes reservations. |

### Verify in the running app

1. Follow the setup below with your own Meta credentials. A configured-key indicator alone does **not** establish a successful inference call.
2. Open **New print job**, enter a synthetic PLA request with a future deadline but omit units, and click **Extract draft with Meta**. Inspect the returned draft and clarification, resolve units, and review before creating the job. Clarification wording may vary.
3. Upload `samples/demo-block.stl`, obtain a quote with a supported locally installed slicer/profile (or an explicitly labeled manual estimate), then approve a compatible reservation. Keep the deadline comfortably beyond the simulated outage and perform recovery before the reservation starts.
4. Click **Simulate printer outage**, **Propose recovery**, then **Explain recovery options with Meta**. Inspect the model attribution, recommendation, and actual verified reasons. With one compatible printer, expect a later slot on that printer rather than invented alternatives.
5. Pause on **APPROVAL REQUIRED** and **Selected proposal · awaiting approval**: the original reservation remains recorded. Selecting another option changes only the pending proposal. Click **Approve recovery** separately, then inspect the replacement and audit history.

### Inspect the integration

- Intake: [`backend/integrations.py`](backend/integrations.py), `extract_intake`; API: `POST /api/intake/drafts`.
- Recovery: [`backend/recovery.py`](backend/recovery.py); APIs: `POST /api/proposals/{proposal_id}/explanation` and `GET` on the same path. Responses identify `source: meta_model_api`, the model, and a versioned scheduling snapshot.
- Approval boundary: [`backend/main.py`](backend/main.py), `select_recovery_option` and `approve`. Capacity changes invalidate explanations; approval rechecks current state.
- Automated safeguards: [`test_integrations.py`](backend/tests/test_integrations.py) and [`test_recovery_explanations.py`](backend/tests/test_recovery_explanations.py). Provider mocks test validation and failure handling; they are not proof of a live call. Verify real inference through the app using your own key.

Both integrations call `https://api.meta.ai/v1/chat/completions`. Provider failures are reported rather than replaced with fabricated AI output. Successful recovery explanations may be reused for the same unchanged snapshot; use a fresh proposal/run to observe a new request. Manual fallback is labeled and does not demonstrate Meta inference.

See the [three-minute demo sequence](docs/DEMO.md), [integration details](docs/SETUP.md), and [submission description](docs/SUBMISSION.md). The recorded X2D demonstration uses locally imported operator settings; private profiles and credentials are not included in this repository.

## Quick start

Requires Python 3.12+, Node 20.19+ or 22.12+, and pnpm. Native slicing additionally requires a separately installed compatible Bambu Studio CLI. No third-party slicer binaries or private printer profiles are distributed here.

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
./scripts/start.ps1
```

Open [the local app](http://127.0.0.1:8765/) or [API documentation](http://127.0.0.1:8765/docs). On macOS/Linux use `.venv/bin/python` and `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765` instead of the PowerShell launcher. Verify native CLI compatibility on the target OS before enabling slicing.

The app starts with a synthetic rate card and two virtual printers. All bundled rates are **demo/test values**, not a real shop's prices. Use **Shop rates** to save your own local rate card; new quotes retain a snapshot and older quotes stay unchanged.

Without a Meta key or slicer, manual intake and manual estimate mode remain usable. See [integration setup](docs/SETUP.md) for live integrations and [the demo guide](docs/DEMO.md) for a short walkthrough.

## Meta credentials

Edit the ignored `.env` file locally:

```dotenv
META_API_KEY=your-local-key
META_MODEL=muse-spark-1.3
SHOP_TIMEZONE=America/New_York
```

Use a Meta Model API key with access and credits for the configured Standard-mode model. Restart after editing. Do not put keys in the frontend, screenshots, issues, commits, or public reports. `.env.example` contains placeholders only.

For intake, the request text, date/time context and validated file format, dimensions, embedded units and assigned material/color suggestions (when a model is attached) are sent when the operator requests extraction. Filenames and model contents stay local. Vague sizes such as “medium” prompt an exact-dimension or original-size question; no resizing is performed. For recovery, Meta receives verified option facts and allowed reason codes; customer text, printer names, meshes, price amounts, and private rate cards are excluded from that request. Uploaded meshes remain local. Responses are validated before use; provider failures do not silently become fabricated AI results.

## Printer configuration

### Requested filament types

New jobs can request PLA, PETG, ABS, ASA or TPU, with color stored separately. Meta preserves the requested material; it never silently substitutes PLA. The current verified slicing and pricing path is PLA. Other requests are recorded as `awaiting_material_profile`; manual quotes, native slicing and cross-printer comparisons remain blocked until matching material profiles and rates are configured.

`profiles/materials.example.json` is a setup checklist, not usable slicer presets. For PETG, ABS, ASA and TPU, provide a saved Bambu Studio reference project for each compatible printer/nozzle combination and its material cost per kg. Printer compatibility, temperatures, cooling, enclosure needs and feed paths must come from verified settings; the PLA profiles are not cloned or relabeled. No support for an unconfigured combination is implied. `/api/filaments` reports request types and configuration status.


### STL and 3MF job uploads

#### Four-color MVP inspection

Saved colors and assignments are shown beside the requested-color field. Assigned RGB shades are summarized with broad color names (for example, Black / White / Yellow / Green); these are editable descriptions, not manufacturer shade matches. Exact saved hex values remain in the palette. A complete assigned-slot color set prefills that editable field; unresolved paint or missing mappings do not. Four palette entries alone do not imply four-color printing.

The requested filament selector is suggested from **assigned 3MF slots only** when all referenced slots agree on one catalog material. Unused saved slots do not affect it. Missing, mixed, unsupported or unresolved assignments leave it unselected and ask for clarification. The field remains editable; changing a Meta-extracted material requires an explicit override confirmation before creating the job. This changes the request, not the uploaded color/tool mappings, and does not remove quote blocks. STL files leave the material unselected for user entry; user-written request text can still be extracted by Meta.

3MF uploads show saved filament colors/materials, known object/part slot assignments and standard face-property references. Saved slots are listed separately from slots actually assigned to printable geometry; unused palette entries do not prove multicolor use. Encoded paint is detected but not decoded into verified physical mappings. The MVP limit is four assigned colors/filament slots; projects exceeding it are flagged and blocked.

Multicolor, painted, textured or unresolved color/material assignments block **all** quoting paths, including manual estimates, native slicing and cross-printer comparisons. No verification override is provided yet: mapping and multicolor slicer-result verification must be implemented before enabling these quotes. Existing approval checks cannot bypass the block. Previously uploaded 3MFs without color inspection must be uploaded again before quoting. Single-filament projects with extra unused saved slots remain eligible when assignments are unambiguous.

The slicing input remains a normalized geometry-only STL. A separate preview renders supported saved component colors for new uploads as file intent; opaque paint is not decoded and no saved mappings are silently applied to a registered printer profile. STL files do not provide this 3MF assignment inspection. Model geometry and full palettes stay local. On intake extraction, Meta also receives the complete assigned-slot color suggestion, when known, so it can avoid asking for a color already established by the file. Unused palette slots are not sent as assigned colors.

Automatic repair is not offered. If a model fails geometry validation, repair it externally and upload the corrected STL or 3MF. No geometry is silently changed.

Creating a new job requires a validated model file. The UI stages the upload through `POST /api/model-uploads`, then passes the returned single-use `model_upload_id` to `POST /api/jobs`. Missing, expired, consumed or invalid uploads cannot create a job. Staged uploads expire after one hour; Meta extraction alone remains a draft and creates no job.

Job uploads accept `.stl` and supported `.3mf` geometry (up to 64 MiB input size and 1,000,000 triangles). STL units require operator confirmation. 3MF embedded units and component/build transforms are converted into millimeter geometry for preview, quoting and independent printer slices. A multi-object build is treated as one assembly; quantity repeats the complete assembly, not each object separately. Review the preview and resulting dimensions before approval.

Uploaded 3MF printer/process settings, G-code and scripts are ignored; only the registered, operator-reviewed profile drives slicing. The app retains normalized STL geometry plus source provenance, not the original archive. Modifiers, cyclic or external references, unsupported geometry and archives exceeding inspection limits require manual review. Saving printer settings as a trusted local profile remains a separate importer workflow.

### Cross-printer comparisons

After uploading a mesh and confirming units, open **Cross-printer quote adviser**. Select imported profiles, review their saved settings, and enter a reviewed support share separately for each profile when known. Unknown support share can block approval under the configured support-surcharge policy; do not guess zero. The optional support surcharge is not applied in this comparison workflow.

Choose **Slice and compare selected printers**. Each profile receives its own native slice, candidate quote, and earliest compatible schedule; X2D estimates are never reused for an A1 or A1 mini. Parts exceeding a selected envelope must be deselected, and failed slices are excluded without fabricated estimates. Quantity uses sequential parts, not batch packing. Different saved presets can affect quality as well as price/time, so review them before choosing.

To request Meta advice, first permit sharing the displayed quote totals, price differences, slice estimates and scheduling facts. Rate-card details, customer text, meshes and printer names are excluded from that provider request. **Compare verified options with Meta** validates option coverage, recommendations and reason codes, then renders explanations from facts. Manual review remains possible if Meta is unavailable.

Selecting a radio option changes only the local UI selection. Check the explicit price/reservation approval box, then choose **Approve price & reservation** to commit. The backend requires the exact option, total and currency and rechecks job, rates, profiles, quote expiry and capacity. Stale results require a fresh comparison. For a simulated pre-start outage, the same action atomically replaces the old reservation and applies the newly approved quote; the historical quote is retained. This differs from same-profile recovery, which preserves its existing quote.

APIs: `POST /api/jobs/{job_id}/comparisons`, `GET /api/jobs/{job_id}/comparisons`, `POST /api/comparisons/{comparison_id}/explanation` (requires `consent_to_send_quote_totals: true`), and `POST /api/comparisons/{comparison_id}/approve`. See `backend/comparison.py` and `backend/tests/test_comparison.py`.

The public sample registry is `profiles/registry.example.json`. The application uses it when the ignored local `profiles/registry.json` does not exist. The sample resolves separately installed Bambu A1 system presets and is **not calibrated**.

For your own **A1 or A1 mini**, save a single-part, single-plate PLA project with a 0.4 mm nozzle in Bambu Studio, then run:

```powershell
& .venv/Scripts/python.exe -m scripts.import_a1_profile 'C:/path/to/your-reference.3mf'
```

The importer identifies the model, validates its build volume, preserves the filament-slot mapping, and registers separate local printer capacity. It replaces source geometry with the owned sample block and keeps imported settings in ignored local files. Restart the app and verify a native sample slice against Bambu Studio before using estimates. This adds support for importing profiles; private shop profiles are not bundled. A2L is not configured.

For supported X2D projects, import your own single-part, PLA, dual-0.4-mm-nozzle project from the repository root:

```powershell
& .venv/Scripts/python.exe -m scripts.import_x2d_profile 'C:/path/to/your-reference.3mf'
```

This writes only local ignored profile data and a local registry. The original project geometry and ancillary assets are not carried into quoting. The X2D path preserves the project's filament-slot/tool mappings and accepts a quote only after the native report confirms the supported single-slot behavior. General multicolor or arbitrary tool-change workflows are outside the current MVP.

## Verification

### Verified production planner and approval workflow

The latest isolated planner run passed **74 browser and API checks**, with **four live Meta planner runs** and native Bambu slices for **A1, A1 mini and X2D**. It used the owned sample block and synthetic demo pricing. These checks include overlapping assertions across the workflow, not 74 independent scenarios:

- Meta requested both allowed read tools; the browser displayed the verified trail, a supported option recommendation and the separate approval requirement. Missing comparisons were reported rather than invented.
- Planning and browser-only option selection preserved the selected baseline quote and reservations. Tool results excluded customer and financial fields.
- Changing a requirement marked the previous plan stale, hid its recommendation, retained a historical trail and prevented stale comparison approval. Replanning requested a fresh comparison; after new native results, it recommended review of a verified option.
- A new instruction to refresh stale comparison evidence remains usable: only advice based on a verified comparison retains its comparison reference. A regression test covers this stale-refresh correction.
- Unconfirmed approval, incorrect totals and incorrect currencies were rejected without changing commitments. Only a scripted operator approval matching the exact option, total and currency selected its quote and created one synthetic reservation. Repeating that approval was idempotent, and the resulting state change invalidated prior planner advice.

The separate regression suite passed **156 tests**, with two optional tests skipped. No physical printer was contacted; main-workspace jobs and private rates were untouched. The synthetic reservation was created only in the isolated test database. Models, costs, credentials, imported settings, screenshots, test scripts and raw reports remain private; only this summary is published.

### Verified finish selection and additional-cost safeguards

An earlier isolated finish workflow passed **43 checks: 34 API assertions and 9 browser observations**, using the owned sample block, synthetic demo pricing and **four live Meta intake calls** (one per finish option). The checks covered overlapping behavior across As-printed, Sanding, Painting and Other / discuss with shop:

- Each selected finish was retained by Meta without another generic finish clarification and persisted on reviewed job submission.
- As-printed produced a synthetic print-only quote. No reservation was committed.
- Sanding, Painting and Other entered `awaiting_finish_review`. Each displayed the additional-cost notice and the requirement for shop review and a separately approved finishing price; quote and scheduling controls were hidden.
- Manual quotes, native slice quotes and cross-printer comparisons each rejected every custom-finishing job with **HTTP 422**. Scheduling proposals returned **HTTP 409**. No custom-finishing quotes or reservations were created.

This run verified request capture, live intake and safeguards, not custom-finishing pricing or fulfillment. A finishing-charge approval workflow is not implemented yet; no surcharge was invented. No physical printer was contacted, private shop rates were not loaded, and main-workspace jobs were unchanged. Only this summary is public; credentials, material costs, imported settings, model files, screenshots and raw reports remain excluded.

### Verified four-color keychain workflow

A subsequent isolated run passed **13 browser and API checks** using an original four-color keychain 3MF rather than a synthetic block. It verified:

- The geometry preview showed the keychain and eyelet; the served mesh retained **9,096 triangles** and measured **40 x 49 x 3 mm**.
- All four filament slots were assigned. The palette displayed black, white, yellow (`#FFE000`) and green (`#75B52A`); the editable requested-color field autofilled those assigned colors and retained them on submission.
- **PLA** autofilled from the assigned slots and persisted on the created test job.
- The browser displayed the multicolor verification block and hid quote controls. Manual estimates, native slice quotes and cross-printer comparisons each rejected the unverified multicolor job with **HTTP 422**.
- No quotes or reservations were created. The source file and main workspace were unchanged, and no physical printer was contacted.

These checks include overlapping UI observations and API assertions. At the time of this run, the preview used a single display color and saved colors appeared only in the palette. The newer component-color preview is described below. This run did not call Meta, perform a successful multicolor slice or verify physical print accuracy. It used an isolated test workspace with default demo pricing. The original model, screenshots and raw report remain private; only this summary is published.

### Verified assigned-color autofill and palette display

An earlier isolated end-to-end run passed **17 checks** across browser interactions and API assertions, using owned synthetic 3MF fixtures, synthetic demo pricing and **two live Meta intake calls**. It verified:

- A four-entry saved palette with only slot 2 assigned autofilled **Green** only. All four entries remained visible, with assigned and unused slots distinguished.
- Meta retained the assigned color without asking a redundant color question. A manual change to **Purple** survived re-extraction and was saved when the reviewed job was submitted.
- A model assigned to all four slots autofilled **Red / Green / Blue / White**, displayed its palette and assignments, and retained those colors on job creation.
- Missing assignments and unresolved encoded paint produced no invented color suggestion.
- The browser displayed the multicolor verification block and hid quoting controls. Manual quotes, native slice quotes and cross-printer comparisons each rejected the unverified multicolor job with HTTP 422.
- No quotes or reservations were created. Main-workspace jobs were unchanged, and no physical printer was contacted.

These 17 checks include UI observations and API assertions of overlapping workflow behavior; they are not 17 independent scenarios. This run verified intake and quote safeguards, not successful multicolor slicing or physical print accuracy. Private shop rates were not loaded, and model archives stayed local. Only this summary is published; credentials, material costs, imported settings, model files and raw reports remain excluded.

### Verified filament autofill and review workflows

An earlier isolated live workflow run passed **45 checks** using synthetic models and demo pricing, real Meta intake calls, actual isolated geometry workers and a native A1 mini slice. The run verified:

- 3MF material suggestions use assigned slots only; unused saved materials do not change the suggestion.
- Changing an extracted PLA request to PETG is rejected without explicit override confirmation. A confirmed edit records PETG as awaiting configuration rather than substituting PLA.
- STL intake leaves unstated material and units unresolved. Blank material is rejected; reviewed manual PLA/color/units entry produces a native quote without reserving capacity.
- Missing and conflicting assignments ask for clarification without inventing PLA. Selecting PLA afterward does not bypass unresolved mapping safeguards.
- Four-color PLA may suggest a common polymer, but multicolor quoting remains blocked until physical mappings and multicolor slicer results are verified.
- PETG, ABS, ASA and TPU remain blocked across manual quotes, native slice quotes and cross-printer comparisons until material-specific profiles and rates are configured.

No test committed a reservation, contacted a physical printer or modified main-workspace jobs. Material costs, credentials, imported settings, user model files and raw reports remain private; only this verification summary is published. These were API workflow checks, not a browser automation run. The latest separate regression suite passed **135 tests**, with two optional native-slicing tests skipped; provider mocks in that suite are not live inference evidence.

### Verified STL and 3MF submissions

An earlier live end-to-end run passed **47 checks: 23 for STL and 24 for 3MF**, in separate isolated databases using synthetic geometry and invented demo pricing. Both used real `muse-spark-1.3` intake and comparison inference plus native Bambu Studio slices for A1, A1 mini and X2D. The additional 3MF check verified that embedded centimeter units normalize to the expected millimeter dimensions.

Both workflows verified required model submission, no empty job during staging, independently priced/scheduled candidates, and explicit consent before sending comparison totals to Meta. Initial and recovery advice left the current job quote and reservations unchanged. An alternative had its own slice and a different quote; incorrect-price acknowledgements and unconfirmed approvals were rejected without changing commitments. Only exact-price/reservation approval atomically switched the simulated outage job from X2D to A1 mini. Repeating that approval was idempotent.

These earlier live runs used synthetic prices, not private shop-rate-derived totals. No main-workspace jobs were changed and no physical printer was contacted. Only this summary is public; raw reports, imported profiles, API credentials and private rate cards remain excluded. At that milestone, the automated regression run passed **97 tests**, with two optional native-slicing tests skipped; mocked provider tests are distinct from live inference evidence.

To repeat the workflow, follow the judge verification and cross-printer instructions above in a fresh rehearsal with synthetic rates and your own Meta access/imported printer profiles. Select the required STL or supported 3MF file in the new-job form. For 3MF, review the normalized dimensions and assembly interpretation; embedded manufacturing settings do not override the selected printer profiles.

### Verified A1 and A1 mini workflows

A local end-to-end run passed **31 checks across A1 and A1 mini**, using real `muse-spark-1.3` intake and recovery inference, native Bambu Studio slicing, and an isolated database with the operator's configured rate card. Each workflow validated the owned `samples/demo-block.stl`, calculated a quote against the active rate-card snapshot, proposed matching printer capacity, and recovered from a simulated pre-start outage.

| Imported profile | Sample filament estimate | Sample total slicer time |
| --- | --- | --- |
| A1 / PLA / 0.4 mm | 2.540 g | 15m52s |
| A1 mini / PLA / 0.4 mm | 2.548 g | 15m31s |

These are slicer estimates for the sample and the locally imported settings, not measured physical-print results or universal estimates for these printers. Exact results depend on your settings and slicer version. No shop rates, quote totals, imported settings, or private test reports are published here.

The live checks confirmed that scheduling proposals, Meta recovery advice, and operator option selection **do not change reservations**. Explicit initial approval creates the reservation; separate recovery approval atomically replaces it and releases the original. Repeating the recovery approval is idempotent, and the approved quote remains unchanged. Each tested profile stayed on its matching printer; this does not establish cross-printer rerouting with interchangeable estimates. No physical printer was contacted and the main workspace was unchanged.

To reproduce, import your own A1 or A1 mini project with `scripts.import_a1_profile`, restart the app, and follow the judge verification sequence above in a fresh rehearsal workspace. Use your own Meta credentials and local rate card. The 31-check result is a summary of a local live run; the public automated suite below uses mocked provider responses and does not rerun this live experiment.

### Automated checks

```powershell
& .venv/Scripts/python.exe -m pytest -q
pnpm --dir frontend build
```

The default suite uses synthetic fixtures and mocked provider responses. Native slicing tests are opt-in:

```powershell
$env:RUN_LIVE_SLICER='1'
& .venv/Scripts/python.exe -m pytest -q
```

The X2D test also needs your locally imported profile. `scripts/e2e_live.py` exercises real Meta intake, local slicing, configured pricing, scheduling, and simulated recovery against a running app; it creates labeled local test records and uses current local rates. Do not run it against real production capacity. Local reports are ignored and should be reviewed before sharing.

## Architecture and limits

React/TypeScript/Vite frontend; FastAPI/SQLAlchemy backend; SQLite by default, with a configurable PostgreSQL connection; local artifact storage; and background slicing tasks. All capacity mutations pass through a serialized shop transaction. The demo uses one API process, not a distributed worker queue.

Model inspection and imported-profile project generation run one at a time in a separate process with a 90-second deadline and 2 GiB OS memory limit. 3MF archives are limited to 256 entries, 128 MiB total expanded data and 96 MiB per part; geometry is capped at 1,500,000 vertices per mesh. Uploads stream through temporary disk buffers that are removed after completion or failure. Concurrent processing returns a retry response. No model is automatically simplified. Native Bambu slicing retains its separate 120-second timeout.

This is an **unauthenticated loopback-only operator prototype**. It does not synchronize with a printer's real queue, provide customer authorization, send notifications, or control machines. The geometry worker has memory and time bounds, but it is not a filesystem/network security sandbox. Untrusted public hosting still requires stronger isolation and aggregate storage quotas. Recorded comparisons establish agreement with slicer estimates, not physical-print accuracy or production reliability. PostgreSQL integration verification and production hardening remain work ahead.

## Public and local files

- **Public:** application code, synthetic tests, generated sample STL, placeholder environment configuration, sample registry, and generic setup documentation.
- **Local only:** API keys, databases, jobs, rate cards, imported printer settings, raw outputs, screenshots, customer files, internal plans, and shop-specific demo scripts.

Run `python scripts/check_public_files.py` after staging changes to check the proposed commit for excluded paths and known local credential values. It reports filenames and failure categories, never matching credential contents. It is a safeguard, not permission to publish unreviewed customer data.

### Color-aware component preview

New supported Bambu 3MF uploads preserve complete object/part filament-color assignments in a separate, bounded GLB preview generated in the isolated model worker. Rotate the preview to inspect both sides. Rendering uses saved component colors for visual review only; the normalized STL used for quoting is unchanged. Unsupported or incomplete mappings and encoded paint fall back to a labeled geometry-only view. Existing uploads need the original 3MF re-uploaded to generate a color preview. No multicolor quote gate is relaxed, and STL previews remain single-color. Preview artifacts stay in ignored local storage.

### Requested finish

New-job intake offers As-printed (no additional finishing), Sanding, Painting, and Other / discuss with shop. Select a finish before Meta extraction to avoid a repeated generic finish clarification; conflicting request text still requires resolution. Custom finishing has an additional cost. Requests are recorded, but non-as-printed jobs cannot receive automatic quotes or scheduling until the shop reviews the work and separately approves its price. The MVP does not yet provide a finishing-charge approval workflow. No finishing surcharge is invented or silently included in the print-only estimate.

### Meta-assisted production planner

The job workspace includes **Plan with Meta**, a bounded, read-only Meta Model API tool-calling loop. After explicit consent, Meta requests `check_job_readiness` and `read_verified_comparison`, receives their verified results, and submits a structured recommendation. The visible tool trail shows the requested checks and returned facts. The server renders explanations from validated evidence IDs; freeform model claims are not displayed.

The first version reads existing independent slice/schedule comparisons rather than starting slices automatically. Missing or stale results direct the operator to review profiles and run a fresh comparison. Custom finishing, unresolved/multicolor assignments, unsupported material setup and missing units remain blockers. A recommended option must be present in a fresh verified comparison, meet the deadline and have no unresolved support review. Expired or changed jobs, quotes, profiles, rates or capacity make the plan stale and suppress its recommendation. Planning is not approval; existing exact-price and reservation approval routes remain the only way to commit a comparison option.

Only blocker codes, profile IDs and non-price slice/schedule facts are sent to Meta for planning. Customer text, meshes, filenames, printer names, rate cards, prices and price-derived reason codes are excluded. The planner has no quote-creation, reservation, messaging, shell or printer-control tools. Unexpected tools, malformed results, fabricated evidence and provider failures fail closed. The local planner record and audit event are saved, but quotes, selected prices and reservations remain unchanged.
