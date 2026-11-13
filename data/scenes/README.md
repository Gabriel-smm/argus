# Demo scenes

Scenarios for the Scan button's picker. **Credit: Andrew**, who wrote the three scenarios in `data/contract/` (`scenario_normal.json`, `scenario_drone.json`, `scenario_jamming.json`, from his `argus-pipeline.patch` on the `new-files-for-argus` branch). They are **illustrative, not real captures**, and the app says so in a badge: "Demo: illustrative scenario by Andrew, not a real capture".

| Scene | File | What it shows | Expected report |
|---|---|---|---|
| Normal day | `normal.jsonl` | Wi-Fi and Bluetooth at 2.4 GHz | Normal activity |
| Drone nearby | `drone.jsonl` | The same, plus a hopping 8 MHz drone link (d3) and a weak burst | 1 signal needs a closer look |
| Jamming | `jamming.jsonl`, `jamming-assessment.json` | Wide, flat noise across 902-928 MHz where sensors usually transmit | Possible jamming |

`python -m context_sources.scenarios` rebuilds these from Andrew's files. Each of his detections becomes one row: `center_frequency_hz`, `bandwidth_hz`, `modulation` "unknown" (his files do not name it), `hopping` (true for a "hopping" burst pattern, false for "continuous", left out otherwise) and `duty_cycle`. Each row's `note` names the file and detection it came from. His own labels and verdicts are not used: Laya and the site check judge the signals themselves.

Jamming is judged on a band as a whole (the noise floor rose and the usual traffic disappeared), not on one signal, so the site check alone calls the jamming signal "unknown". Andrew's jamming block (`noise_rise_db`, `expected_missing`, `reason`) is kept in `jamming-assessment.json`; when it is flagged, the report's verdict is "needs a closer look", headed "Possible jamming" with his reason, and a **Jamming** tile opens the details. It is not counted among the signals, so the counts still add up.
