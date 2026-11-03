# Print3DFlow three-minute demonstration

## Final recorded X2D keychain cut

**[Watch the final demo on YouTube](https://youtu.be/tIm6Na5HFAg)** (2:55).

The final submission edit runs 2:55 (175.042 seconds), with enlarged actual app views and ElevenLabs Brian narration with corrected Baseten and Bambu pronunciations. It uses a four-color keychain, Baseten-hosted Meta Muse Spark Open, invented demo pricing and an isolated workspace. The planner reports verified blockers/missing comparison evidence; a separate dedicated X2D workflow verifies the native slice. Recovery moves to a later X2D slot with the approved quote preserved. This edit does not demonstrate four-color cross-printer comparisons or physical printing.

| Final-cut time | Evidence | Focus |
| --- | --- | --- |
| 0:00-0:14 | Print3DFlow | From keychain request to an approved production plan |
| 0:14-0:28 | Meta-assisted intake | Structured requirements, reviewed before job creation |
| 0:28-0:42 | Four assigned colors | Actual geometry, embedded dimensions and filament slots |
| 0:42-0:56 | Verified tool trail | Meta checks evidence instead of guessing |
| 0:56-1:10 | Native X2D slicing | Purge and change overhead are counted once |
| 1:10-1:24 | Review the candidate | Native tool allocation stays visible |
| 1:24-1:37 | Approve the exact price | Price approval does not reserve capacity |
| 1:37-1:48 | Approve the reservation | A separate scheduling decision |
| 1:48-2:01 | A simulated outage | The original reservation stays until replacement approval |
| 2:01-2:11 | Stale advice is visible | Historical evidence cannot silently become current |
| 2:11-2:27 | Meta explains recovery | A later X2D slot, the same approved quote |
| 2:27-2:41 | Operator-approved recovery | The audit records each commitment |
| 2:41-2:55 | Evidence, advice, approval | Print3DFlow · built for real shop decisions |

The cut shows exact-price approval, separate initial reservation approval, and separate recovery approval. The stale planner trail is historical; it is not presented as a refreshed valid recommendation. The Meta recovery adviser uses fresh verified scheduling results. Waits are omitted and the video is labelled an edited walkthrough of actual app captures. Models, private settings and raw reports remain local; no physical printer or camera commands were issued during recording.

See [the submission description](SUBMISSION.md) for matching judge pointers. The single-filament three-printer sequence below is an alternative rehearsal guide, not the final video.

## Alternative single-filament rehearsal

Show one synthetic job with twenty copies of the owned `samples/demo-block.stl`: Meta intake, independent A1/A1 mini/X2D results, the Meta production planner and verified tool trail, explicit initial approval, stale evidence, and approval-controlled recovery after a simulated pre-start outage. Use a fresh rehearsal database, invented demo pricing and a deadline at least three days ahead.

| Time | Screen action and evidence |
| --- | --- |
| 0:00-0:12 | Introduce the shop problem: a quote is useful only if the production plan can be kept. |
| 0:12-0:37 | Attach the required owned STL, select PLA and As-printed before extraction, and enter a request for twenty blocks with a precise future deadline. Extract with Meta, confirm missing STL units as millimeters, review, then create the job. |
| 0:37-1:00 | In Cross-printer quote adviser, review the A1, A1 mini and X2D presets and actual support inputs. Confirm settings, then Slice and compare selected printers. Show three independently sliced candidate quotes and schedules, with no committed reservation. |
| 1:00-1:24 | In Meta-assisted production planner, check its planning-facts consent and click Plan with Meta. Show actual model attribution, recommendation and the Verified tool trail: check_job_readiness and read_verified_comparison. Expand a result containing profile, slice duration, schedule, deadline status and evidence IDs. Planning has not selected a price or reserved capacity. |
| 1:24-1:40 | Choose the X2D as the operator's scenario choice, even if Meta recommends another option. Pause after radio selection: no commitment yet. Check the exact-price/reservation approval box, then Approve price & reservation. Show the confirmed initial reservation. |
| 1:40-1:58 | Show that the initial commitment has invalidated the earlier advice. Simulate printer outage before the reservation starts; capacity changes too. Refresh the page if needed to show the stale-plan warning and hidden recommendation. The historical tool trail remains labeled historical. |
| 1:58-2:24 | Run Plan with Meta again; show the grounded instruction to obtain a fresh comparison. This instruction must remain usable rather than inheriting the obsolete comparison. Review inputs and request fresh independent comparisons for all three profiles; then run the planner again and inspect the new supported recommendation and schedule facts. Shorten waits visibly. |
| 2:24-2:47 | Select an on-time A1 or A1 mini alternative with reviewed supports. Show its actual price delta and that the original quote/reservation remain unchanged. Check the exact-price/reservation approval box, then Approve price & reservation. Show the approved replacement and release of the old slot. |
| 2:47-3:00 | Show planner_advice_created and comparison_approved in history, plus the replacement reservation. Close: verified evidence, Meta advice, operator-approved commitments. |

## Narration

Use the synchronized local narration in `DEMO-NARRATION.txt`. The timestamps are edit targets, not promises about inference or slicing latency. Keep the final video within three minutes including end cards. A complete take may run longer: trim only waiting periods and display a "wait shortened" caption. Preserve each request and its actual result from the same rehearsal.

## Rehearsal setup

1. Keep the main workspace on port 8765 untouched. Run `./scripts/start_demo.ps1` to create a fresh rehearsal on port 8766, or use its `-Port` option for an unused local port.
2. The launcher initially copies the local rate card. Before recording or any external inference, replace it through Shop rates in the rehearsal with clearly labeled invented demo values. Never show the private rate card or copy it into public evidence.
3. Confirm all three separately imported supported PLA profiles are available. They are not bundled with the public repository. Review preset differences without implying identical quality. Use the owned STL rather than a multicolor model: unverified multicolor and custom finishing deliberately block this quoting storyline.
4. Select As-printed before Meta intake. Suggested request: "I need twenty PLA sample blocks in white, at the original size, by [precise future date and time with timezone]." Leave STL units unstated so the review demonstrates clarification. Resolve millimeters before submission; do not edit source request text after extraction.
5. Enter support share 0 only after verifying the flat block generates no support on each selected profile. Unknown support review must remain unresolved. Jobs repeat sequentially; this is not batch nesting.
6. Rehearse the entire outage sequence and repeat from a fresh database for recording. The initial reservation must not start before recovery approval. Slicing and inference waits count toward real elapsed time even when trimmed from the video; restart the take if the pre-start recovery window has passed.

## Evidence and approval boundaries

- The planner calls Meta through the Model API and executes only its allowed read-only checks. It reads existing comparisons; the operator initiates native slicing separately. `submit_plan` records structured advice, not production approval. Freeform model claims are not rendered as facts.
- The planner's consent covers blocker codes and non-price slice/schedule facts. Prices, rate cards, printer names, customer text, filenames and model archives stay out of its provider request. The visible local quote cards may show synthetic prices.
- The cross-printer adviser's separate Compare verified options with Meta button sends price totals only after its separate consent. It is optional and not used in this three-minute planner storyline; do not imply the planner compared prices or recommended the cheapest option.
- Selecting a radio option, granting planning consent and accepting an exact price/reservation are separate decisions. Only Approve price & reservation commits the comparison option. Historical quotes remain recorded; recovery atomically replaces the original reservation.
- A commitment, requirement/rate/profile change, outage or expiration can invalidate old advice. Show the actual stale warning and suppress the old recommendation. To demonstrate the refresh fix, show the new request-comparison instruction before generating new results.
- If the actual recommendation differs from the desired scenario printer, disclose the operator's choice. If totals tie, say they are equal. Do not force late or unsupported options, invent a price delta, or claim physical-print accuracy. No printer command or customer message is sent.

Use the Cross-printer quote adviser's Approve price & reservation for both commitments. The earlier Propose recovery / Explain recovery options with Meta / Approve recovery controls demonstrate a different same-profile path and are outside this recording.

## Verified basis and submission

The planner's isolated browser/API workflow passed 74 checks with four live Meta planner runs and native A1/A1 mini/X2D slices. It verified tool evidence, stale-plan handling, rejected unconfirmed/wrong-price/wrong-currency approvals, exact approval and idempotency. A synthetic reservation was created only after scripted operator approval in the isolated database. The regression suite passed 156 tests, with two optional tests skipped. These are prototype behavior checks, not physical manufacturing validation.

Keep recordings, imported settings, costs, model files, local test scripts and raw reports private. Only the public summary belongs in the repository. Update `docs/SUBMISSION.md` timestamps to the final cut and enter the actual video URL on the submission platform; verify repository and video access while logged out.
