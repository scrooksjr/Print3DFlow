# Three minute demonstration

Show one synthetic job from request to reviewed plan and exception recovery. Use the owned `samples/demo-block.stl`, a future deadline, and a fresh rehearsal database.

| Time | Demonstration |
| --- | --- |
| 0:00–0:18 | Explain the manual quoting and scheduling problem. |
| 0:18–0:50 | Submit a request to Meta, show a missing-units question, and review the extracted fields. |
| 0:50–1:22 | Upload the actual STL, confirm a supported profile, and obtain a real slice-backed quote. Explain the configured pricing policy without disclosing private business data. |
| 1:22–1:45 | Review and approve a compatible reservation. |
| 1:45–1:55 | Inject an explicitly simulated pre-start outage and click Propose recovery. Show the original reservation still recorded. |
| 1:55–2:15 | Click Explain recovery options with Meta. Show the actual tradeoffs and model attribution. |
| 2:15–2:28 | Pause on APPROVAL REQUIRED and Selected proposal · awaiting approval. Show that the original reservation's times have not changed. |
| 2:28–2:40 | Click Approve recovery. Show the confirmed replacement and unchanged quote. |
| 2:40–2:52 | Show the audit history, including the explanation and operator approval. |
| 2:52–3:00 | Close with the operational value and operator control. |

Meta performs intake extraction and recommends among verified recovery options. It selects reasons that the server validates and renders from scheduler facts. The scheduler, pricing, recovery search, and message template remain application logic. The recommendation does not select a proposal or reserve capacity; keep the operator's separate selection and approval visible. If only one compatible printer is configured, Meta explains the wait and deadline tradeoff rather than inventing compatible alternatives.

With a single option, the scheduler may already have selected the pending proposal. Show its awaiting-approval label; do not invent an extra selection click. With multiple options, Select this proposal changes only the pending choice. Approve recovery is the separate commitment action in both cases. If capacity changes and the explanation becomes stale, regenerate the proposal and explanation before approval.

State that slicing is real, outage injection is simulated, customer updates are drafts, and no physical printer is controlled. Do not claim measured productivity improvements or production accuracy without measurements. Trim waiting periods only with a clear caption; do not present fabricated output as a live result.

The local rehearsal launcher emits a fresh prompt path with a future deadline. Private recordings, API keys, local rate snapshots, customer artifacts, and imported settings are excluded from this repository.
