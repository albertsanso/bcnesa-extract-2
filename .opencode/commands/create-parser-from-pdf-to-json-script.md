# Summary

This script creates a parser that converts PDF files into JSON format.

# Description

This script reads PDF files and extracts their content, converting it into a structured JSON format 
for easier data manipulation and analysis.

The reference structure for JSON output is based on the file `/resources/acast-json/model-definition.json`, which defines the expected fields and their types.

The output JSON files must be stored in the `/resources/actas-json/` directory, maintaining the same folder structure as the input PDF files.

The script must be saved in the `src/actas-pdf/` directory with the filename `convert_pdf_to_json.py`.

# Usage and input parameters:

Parameters list:
- `--season`: The season for which the PDF files need to be converted, in the format `YYYY-YYYY` (e.g., `2023-2024`). Mandatory parameter.
- `--category`: The category to convert (e.g., Preferent). If not specified, the script should convert all categories for the given season.
- `--group`: The group to convert (e.g., Group A). If not specified, the script should convert all groups for the given category and season.
- `--phase`: The phase to convert (e.g., 1st Phase). If not specified, the script should convert "1st Phase" by default only.
- `--force`: Optional flag to force re-conversion of existing files.

```commandline
python convert_pdf_to_json.py --season <season> [--category <category>] [--group <group>] [--phase <phase>] [--force]
```

# Script high level steps:
1. Parse input parameters.
2. Validate the provided season, category, group, and phase.
3. Navigate the directory structure to identify available PDF files for the specified season, category, group, and phase.
4. For each identified PDF file, read its content and extract relevant information.
5. Convert the extracted information into a structured JSON format based on the reference structure defined in `/resources/actas-json/model-definition.json`.
6. Save the converted JSON files in the specified directory structure, maintaining the same folder hierarchy as the input PDF files.
7. Log any errors encountered during the conversion process.
8. Provide a summary of the conversion process, including the number of successful conversions and any errors encountered.

# Key design considerations for the script:
- The script should handle PDF reading errors gracefully and retry conversions if necessary.
- The script should respect the file system's limitations and avoid overwhelming the system with too many simultaneous file operations.
- The script should be modular, with functions for each major step (e.g., parsing parameters, navigating the directory structure, reading PDFs, converting to JSON, saving files, logging errors).
- The script should be flexible enough for handling different seasons: each season can have different categories, groups, and phases. The script should be able to adapt to these variations.
- The script should be able to handle changes in the PDF file structure, such as changes in formatting or layout, by using robust parsing techniques (e.g., PDF parsing libraries like PyPDF2 or pdfplumber).
- The script should ensure that the output JSON files adhere to the defined schema in `/resources/actas-json/model-definition.json`, validating the structure before saving.
- The script should provide clear and informative logging, including details about the files being processed, any errors encountered, and a summary of the conversion results.
- The script should be designed to be easily maintainable and extensible, allowing for future enhancements or modifications to the parsing logic or output format as needed.

# Output script file location:
The script must be saved in the `src/actas-pdf/` directory with the filename `convert_pdf_to_json.py`.