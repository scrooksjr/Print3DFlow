# Print3DFlow

Manufacturing workflow assistant for **Print3DStore**, built for the Meta Global AI Developer Hackathon's Indie track.

Print3DFlow connects a customer request to a reviewed quote, a compatible printer reservation, and recovery when a printer becomes unavailable.

## Workflow

1. **Meta-assisted intake:** Muse Spark extracts a structured draft and asks about missing requirements. The operator reviews before creating a job.
2. **Geometry and quoting:** validate an STL, confirm units, preview the actual mesh, and obtain native Bambu Studio slice estimates or explicitly labeled manual estimates.
3. **Shop pricing:** versioned rate cards support material cost, waste policy, machine-time allowance, setup, markup, minimum charges, and reviewed support surcharges.
4. **Scheduling:** propose compatible capacity and commit reservations atomically after approval.
5. **Exception recovery:** inject a simulated pre-start outage, ask Meta to compare verified scheduling options, choose a proposal, and approve atomic replacement while preserving the quote.

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

For intake, only the request text and date/time context are sent when the operator requests extraction. For recovery, Meta receives verified option facts and allowed reason codes; customer text, printer names, meshes, price amounts, and private rate cards are excluded from that request. Uploaded meshes remain local. Responses are validated before use; provider failures do not silently become fabricated AI results.

## Printer configuration

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

This is an **unauthenticated loopback-only operator prototype**. It does not synchronize with a printer's real queue, provide customer authorization, send notifications, or control machines. Mesh parsing still needs stronger isolation before accepting untrusted public uploads. A subprocess timeout is not an OS memory/disk sandbox. Recorded comparisons establish agreement with slicer estimates, not physical-print accuracy or production reliability. PostgreSQL integration verification and production hardening remain work ahead.

## Public and local files

- **Public:** application code, synthetic tests, generated sample STL, placeholder environment configuration, sample registry, and generic setup documentation.
- **Local only:** API keys, databases, jobs, rate cards, imported printer settings, raw outputs, screenshots, customer files, internal plans, and shop-specific demo scripts.

Run `python scripts/check_public_files.py` after staging changes to check the proposed commit for excluded paths and known local credential values. It reports filenames and failure categories, never matching credential contents. It is a safeguard, not permission to publish unreviewed customer data.
