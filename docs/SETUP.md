# Integration setup

## Meta intake

Create a Meta Model API key in the [developer dashboard](https://dev.meta.ai/) and place it in the ignored `.env` file using the variable `META_API_KEY`. The default model is `muse-spark-1.3`. Access and credits are required. See Meta's [quickstart](https://dev.meta.ai/docs/quickstart) and [structured output documentation](https://dev.meta.ai/docs/structured-output).

Restart the server, open **New print job**, enter a synthetic request, and choose **Extract draft with Meta**. Inspect the actual response, resolve missing fields, and confirm review. No job is created by extraction alone.

## Bambu Studio

Install Bambu Studio separately. On Windows the default executable path is `C:/Program Files/Bambu Studio/bambu-studio.exe`; override it through `BAMBU_STUDIO_PATH`. No printer IP, access code, cloud token, or printer connection is required for local slicing.

The public reference profile uses installed A1 presets. It is distinct from your shop's machines and pricing. For X2D settings, use your own saved Bambu project and the importer described in the README. The importer supports a narrow, validated project shape; unsupported printer/nozzle/material configurations, object modifiers, tool changes, and post-processing scripts are rejected for review.

Local `profiles/registry.json` takes precedence over the public example. `SLICER_PROFILE_MANIFEST` may explicitly select another local manifest. Imported files and resolved configs belong in `data/` or another private location, never a public commit.

## Pricing and estimate comparisons

**Shop rates** creates an immutable local rate-card version for future quotes. Existing quotes retain their own currency, rates, and capacity buffer. Tests use invented fixtures; do not copy their values as business advice or as a shop rate card.

**Compare with Bambu Studio** records one-part estimates from the same mesh, units, orientation, plate, and process. Use total estimated time, including preparation. A quote's matching-3MF download can help reproduce its placement. Percentage tolerances are review criteria, not confidence intervals or physical calibration claims.

## Meta recovery explanations

After **Propose recovery**, choose **Explain recovery options with Meta**. The provider receives only verified option IDs, times, deadline status, delay/slack figures, and allowed reason codes. Customer text, printer names, uploaded meshes, outage-reason text, price amounts, and rate cards are not sent for this step.

The structured response must cover every option, recommend only a verified on-time option (or none when all are late), and select only reason codes justified by that option. The server renders the selected reasons with verified facts. The model has no reservation tools and cannot insert unverified prose, slots, prices, or commands into the displayed explanation.

Explanations are cached against the proposal, quote, job version, relevant printer configuration, reservations, and outages. Capacity changes during the provider call discard the response. Later changes mark it stale; approval checks again and blocks stale explanations. A model outage does not fabricate a fallback explanation: operators may review a fresh verified proposal manually. Customer updates remain templates/drafts and are not sent.

Selecting an alternative changes only the uncommitted proposal. **Approve recovery** is still required to change reservations. For a single compatible printer, the model must not imply another printer is available. App estimate/price policy and profile compatibility are unchanged.

## Development and privacy

For frontend development, start the backend on port 8765 and run `pnpm --dir frontend dev`. The Vite proxy forwards local `/api` requests. Use synthetic customer data. The app has no authentication; do not expose it on a public network.

To rehearse with a clean database and your configured local rates, keep the main app running and run `./scripts/start_demo.ps1`. The rehearsal uses port 8766 and a new ignored data directory. It does not copy or modify main-app jobs.
