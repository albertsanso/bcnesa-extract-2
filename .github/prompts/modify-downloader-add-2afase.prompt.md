# Summary
Add to the actas downloader script the ability to download match reports (actas) for the whole season. The downloader must always include **1a Fase** for every competition and identify the additional phases correctly:

- **Vet 1a**: **TITOL**, **DESCENS** and **Play Off Títol**.
- All other competitions: **ASCENS**, **DESCENS** and **Play Off Ascens**.

The script should be able to identify these phases and download the corresponding match reports in PDF format, saving them in the 
structured directory format based on season, category, group, and phase.

# Description
The script located in `/src/actas-pdf/download_actas.py` should be modified to include the ability to download match reports from http://www.rtbtt.com, 
for the entire season. Every competition must include **1a Fase**. The **Vet 1a** competition additionally uses **TITOL**, **DESCENS** and **Play Off Títol**, while the remaining competitions use **ASCENS**, **DESCENS** and **Play Off Ascens**.

The base URL for actas is following the pattern: https://www.rtbtt.com/actes_<season>.html
Where `<season>` is a string like `2425` for season `2024-2025`, and so on.

Downloaded actas PDFs are saved in the following directory structure:
```
resources/actas-pdf/<season>/<category>/<group>/<phase>/acta_<match_id>.pdf
```

# Goal
The goal is to enhance the existing script to automatically identify and download match reports for all phases of the season, 
including **1a Fase** for all competitions, plus the competition-specific phases listed below.

The folder structure for downloaded PDFs must be maintained. Additional phase folders are siblings of `1a Fase`:
```
resources/actas-pdf/<season>/Vet<*>/<group>/<phase>/acta_<match_id>.pdf
```
Where `<phase>` is `1a Fase` for every competition; for `Vet 1a` it can additionally be `TITOL`, `DESCENS` or `Play Off Títol`; for all other competitions it can additionally be `ASCENS`, `DESCENS` or `Play Off Ascens`.

The Actes page may expose phase links through JavaScript `loadurl(...)` hrefs. Their target filenames can use the `actes_` prefix, for example `actes_VET_1_TITOL.html`, `actes_VET_1_DESCENS.html` or `actes_VET_2_A_ASCENS.html`, while Play Off targets may use filenames such as `VET_1_poff_titol.html`. The parser must inspect the complete target path and remove technical prefixes such as `actes_` or `lligues_` before identifying the category and phase; it must not silently discard the green phase links.

# Acceptance Criteria
1. The script should identify and download **1a Fase** match reports for every competition.
2. The script should identify and download `TITOL`, `DESCENS` and `Play Off Títol` for `Vet 1a`, and `ASCENS`, `DESCENS` and `Play Off Ascens` for all other competitions.
3. The downloaded PDFs should be saved in the structured directory format based on season, category, group, and phase, with every additional phase as a sibling of `1a Fase`.
4. The script should log any errors encountered during identification or downloading.
5. The script should provide a summary of successful downloads and errors broken down by phase.
6. The script should be tested against HTML links for all required phases and the correct output directory structure.
7. The script should use robust parsing techniques for changes in URLs or HTML layout.
8. The script should handle network errors gracefully, retry downloads, and respect configured rate limits.
9. The script should remain modular, with separate functions for parsing, phase selection, downloading, saving, and logging.
10. The script should adapt to seasons with different categories, groups, and available phases.

