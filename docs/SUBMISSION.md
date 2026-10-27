# Print3DFlow — hackathon submission description

## Copy-ready description

Print3DFlow is a manufacturing workflow assistant for small 3D printing shops, built for the Indie track. It connects customer requests, slice-backed quotes, compatible printer scheduling, and recovery from printer outages in one reviewable workflow.

Meta's Muse Spark model is a real runtime component in two places. First, it extracts structured job requirements from customer text and identifies missing information for operator review. Second, after a simulated pre-start outage, it recommends among verified recovery options and selects reasons explaining their tradeoffs, including deadline feasibility, completion delay, printer continuity, and unchanged pricing when supported by the results.

The application computes scheduling options and validates Meta's structured response against those facts before rendering the explanation. Meta cannot invent a slot, change a price, or alter a reservation. The operator reviews the recommendation and separately approves recovery; only that approval commits the replacement and releases the original reservation. Changed capacity makes the explanation stale and requires a fresh plan.

The demonstration combines real Meta inference with native Bambu Studio slicing using an operator-supplied X2D profile, itemized pricing, and an auditable reservation workflow. Outage injection is simulated, customer updates remain drafts, and no physical printer is controlled. The current prototype runs locally and supports pre-start recovery.

Additional live end-to-end testing verified the A1 and A1 mini workflows in an isolated database: Meta intake, native slicing, quotes using the configured rate card, matching-printer scheduling, and Meta-assisted outage recovery. All 31 checks passed across the two profiles. Scheduling proposals, Meta advice, and option selection left reservations unchanged; separate operator approval committed recovery atomically, preserved the approved quote, and was idempotent. Imported settings, business rates, quote totals, and raw private reports are excluded from the public repository.

Repository: https://github.com/scrooksjr/Print3DFlow

## Stage One verification pointers

- **Video 0:18–0:50:** real Meta intake request, returned draft, missing-units clarification, and operator review.
- **Video 1:55–2:15:** request a Meta recovery explanation and show its model attribution and verified tradeoffs.
- **Video 2:15–2:40:** show the original reservation unchanged before the separate Approve recovery action, then show the committed replacement.
- **Code:** `backend/integrations.py` performs intake inference; `backend/recovery.py` performs recovery inference and grounded-response validation. Both call the Meta Model API. `backend/main.py` implements the API and approval transaction boundary.
- **A1/A1 mini verification:** the README summarizes the additional live run and sample slicer estimates. Use `python -m scripts.import_a1_profile 'C:/path/to/your-reference.3mf'` with your own supported A1 or A1 mini PLA/0.4 mm project, restart, and repeat the judge verification sequence in a fresh rehearsal workspace. Each profile was tested on its matching printer; cross-printer rerouting is not claimed.
- **Reproduce:** follow the README's judge verification sequence and `docs/SETUP.md`, using your own Meta key/access. No credentials, customer files, private rates, or imported shop profiles are distributed. Native slicing requires a separately installed compatible Bambu Studio; reproduction of imported-profile results requires your own supported project and local rate card.
- **Evidence boundary:** automated provider mocks verify safeguards, not live inference. Configuration status alone is not live-call proof. The recorded demonstration should show actual successful responses; manual fallback must not be presented as Meta output.

## Submission preparation

Add the final three-minute video URL in the submission platform. The timestamps above are recording targets; align them to the final edit before submitting. Verify that the public repository contains the demonstrated integration code and that both links open while logged out. Do not upload local credentials, private test reports, or shop profile artifacts as evidence.
