---
name: create-current-season-incremental-download
description: Create a script to download match reports (actas) for the current season incrementally
---

# Summary
Create a script `src/incremental/download_actas_content_incremental.py` that downloads match reports (actas) content for the current season incrementally, 
ensuring it correctly identifies and downloads match reports for all phases.

# Description
The script should be able to navigate the website structure for the current season, identify the available **categories**, **groups**, **phases**, **match days** 
and download the corresponding match reports incrementally. 

The actas reports can be formatted in both PDF and HTML formats, and the script should be able to handle both formats.
- HTML format: store acta in `resources/actas-incremental-content/<season>/<category>/<group>/<phase>/<match_day>.html`
- PDF format: store acta in `resources/actas-incremental-content/<season>/<category>/<group>/<phase>/<match_day>/<match_id>.pdf`

Each <match_day>.html is the downloaded HTML content of the match day, which contains:
- For each match, if the match is still scheduled and not played yet, it should contain minimum information about the match (date, time, teams, and location).
- For each match, if the match has been played, it should contain the full acta content, including the match report in HTML and a link to download the PDF version of the acta.

## Pages for actas content access by category
The initial page to access the different categories of actas content is `https://fctt.cat/competicions-estatals/`.

There are some main sections `LLIGUES DE LA REPRESENTACIO TERRITORIAL DE <territory>` for each territory, and each section contains links to the different categories of actas content.
Territories include: [`Barcelona`, `Girona`, `Lleida`, `Tarragona`]

For each territory, there is a list of cards that are giving access to the different (<category>, <group>) current season actas content. 
Each card contains a link to the corresponding category and group page, which contains the list of categories and match days.

For instance, for the `Barcelona` territory, the categories and groups are:
- `RTB PREFERENT G1` which has a related anchor link to `https://fctt.cat/lligues/rtb-pref` 
- `RTB PREFERENT G2` which has a related anchor link to `https://fctt.cat/lligues/rtb-pref-2`
- `RTB PREFERENT G3` which has a related anchor link to `https://fctt.cat/lligues/rtb-pref-3`
- `RTB VETERANS 1a G1` which has a related anchor link to `https://fctt.cat/lligues/rtb-vet-1a-1`
- `RTB VETERANS 1a G2` which has a related anchor link to `https://fctt.cat/lligues/rtb-vet-1a-2`
- ...

## Pages for actas by jornada (match day) access by category and group
For each category and group, there is a page that contains the list of match days
For instance, for the `RTB PREFERENT G1` category and group, the page is `https://fctt.cat/lligues/rtb-pref` and it contains the list of match days for the current season.
Each category card has a link to its corresponding match days, and each match day contains a list of matches

The access to a concrete match day is build by adding `?jornada=1` to the category link, for instance, for the `RTB PREFERENT G1`, the link to access the match day 1 is `https://fctt.cat/lligues/rtb-pref?jornada=1`

# Script implementation

## Tech details for handling downloads
Use a robust HTML parser to extract the required information from the pages, and handle network errors gracefully, retrying downloads as needed. 
The script should respect configured rate limits to avoid overwhelming the server.
When the requested page or URL is not available, the script should:
- Log the error
- Retry mechanism for failed downloads (default: 3 retries).
- Skip the match day if the page is not available after retries, and log the skipped match day.

Future match days are not retried:
- If the match day page returns OK from the server but contains no results, and the match day is in the future
  (none of its matches has started yet, according to the match dates listed on the category/group page),
  do not retry it: the matches simply have not been played yet.
- In that case keep (save) the match day content with the minimal match info (date, time, teams, and location),
  taken from the category/group page when the match day page does not list the matches.
- Retries still apply to network errors and HTTP errors, and to match days that are not in the future.

## Retry mechanism for HTTP requests
- Apply exponential backoff for retries to avoid overwhelming the server.
- Use different user agents for each retry to avoid being blocked by the server.
- Use best practices for web scraping, including respecting `robots.txt` and avoiding excessive requests.

## Page for actas by jornada (match day) Validation (partial/complete)
- For each match day, validate that the downloaded content is complete and correct.

Validation criteria:
- The match day page should contain the expected number of matches for that match day.
- For each match, if the match has been played, the acta content should be complete
- For each match, if the match has not been played yet, the acta content should contain the minimum match info (date, time, teams, and location).
- If the match day page is not available or the content is incomplete, log the error and retry the download (up to the configured number of retries).
- If the match day page is not available after retries, log the error and skip the match day, saving the minimal match info if the match day is in the future.
- For each match, **ALL** the players must be identified: linked to their corresponding player page including a parameter **`codi_jugador`** in the URL, and the player name must be correctly extracted.

# Goal
The goal of this script is to download the actas content for the current season incrementally, in terms of match days, and store them in the structured directory format based on season, category, group, phase, and match day.
Output python script: `src/incremental/download_actas_content_incremental.py`
Script parameters:
- `--season`: The season to download the actas content for (default: current season)
- `--territory`: The territory to download the actas content for (default: all territories)
- `--category`: The category to download the actas content for (default: all categories)
- `--group`: The group to download the actas content for (default: all groups)
- `--phase`: The phase to download the actas content for (default: all phases)
- `--match_day`: The match day to download the actas content for (default: all match days)
- `--format`: The format to download the actas content in (default: both HTML and PDF)
- `--output_dir`: The output directory to save the downloaded actas content (default: `resources/actas-incremental-content`)
- `--log_file`: The log file to save the download logs (default: `logs/download_actas_content_incremental.log`)
- `--force`: Force re-download of actas content even if it already exists (default: False)
- `--retry`: Number of retries for failed downloads (default: 3)
- `--skip_pdf`: Skip downloading PDF files (default: True)

# Guardrails
- PDF content should be downloaded only if the match has been played and the acta is available in PDF format.
- A future match day whose page has no results is not an error: it is saved with minimal match info and never retried.
- All the pages under `https://fctt.cat/competicions-estatals/` and `https://fctt.cat/lligues` are flaky and may return 404 or 500 errors. The script should handle this gracefully, retrying the request as needed. Dont be aggressive with retries, and respect the server's rate limits. If the page is not available after retries, log the error and skip the territory.
- Persist Success/failure metrics that can be consumed in future runs in order to learn how to optimize retries, modeling with statistics, statistical distribution of errors, and identifying patterns in failures. This can help improve the robustness of the script over time.
- Metrics to persist include:
  - Number of successful downloads
  - Number of failed downloads
  - Number of skipped match days
  - Number of retries for each match day
  - Time taken for each download
  - Error messages for failed downloads
- Metrics should be stored in a structured format (e.g., JSON or CSV) in a separate file for analysis and reporting. In a file named `metrics/download_actas_content_incremental_metrics.json`.
- The metrics should be used in future runs to optimize the download process, such as adjusting retry strategies, identifying problematic match days or categories, and improving overall efficiency.
- The script should be designed to be idempotent, meaning that running it multiple times should not result in duplicate downloads or inconsistent state. It should check for existing files and only download new or updated content.




