/# Summary

Create a python script that crawls http://www.rtbtt.com  and downloads the match reports (actas) in PDF format. 

The script must be saved in the `/src/actas-pdf/` directory with the filename `download_actas.py`.

# Description

The default base URL is http://www.rtbtt.com, but it can be changed with the `--base-url` parameter. 
The script should navigate through the website's structure, identify the available seasons, categories, groups, 
and phases, and download the corresponding match reports in PDF format.

The script should save the PDFs in a structured directory format based on season, category, group, and phase. 

Additionally, it should log any errors encountered during the download process.

# Usage and input parameters:

Parameters list:
- `--season`: The season to download (e.g., 2024-2025). Mandatory parameter.
- `--category`: The category to download (e.g., Preferent). If not specified, the script should download all categories for the given season.
- `--group`: The group to download (e.g., G1). If not specified, the script should download all groups for the given season and category.
- `--phase`: The phase to download (e.g., 1a Fase). If not specified, the script should download "1a Fase" by default only.
- `--force`: Optional flag to force re-download of existing files.
- `--base-url`: Optional parameter to specify a different base URL for the website.

```commandline
python download_actas.py --season <season> [--category <category>] [--group <group>] [--phase <phase>] [--force] [--base-url <base_url>]
```

# Downloaded PDFs repository structure:
The downloaded PDFs should be saved in the following directory structure:
```
resources/actas-pdf/<season>/<category>/<group>/<phase>/acta_<match_id>.pdf
```

# Script high level steps:
1. Parse input parameters.
2. Validate the provided season, category, group, and phase.
3. Navigate the website structure to identify available seasons, categories, groups, and phases.
- Navigate from http://rtbtt.com to menu **Competició**, then **Calendari i Resultats**, then choose the season from the menu suboptions.
- At this point the selected URL will have a format similar to `https://www.rtbtt.com/calendaris_<season>.html`.
- `<season>` will be a string like `2425` for season `2024-2025`, and so on.
4. For each identified match report, construct the download URL and download the PDF.
5. Save the downloaded PDFs in the specified directory structure.
6. Log any errors encountered during the download process.
7. Provide a summary of the download process, including the number of successful downloads and any errors encountered.

# Key design considerations for the script:
- The script should handle network errors gracefully and retry downloads if necessary.
- The script should respect the website's rate limits and avoid overwhelming the server with requests.
- The script should be modular, with functions for each major step (e.g., parsing parameters, navigating the website, downloading PDFs, saving files, logging errors).
- The script should be flexible enough for handling different seasons: each season can have different categories, groups, and phases. The script should be able to adapt to these variations.
- The script should be able to handle changes in the website's structure, such as changes in URLs or HTML layout, by using robust parsing techniques (e.g., BeautifulSoup).


