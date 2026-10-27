# Filament requests and profile setup

New jobs accept PLA, PETG, ABS, ASA and TPU requests, with color stored separately. Non-PLA requests await material configuration; existing PLA estimates and prices are never substituted.

| Material | Current readiness |
| --- | --- |
| PLA | Existing registered A1, A1 mini and X2D settings; local rate card |
| PETG | Reference projects, compatible printer bindings and rates pending |
| ABS | Reference projects, compatible printer bindings and rates pending |
| ASA | Reference projects, compatible printer bindings and rates pending |
| TPU | Reference projects, compatible printer bindings and rates pending |

For each intended compatible printer/material combination, supply a single-part, single-plate Bambu Studio reference project with the actual nozzle, filament brand/type, feed mapping, plate and process selected. Also provide material cost per kg and any different machine rate or setup fee. Include sample total grams and estimated time to verify the profile.

Do not copy PLA settings or assume every printer supports every material. `profiles/materials.example.json` is a setup checklist, not usable presets. Additional materials' quoting remains disabled until configuration is implemented and verified from these inputs.

Original projects, rates, model files and test reports stay local. Automatic repair is no longer provided; upload externally repaired geometry when needed. Price and reservation changes still require explicit approval.
