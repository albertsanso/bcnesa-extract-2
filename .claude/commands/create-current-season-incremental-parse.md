---
name: create-current-season-incremental-parse
description: Create a script to parse match reports (actas) for the current season incrementally
---

# Summary
Create a script `src/incremental/parse_actas_content_incremental.py` that parses match reports (actas) content for the current season, 
ensuring it correctly identifies and parses match reports for all phases.

# Description
The script should be able to navigate the downloaded match reports content for the current season, identify the available **categories**, **groups**, **phases**, **match days**
and parse the corresponding match reports.

The Input actas reports can be formatted in both PDF and HTML formats, and the script should be able to handle both formats.
- HTML format: store acta in `resources/actas-incremental-content/<season>/<category>/<group>/<phase>/<match_day>.html`
- PDF format: store acta in `resources/actas-incremental-content/<season>/<category>/<group>/<phase>/<match_day>/<match_id>.pdf`

Each <match_day>.html is the downloaded HTML content of the match day, which contains:
- For each match, if the match is still scheduled and not played yet, it should contain minimum information about the match (date, time, teams, and location).
- The metadata field `acta-content-status` should contain `partial` for matches that have not been played yet, and should contain `complete` for matches that have been played.
- For each match, if the match has been played, it should contain the full acta content, including the match report in HTML and a link to download the PDF version of the acta.

The output parsed JSON files should be stored in `resources/actas-incremental-json/<season>/<category>/<group>/<phase>/jornada_<match_day>_local_team_<local_team_id>_away_team_<away_team_id>.json`:
- Category output folder must be normalized to kebab-case (e.g., "Vet 1a" becomes "vet-1a").

# Parsing rules
- Produce a JSON file for each match, containing the parsed information from the corresponding acta.
- Parsing the actas content should produce structured JSON files following the specified format in `../../docs/acta-model-definition.json`.
- PDF files are ignored for parsing for now.
- The parser should handle variations in HTML structure and ensure accurate data extraction.

Partial and Complete actas content:
- If match day actas HTML file is `partial`, the parser should only extract the minimum information and mark the corresponding matches as not published in the JSON output. Minimum fields in the JSON output should be:
  - `season`: The season of the match (e.g., "2026-2027").
  - `category`: The category of the match (e.g., "Vet 1a", "Vet 2a", "Vet 3a", "Vet 4a").
  - `group`: The group of the match (e.g., "Group A", "Group B").
  - `phase`: The phase of the match (e.g., "1a Fase", "TITOL", "DESCENS", "Play Off Títol", "ASCENS", "Play Off Ascens").
  - `match_id`: A unique identifier for the match (e.g., "2026-2027_Vet1a_GroupA_1aFase_001").
  - `match_date`: The date of the match (e.g., "2026-09-15").
  - `match_time`: The time of the match (e.g., "18:00").
  - `home_team`: The name of the home team (e.g., "Team A").
  - `away_team`: The name of the away team (e.g., "Team B").
  - `location`: The location of the match (e.g., "Stadium XYZ").
- If match day actas HTML file is `complete`, the parser should extract the full information and mark the corresponding matches as published in the JSON output. Full fields in the JSON output should include:
  - Minimum fields as above, plus:
    - Sets and scores for each match, including the number of sets won by each team and the score for each set.
    - Any additional relevant information present in the acta, such as referee names, match statistics, and any special notes or comments.

# Goal
The goal of this script is to ensure that the actas content for the current season is parsed incrementally, producing structured JSON files that can be used for further analysis or reporting. 
The script should be robust, handling variations in HTML structure and ensuring accurate data extraction, while also providing clear logging and error handling.