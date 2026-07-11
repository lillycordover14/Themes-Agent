# Adding PitchBook / Harmonic to the GitHub pipeline (optional)

The GitHub Action already pulls everything from the open web (funding news, firm blogs, Substacks, Medium, podcasts, X/LinkedIn links) with **no keys**. To also pull **Harmonic** and/or **PitchBook** from inside GitHub, add API keys as repo secrets — the Action reads them automatically and stays fail-safe if they're absent or wrong.

## Where to add secrets
GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Secret name | Value |
|---|---|
| `HARMONIC_API_KEY` | Your Harmonic API key (get it at https://console.harmonic.ai/docs → API / dashboard) |
| `HARMONIC_ENDPOINT` | *(optional)* Exact Harmonic API URL to pull, from https://console.harmonic.ai/docs/api-reference/introduction (e.g. a saved-search results URL). If omitted, the script uses the keyword company-search endpoint. |
| `PITCHBOOK_API_KEY` | *(only if you have PitchBook **Data API** access — the enterprise API, not the MCP)* |
| `PITCHBOOK_ENDPOINT` | The exact PitchBook Data API URL to pull (required for PitchBook to run) |

After adding, go to **Actions → "Update Themes Agent dashboard" → Run workflow**. Check the run log:
- Harmonic/PitchBook steps print what they pulled, or a clear reason they skipped.
- If Harmonic errors on the endpoint, set `HARMONIC_ENDPOINT` to the exact URL from your API docs and re-run. Send me the log line and I'll finalize the parser.

## Honest notes
- **Harmonic** has a standard key-based REST API — this works cleanly in GitHub once the key (and, if needed, endpoint) is set.
- **PitchBook**: the tool you use inside Cowork is PitchBook's **MCP**, which a GitHub Action cannot call. A GitHub Action can only reach PitchBook if your plan includes the separate **PitchBook Data API** (key + endpoint). If it doesn't, keep PitchBook on the Cowork side (the Cowork agent can write PitchBook data into this repo's `data/` folder).
- Secrets are encrypted by GitHub and never printed in logs. The scripts never fail the build if a key is missing or invalid — the web pipeline always runs.
