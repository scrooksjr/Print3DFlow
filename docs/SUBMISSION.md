# Print3DFlow — hackathon submission description

## Copy-ready description

Print3DFlow is a manufacturing workflow assistant for small 3D printing shops, built for the Indie track. It connects customer requests, slice-backed quotes, compatible printer scheduling, and recovery from printer outages in one reviewable workflow.

Meta's Muse Spark model powers job intake, grounded outage recovery advice, and a cross-printer quote adviser. It extracts structured requirements from customer text and identifies missing information for review. It also recommends among verified scheduling options and selects factual reasons explaining deadline, completion-time, printer-switch and pricing tradeoffs.

The application computes scheduling options and validates Meta's structured response against those facts before rendering the explanation. Meta cannot invent a slot, change a price, or alter a reservation. The operator reviews the recommendation and separately approves recovery; only that approval commits the replacement and releases the original reservation. Changed capacity makes the explanation stale and requires a fresh plan.

The cross-printer adviser independently slices the same mesh using imported A1, A1 mini and X2D settings, calculates a candidate quote for each, and checks each printer's schedule. It never reuses one printer's time estimate for another. The operator reviews the saved presets, which may differ, and explicitly permits sharing quote totals, price differences and scheduling facts with Meta; rate-card details, customer text and meshes remain local for this request. Meta's recommendation does not select or commit an option. The operator separately selects a proposal and approves its exact total, currency and reservation. In pre-start outage recovery, that approval can atomically switch printers and apply a new quote while retaining the historical quote. Stale inputs, late options and unresolved support review block approval.

The demonstration combines real Meta inference with native Bambu Studio slicing using an operator-supplied X2D profile, itemized pricing, and an auditable reservation workflow. Outage injection is simulated, customer updates remain drafts, and no physical printer is controlled. The current prototype runs locally and supports pre-start recovery.

Additional live end-to-end testing verified the A1 and A1 mini workflows in an isolated database: Meta intake, native slicing, quotes using the configured rate card, matching-printer scheduling, and Meta-assisted outage recovery. All 31 checks passed across the two profiles. Scheduling proposals, Meta advice, and option selection left reservations unchanged; separate operator approval committed recovery atomically, preserved the approved quote, and was idempotent. Imported settings, business rates, quote totals, and raw private reports are excluded from the public repository.

The cross-printer addition passed 17 live checks with real Meta inference, native slices for all three printers, and synthetic pricing. These included an explicitly approved X2D-to-A1-mini recovery with a changed quote and rejection of an incorrect price acknowledgement. Separate local-only checks verified all three candidate quotes against the private shop rate card without sending those totals to Meta. The regression suite passed 86 tests, with two optional native-slicing tests skipped. These checks establish prototype behavior, not physical-print accuracy or production reliability.

Repository: https://github.com/scrooksjr/Print3DFlow

## Stage One verification pointers

- **Video 0:18–0:50:** real Meta intake request, returned draft, missing-units clarification, and operator review.
- **Video 1:55–2:15:** request a Meta recovery explanation and show its model attribution and verified tradeoffs.
- **Video 2:15–2:40:** show the original reservation unchanged before the separate Approve recovery action, then show the committed replacement.
- **Code:** `backend/integrations.py` performs intake inference; `backend/recovery.py` performs recovery inference and grounded-response validation. Both call the Meta Model API. `backend/main.py` implements the API and approval transaction boundary.
- **Cross-printer adviser:** `backend/comparison.py` performs independent slicing, candidate pricing, schedule checks, validated Meta comparison and approval. `frontend/src/PrinterComparison.tsx` exposes separate data-sharing consent, option selection, and exact-price/reservation approval. `backend/tests/test_comparison.py` covers changed rates/capacity/profiles, provider failures, invalid model claims, support review, and explicit approval.
- **Verify cross-printer behavior:** import your supported profiles, upload the owned sample, select profiles in Cross-printer quote adviser, review settings/support inputs and request independent slices. For a safe public demonstration, use synthetic pricing. Permit sending the displayed totals, request Meta advice, and show that the original quote/reservation remain unchanged. Select an option, then separately approve its exact price and reservation. During a simulated pre-start outage, verify the old reservation is released only at approval. Align video pointers to the final edit if this sequence replaces the single-printer recovery shot.
- **A1/A1 mini verification:** the README summarizes the earlier matching-printer run and sample slicer estimates. Use `python -m scripts.import_a1_profile 'C:/path/to/your-reference.3mf'` with your own supported A1 or A1 mini PLA/0.4 mm project and restart. The newer cross-printer workflow reslices each candidate and separately approves any price change; the earlier same-profile recovery preserves its existing quote.
- **Reproduce:** follow the README's judge verification sequence and `docs/SETUP.md`, using your own Meta key/access. No credentials, customer files, private rates, or imported shop profiles are distributed. Native slicing requires a separately installed compatible Bambu Studio; reproduction of imported-profile results requires your own supported project and local rate card.
- **Evidence boundary:** automated provider mocks verify safeguards, not live inference. Configuration status alone is not live-call proof. The recorded demonstration should show actual successful responses; manual fallback must not be presented as Meta output.

## Submission preparation

Add the final three-minute video URL in the submission platform. The timestamps above are recording targets; align them to the final edit before submitting. Verify that the public repository contains the demonstrated integration code and that both links open while logged out. Do not upload local credentials, private test reports, or shop profile artifacts as evidence.
