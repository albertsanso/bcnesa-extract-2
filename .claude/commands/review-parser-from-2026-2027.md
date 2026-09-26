---
name: review-parser-from-2026-2027
description: Create a new parser script for HTML reports (actas) from FCTT website, ensuring it correctly parses the data and outputs structured JSON files.
---

# Summary
Build a new parser script in `src/actas-html/parse_actas_from_html_to_json.py`, ensuring it correctly parses the data from HTML match reports (actas) and outputs structured JSON files.

# Description
The actas reports are taken from FCTT website and are in HTML format. 
The parser script must be inspired in the FCTT parser in `https://github.com/albertsanso/fctt-extract/blob/main/src/actas-html/parse_actas.py`
The parser script should handle the HTML format and extract relevant data to output structured JSON files.

# Empty or not published actas
Matches that have not been played yet or whose actas have not been published cannot be skipped. 
The parser script must parse the actas for these matches and output structured JSON files, even if they are empty or not published.
Minimum fields in the JSON output should be:
- `season`: The season of the match (e.g., "2026-2027").
- `category`: The category of the match (e.g., "Vet 1a", "Vet 2a", "Vet 3a", "Vet 4a").
- `group`: The group of the match (e.g., "Group A", "Group B").
- `phase`: The phase of the match (e.g., "1a Fase", "TITOL", "DESCENS", "Play Off Títol", "ASCENS", "Play Off Ascens").
- `match_id`: A unique identifier for the match (e.g., "2026-2027_Vet1a_GroupA_1aFase_001").
- `match_date`: The date of the match (e.g., "2026-09-15").
- `home_team`: The name of the home team (e.g., "Team A").
- `away_team`: The name of the away team (e.g., "Team B").


# Acceptance Criteria
- [ ] The parser script should correctly parse HTML match reports (actas) from the FCTT website and extract relevant data.
- [ ] The parser script should output structured JSON files following the specified format in `../../docs/acta-model-definition.json`.
- [ ] The parser script should handle variations in HTML structure and ensure accurate data extraction.
- [ ] The parser script should log any errors encountered during parsing and provide a summary of successful parses and errors.
- [ ] The parser script should be modular, with separate functions for parsing, data extraction, JSON formatting, and logging.
- [ ] The parser script should be tested against a variety of HTML reports to ensure robustness and accuracy in data extraction.
- [ ] The parser script should handle edge cases, such as missing data fields or unexpected HTML structures, and provide appropriate error handling and logging.
- [ ] The parser script should be compatible with the existing directory structure for actas reports, ensuring that the output JSON files are saved in the correct location based on season, category, group, and phase.
- [ ] The parser script should be designed to accommodate future changes in the HTML structure of the FCTT website, ensuring that it can be easily updated to handle new formats or variations in the HTML reports.
- [ ] The parser script should include comprehensive documentation, including usage instructions, code comments, and explanations of the parsing logic and data extraction process.

