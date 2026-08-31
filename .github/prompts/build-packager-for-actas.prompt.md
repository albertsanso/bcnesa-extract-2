# Summary
Build a packager that creates a ZIP file containing JSON files with information about the actas.

# Description
Create a Python script that packages the contents of the `/resources/actas-json/` directory into a ZIP file named `actas-json.zip`. 
The script should be saved in the `/src/packager/` directory with the filename `package_actas.py`.

The package zip file should contain:
- All the JSON files present in the `/resources/actas-json/` directory, preserving the directory structure.
- A manifest file named `manifest.json` that lists all the JSON files included in the ZIP file, along with their relative paths and sizes.

## Manifest format

The archive must contain a UTF-8 encoded `manifest.json` at its root. Its top-level structure is:

```json
{
  "source": "BCNESA",
  "files": [
	{
	  "path": "2025-2026/Segona _B_/G2/1a Fase/acta_6_page_1.json",
	  "size": 5847
	},
	{
	  "path": "model-definition.json",
	  "size": 14880
	}
  ]
}
```

Manifest requirements:
- `source` is a string and must always be `"BCNESA"`.
- `files` is an array containing one entry for every JSON file included in the ZIP, including `model-definition.json` when it is packaged.
- Each `files` entry is an object with exactly these fields:
  - `path`: the file path relative to `/resources/actas-json/`, using `/` as the separator, even on Windows. It must match the path stored in the ZIP.
  - `size`: the uncompressed file size in bytes, represented as a non-negative integer.
- Entries must be sorted lexicographically by their relative POSIX path.
- The manifest itself must not appear as an item in `files`.
- When `--season <season>` is used, `files` contains only JSON files below that season directory, while their paths remain relative to `/resources/actas-json/`.
- Serialize the manifest with two-space indentation and a final newline.

- # Usage and input parameters:
The script should accept the following optional parameters:
- `--input-dir`: The input directory containing the JSON files to be packaged. Default is `/resources/actas-json/`.
- `--output-file`: The output ZIP file name.
- `--force`: Optional flag to force re-creation of the ZIP file if it already exists.
- `--season`: Optional flag to indicate the season to be packaged. 
Default is all season. Season is the first level folder like `2021-2022`, `2025-2026`and so on.
If season is specified, only the JSON files under that season folder will be included in the ZIP file, and the output file name will be `actas-json-<season>.zip`.

```text
python src/packager/package_actas.py [--input-dir <input_dir>] [--output-file <output_file>] [--force] [--season <season>]
```