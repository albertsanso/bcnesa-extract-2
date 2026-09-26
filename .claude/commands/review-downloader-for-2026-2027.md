---
name: review-downloader-for-2026-2027
description: Review the downloader script for the 2026-2027 season, ensuring it correctly identifies and downloads match reports (actas) for all phases.
---

# Summary
Review and update the downloader script `src/actas-pdf/download_actas.py` for the 2026-2027 season, ensuring it correctly identifies and downloads match reports (actas) for all phases.

# Description
The script should be able to navigate the website structure for the 2026-2027 season, identify the available categories, groups, and phases, and download the corresponding match reports in PDF format. 
The script must ensure that it includes **1a Fase** for every competition and correctly identifies the additional phases for each competition, as specified in the previous instructions.

Analyze the website structure for the 2026-2027 season:
- Identify new groups, categories, and phases that may have been introduced.
- Verify the correct identification of categories, groups, and phases.
- Ensure that the downloaded PDFs are saved in the structured directory format based on season, category, group, and phase.

# Acceptance Criteria
- [ ] The script should correctly identify and download **1a Fase** match reports for every competition in the 2026-2027 season.
- [ ] The script should correctly identify and download `TITOL`, `DESCENS`, and `Play Off Títol` for `Vet 1a`, and `ASCENS`, `DESCENS`, and `Play Off Ascens` for all other competitions in the 2026-2027 season.
- [ ] The downloaded PDFs should be saved in the structured directory format based on season, category, group, and phase, with every additional phase as a sibling of `1a Fase`.
- [ ] The script should log any errors encountered during identification or downloading for the 2026-2027 season.
- [ ] The script should provide a summary of successful downloads and errors broken down by phase for the 2026-2027 season.
- [ ] The script should be tested against HTML links for all required phases and the correct output directory structure for the 2026-2027 season.
- [ ] The script should use robust parsing techniques for changes in URLs or HTML layout for the 2026-2027 season.
- [ ] The script should handle network errors gracefully, retry downloads, and respect configured rate limits for the 2026-2027 season.
- [ ] The script should remain modular, with separate functions for parsing, phase selection, downloading, saving, and logging for the 2026-2027 season.
- [ ] The script should adapt to seasons with different categories, groups, and available phases, specifically for the 2026-2027 season.
