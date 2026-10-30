# Print3DFlow user guide

Use this guide to operate the current local MVP. For repeatable acceptance tests and a results template, see the [test guide](TEST-GUIDE.md). For technical setup, see the [README](../README.md), [integration setup](SETUP.md), and [architecture](ARCHITECTURE.md).

## 1. Choose your test environment

Print3DFlow is a trusted local operator prototype. Open the running app at `http://127.0.0.1:8765/`. Do not expose the unauthenticated app publicly.

Prefer a separate test database for rehearsals. Test jobs, outage simulations and approved reservations change the database you are using. Database isolation does not isolate configured physical printers or external API accounts.

If the dependencies and frontend are already installed, start a fresh test workspace from the project root in a **new PowerShell terminal**:

```powershell
$testDirectory = Join-Path (Get-Location) ('data/user-tests/' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testDirectory -Force | Out-Null
$env:DATA_DIR = $testDirectory
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $testDirectory 'shop.db').Replace('', '/')
./scripts/start.ps1 -Port 8767
```

Open `http://127.0.0.1:8767/`. A new workspace starts with synthetic pricing and virtual demo printers; locally configured imported profiles may also register. The main workspace remains separate. This terminal still loads local `.env` credentials and printer connection settings. Camera, light and Meta tests are explicitly triggered actions, not disabled by database isolation. Stop the server with Ctrl+C and close the test terminal when finished.

The existing `start_demo.ps1` launcher is another rehearsal option, but it copies the main app's current shop rate card. Replace those copied rates with invented values before public recording or consent to send quote totals. Do not treat that launcher as a privacy scrubber.

### Capabilities and prerequisites

| Workflow | Needed |
| --- | --- |
| Manual job intake and labelled manual estimates | Running app, valid owned STL or supported 3MF |
| Meta intake, planner or explanations | Locally configured supported Meta provider and credits |
| Native single-color quoting | Installed Bambu Studio and an available compatible profile |
| A1 / A1 mini / X2D comparison | Separately imported supported PLA profiles |
| Dedicated four-color X2D quote | Matching full reviewed X2D project, four supported PLA assignments and local Bambu CLI |
| Read-only printer status | Local LAN configuration, valid credentials, trusted certificate chain and matching serial |
| Live camera | Working local liveview plus compatible certificate trust |
| Meta bed review | Fresh camera frame and explicit permission to send that image |
| Chamber light control | Fresh reported light state and explicit On/Off action; firmware must permit the command |

Public GitHub does not contain private profiles, shop rates, model projects, printer credentials or certificates. Their absence is expected. No remote print-start feature exists.

### Configure optional integrations privately

Keep credentials in ignored local `.env`, never in the guide or a report. Preserve existing entries and restart the server after changing configuration.

- **Baseten-hosted Meta:** set `META_PROVIDER=baseten` and your `BASETEN_API_KEY`. The adapter selects the fixed hackathon model `meta-models/muse-spark-open-1026`.
- **Original Meta endpoint:** set `META_PROVIDER=meta`, `META_API_KEY` and a supported `META_MODEL` (default `muse-spark-1.3`). Keys for one provider are not reused for the other.
- **Native slicer:** configure Bambu Studio and import your own supported reference projects using the [README](../README.md) and [filament-profile guide](FILAMENT-PROFILES.md). Saving a material request does not import a profile.
- **Physical X2D:** complete the `BAMBU_READONLY_*` fields from [.env.example](../.env.example). The printer record ID must match that physical machine in the app. The serial number is not the MAC address. Wi-Fi on the same local network is sufficient; an Ethernet cable is not required. LAN Only mode affects Bambu cloud/Handy availability; enable local liveview separately when needed. Certificate validation must succeed before calling a connector verified.

No optional credential is required for basic manual intake. Missing integrations should stay visibly unavailable rather than being counted as tested.

## 2. Know the screens

- **Job workspace:** create a job, review geometry, obtain quotes, compare printers, request Meta advice and approve reservations.
- **Printer schedule:** see reserved capacity and per-printer camera/light panels. A connected X2D panel is separate from virtual Atlas demo printers.
- **Activity log:** inspect recorded operator actions, inference results and approval events.
- **Shop rates:** configure a local rate card for new quotes. Earlier quotes keep their own snapshots.

Always read the printer name on a panel. A job reserved on a virtual or unconfigured printer does not inherit the X2D's camera connection. Viewing another printer does not move the job.

## 3. Create a print job

1. Choose **New print job** (or **Create a job** in an empty workspace).
2. Attach a valid `.stl` or `.3mf`. The repository includes an owned [sample block](../samples/demo-block.stl) for synthetic tests.
3. Enter a request such as: `Print 3 copies of this model in white PLA, at the original size, as-printed, by [specific future date, time and timezone].` Replace the deadline placeholder; use at least three days ahead for rehearsal.
4. Select the requested filament and finish. Available material requests include PLA, PETG, ABS, ASA and TPU, but request support does not imply configured quoting support.
5. Optionally select **Extract draft with Meta**. Review the extracted fields and resolve clarifications. Extraction alone does not create a job.
6. Confirm **Number of prints** means copies of the complete model or assembly. It does not change model dimensions.
7. For STL, enter the material/color information and confirm intended units. For 3MF, inspect embedded units, dimensions and assigned filament suggestions. Suggestions stay editable; review any material override warning.
8. Set a precise local deadline. If Meta supplied a draft, check the extracted-requirements review box after resolving questions.
9. Select **Create print job**. Check the title, quantity, material, finish, dimensions, deadline and actual geometry preview.

### File and appearance limits

- A model file is required; request text alone cannot create a print job.
- File validation can reject invalid geometry, oversized archives or processing-limit violations. Do not rename another file to make it appear valid.
- STL does not provide reliable filament assignments or physical units.
- Assigned 3MF slots are distinct from unused saved palette entries. A saved palette alone does not establish use of every color.
- The supported 3MF preview shows component colors; opaque paint or other unsupported assignments can remain blocked.
- Custom finishing carries an additional-cost notice and requires shop review. It does not silently receive a standard as-printed quote.

## 4. Quote the job

### Native single-color quote

1. In **Preliminary quote**, select **Slice model**.
2. Choose an available matching printer/process profile. Review nozzle, layers, infill, walls, support and saved settings.
3. Enter reviewed support share only when known. Enter zero only after verifying that no support is generated. Do not guess to clear a review blocker.
4. Confirm the manufacturing-settings checkbox and submit the slicing action.
5. Wait for the task to finish. Review the source, native material/time estimates, quote breakdown, allowance/buffer explanations and total.
6. If reproducing the estimate in Bambu Studio, use the matching geometry, units, orientation and saved settings. Compare total time including preparation, not just model-print time.

The MVP repeats single-part estimates sequentially for quantity. It does not promise batch packing or physically calibrated print duration.

### Manual estimate

Choose **Manual estimate** only for an eligible standard single-filament job. Enter reviewed grams and hours per part, confirm the displayed assumptions, and generate the estimate. It must remain labelled an estimate. It cannot bypass unconfigured materials, custom finishing or multicolor gates, and it is not native evidence for assisted execution review.

### Dedicated four-color X2D quote

Use this separate workflow only with the supported one-assembly X2D project: as-printed PLA, two 0.4 mm nozzles and AMS 2 Pro slots 1 black, 2 white, 3 yellow, 4 green. General multicolor comparison remains unsupported.

1. Create the job from the real supported 3MF, then open **Verified X2D four-color quote**.
2. Choose the same matching full project with X2D settings. Review slot order, orientation and prime tower, then confirm settings.
3. Select **Slice four-color candidate**. This creates an unselected candidate, not an approved price or reservation.
4. Review each slot's color, native tool assignment, main/total material, purge/tower material, total duration and change diagnostics. AMS slot numbers are not nozzle numbers; Auto For Flush may change allocation.
5. Inspect the native report and sliced project. Purge/tower material and change overhead are already in native totals and must not be added twice.
6. Only after confirming physical feeding compatibility, check the exact-price/mapping approval and select **Approve mappings & exact price**.
7. Use **Find a printer slot**, review the proposal, then separately approve its reservation.

## 5. Compare printers and request a production plan

1. Open **Cross-printer quote adviser** on an eligible single-color job.
2. Select available A1, A1 mini and/or X2D profiles; review their settings and support inputs. Presets may differ in quality and process.
3. Confirm the settings and select **Slice and compare selected printers**.
4. Review independent candidate prices and feasible schedules. Comparison generation alone must not change the selected quote or reservation.
5. Optional: grant the separate quote-total-sharing permission and select **Compare verified options with Meta**. This shares quote facts, not the entire private rate card.
6. In **Meta-assisted production planner**, grant planning-facts consent and select **Plan with Meta**. Inspect the recommendation and **Verified tool trail**. Missing comparisons or unresolved requirements should produce next-step instructions, not invented options.
7. Optional: expand an option's **Review current camera / bed** section to inspect the current device. Today's bed appearance is advisory for a future slot.
8. Select an option. Selection alone is not approval. Read the exact price and reservation; use the checkbox and **Approve price & reservation** only when ready to commit both.

The comparison's explicitly labelled control approves price and reservation together. The dedicated four-color workflow approves its price first and reservation separately. Neither Meta consent nor a recommendation substitutes for either workflow's approval control.

## 6. Test outage recovery

Run this on synthetic jobs in the test workspace, before the reservation starts.

1. Begin with an approved scheduled test job.
2. Select **Simulate printer outage**. This records a simulated scheduling outage; it does not stop the physical printer.
3. Check that the job requires recovery and the original reservation remains recorded.
4. Choose one recovery route:
   - **Propose recovery** followed by **Explain recovery options with Meta** evaluates compatible same-profile recovery slots.
   - Generate fresh cross-printer comparisons and run the production planner again to evaluate independently sliced alternatives.
5. Inspect the candidate start/end, deadline status and grounded reasons. With one compatible printer, recovery may mean delaying that same machine; another printer must not be invented.
6. Review and explicitly approve the selected recovery path. Only approval replaces the original reservation. Customer-update text remains a draft.

After a commitment, outage, relevant configuration change or expiry, earlier advice may be stale. Re-run the planner and regenerate comparisons as instructed. Do not rely on a historical recommendation or repeatedly approve an obsolete proposal. If the reservation already started, use manual review rather than forcing this pre-start simulation.

## 7. Monitor the printer and camera

### Read-only status

On **Printer schedule**, locate the physical printer by name. Select **Refresh light/status**, or use **Check read-only printer connection** in its scheduled-job readiness panel. Review freshness and reported state. Samples expire after sixty seconds; this is not continuous telemetry. `FINISH` does not prove an empty bed.

`not_configured` means that particular printer has no matching local connector. A virtual Atlas job is not the connected X2D. Do not change its reservation just to see a camera: use the physical X2D's schedule panel instead.

### Camera

1. Confirm local liveview is enabled and works in Bambu Studio.
2. Choose **Camera on / Start viewing** for the connected printer. A live image should appear.
3. The viewer updates at about two frames per second and automatically expires after two minutes. It does not record video or automatically share images with Meta.
4. Choose **Camera off / Stop viewing**, or leave that viewer. The app stream stops; the printer's hardware camera and recording settings are unchanged.
5. If disconnected, read the message and explicitly restart. Do not disable TLS validation to clear a certificate failure.

### Chamber light

Refresh status first. When a current chamber-light state is known, explicitly choose **Light on** or **Light off**. These buttons change physical hardware. The app reports success only after the printer reports the requested state; an unconfirmed request is not proof of success. There is no automatic retry. Restore the original light state after an optional hardware test. Print execution remains disabled.

## 8. Check the bed with Meta

1. Start camera viewing for the intended printer.
2. Select **Capture fresh bed image locally**. Inspect the exact evidence image. Capturing alone sends nothing to Meta.
3. If willing to share that image, check the single-image permission and choose **Check bed with Meta**. The image can reveal the print and printer interior. The selected external provider's data policies apply.
4. Review the capture time, model/provider, reasons and assessment: **Appears empty**, **Object or print detected**, or **Uncertain**.
5. Physically inspect the bed. Clear any object if appropriate. For uncertainty, inspect directly instead of treating the result as empty.
6. Only if the actual bed is empty, check the physical-inspection box and choose **Record physical bed inspection**. This records your observation separately from the model result.
7. Return to execution readiness and complete the other required checks. A current visual assessment without physical confirmation blocks that final readiness review.

Images expire from app memory after sixty seconds or replacement and are not saved to disk by this feature. Metadata remains in the local audit. A changed configuration, restarted server or expired capture invalidates evidence. Re-capture after expiry. Stale results cannot be confirmed; the existing manual physical checklist remains available without current visual evidence.

An empty-looking image does not establish plate cleanliness, correct plate installation, adhesion, sufficient filament or future availability. Future reservations still use scheduling constraints and explicit approval; check the bed again near actual execution. No result starts a print.

## 9. Complete execution readiness

For a scheduled native-slicer-backed job, review the **Reserved printer** name and select its **Manual** or **Assisted** policy. Both currently require starting the print manually at the printer. Automatic policy is unavailable.

Resolve the displayed quote, reservation, outage, active-printer, telemetry and visual-review blockers. Then confirm the sliced artifact, loaded filament/mappings, sufficient material, clear plate and physical printer readiness. Choose **Record physical readiness review - no remote start**.

Readiness reviews expire after ten minutes or relevant evidence changes. If a configured connector is in assisted mode, its telemetry must be fresh. Readiness is not a price approval, reservation approval or remote-start command.

## 10. Troubleshooting

| Symptom | Check / expected action |
| --- | --- |
| Camera controls disabled / `not_configured` | Check the panel's printer name. Only the explicitly configured physical printer has a connector. |
| Certificate verification fails | Check saved serial and trusted issuer bundle. Camera and MQTT may send different issuer chains. Keep verification enabled. |
| No camera image | Enable local liveview, verify Bambu Studio viewing, start the correct panel and read any disconnected message. |
| Camera ends at two minutes | Expected session limit; explicitly start a new session. A few-second dropout is not the intended behavior. |
| Light state unknown/stale | Refresh read-only status. No known reported light means the action stays blocked. |
| Light change unconfirmed | Inspect the device and firmware authorization; do not assume it changed or repeatedly retry. |
| Quote controls blocked | Check material/profile/rate setup, finish, units, support review and 3MF assignment gates. |
| Planner asks for comparison | Generate current verified slices/schedules, then run the planner again. |
| Bed image expired | Capture a new image and grant consent again if requesting another model assessment. |
| Meta unavailable / incomplete result | Use labelled manual review; no fabricated model result is provided. |

## 11. Finish and report

Use the results template in the [test guide](TEST-GUIDE.md). Keep screenshots, costs, raw reports, imported settings, certificates and credentials in ignored local storage. Do not publish camera images or customer model files as test evidence without separate authorization. Stop the test server when finished; keep the main workspace's records unchanged.
