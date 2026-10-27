# Print3DFlow

Manufacturing workflow assistant for **Print3DStore**, built for the Meta Global AI Developer Hackathon's Indie track.

Print3DFlow connects a customer request to a reviewed quote, a compatible printer reservation, and recovery when a printer becomes unavailable.

## Workflow

1. **Meta-assisted intake:** Muse Spark extracts a structured draft and asks about missing requirements. The operator reviews before creating a job.
2. **Geometry and quoting:** validate an STL, confirm units, preview the actual mesh, and obtain native Bambu Studio slice estimates or explicitly labeled manual estimates.
3. **Shop pricing:** versioned rate cards support material cost, waste policy, machine-time allowance, setup, markup, minimum charges, and reviewed support surcharges.
4. **Scheduling:** propose compatible capacity and commit reservations atomically after approval.
5. **Exception recovery:** inject a simulated pre-start outage, review a replacement plan, and atomically replace the old reservation while preserving the quote.

Meta handles intake. Quote arithmetic, scheduling constraints, recovery search, and the customer-update template are deterministic application logic. No messages or printer commands are sent.

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

Only the request text and date/time context are sent to the official Meta endpoint when the operator requests extraction. Uploaded meshes remain local. The returned schema is validated before the draft can be reviewed; provider failures do not silently become fabricated AI results.

## Printer configuration

The public sample registry is `profiles/registry.example.json`. The application uses it when the ignored local `profiles/registry.json` does not exist. The sample resolves separately installed Bambu A1 system presets and is **not calibrated**.

For supported X2D projects, import your own single-part, PLA, dual-0.4-mm-nozzle project from the repository root:

```powershell
& .venv/Scripts/python.exe -m scripts.import_x2d_profile 'C:/path/to/your-reference.3mf'
```

This writes only local ignored profile data and a local registry. The original project geometry and ancillary assets are not carried into quoting. The X2D path preserves the project's filament-slot/tool mappings and accepts a quote only after the native report confirms the supported single-slot behavior. General multicolor or arbitrary tool-change workflows are outside the current MVP.

## Verification

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
