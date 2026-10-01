---
name: create-current-season-incremental-package
description: Create a script to package actas content for the current season incrementally
---

# Summary
Create a script `src/incremental/package_actas_content_incremental.py` that packages match reports (actas) content for the current season, ensuring it correctly identifies and packages match reports for all phases.

# Description
The script should be able to build a ZIP file in `resources/actas-json-<season>.zip` with the whole content 
in the `resources/actas-incremental-json/<season>` source folder, including the `manifest.json` file.

The zipped folder structure should be as follows:

```
resources/actas-json-<season>.zip
├── manifest.json
├── actas-json
    └── <season>
        └── <category>
            └── <group>
                └── <phase>
                    └── jornada_<match_day>_local_team_<local_team_id>_away_team_<away_team_id>.json
```

# Manifest file

The `manifest.json` file should be generated in the root of the ZIP file and should contain the following structure:

```json
{
  "source": "BCNESA",
  "seasons": [
    "<season>"
  ],
  "assets": {
    "ACTAS": {
      "files": [
        "actas-json/<season>/<category>/<group>/<phase>/jornada_<match_day>_local_team_<local_team_id>_away_team_<away_team_id>.json"
      ]
    }
  }
}
```

Manifest file format rules:
- `source` is always the string `"BCNESA"`.
- `seasons` is a list containing the current season in the format `YYYY-YYYY`.
- `assets` is a dictionary with a key `"ACTAS"` that contains another dictionary with the key `"files"`, which is a list of strings; it contains a path for each JSON file that is added to the ZIP, including its prefixes `actas-json/`. It can be empty if no JSON files are found.
- Each string in `files` is the relative path to the input directory, using `/` as a separator even on Windows. It must match the name of the file inside the ZIP.
- The entries in `files` are sorted alphabetically by path.
- The manifest is serialized as UTF-8 JSON, with `ensure_ascii=False`, two spaces of indentation, and a final newline.

# Package script usage parameters
The script should accept the following optional parameters:
- `--input-dir`: directory containing the JSON files. By default, it is `resources/actas-incremental-json/<season>`.
- `--output-file`: path of the output ZIP file. If not specified, it defaults to `resources/actas-json-<season>.zip`, where `<season>` is the current season in the format `YYYY-YYYY`.
- `--season`: the current season in the format `YYYY-YYYY`. If not specified, it defaults to the current season based on the current date.
- `--verbose`: if specified, the script should print detailed information about the packaging process, including the number of files added to the ZIP and any warnings or errors encountered.
- `--dry-run`: if specified, the script should simulate the packaging process without actually creating the ZIP file, allowing the user to see what would be included in the package.
- `--include-empty`: if specified, the script should include empty directories in the ZIP file, even if they do not contain any JSON files.
- `--exclude`: a list of patterns to exclude certain files or directories from the ZIP file. The patterns should be specified in a comma-separated format (e.g., `--exclude="*.tmp,*.bak"`).
- `--include`: a list of patterns to include certain files or directories in the ZIP file, overriding any exclusions. The patterns should be specified in a comma-separated format (e.g., `--include="*.json,*.html"`).
- `--log-file`: path to a log file where the script should write detailed logs of the packaging process. If not specified, logs should be printed to the console.
- `--force`: if specified, the script should overwrite the output ZIP file if it already exists, without prompting for confirmation.
- `--no-manifest`: if specified, the script should not generate a `manifest.json` file in the ZIP, allowing for a package without a manifest.
- `--manifest-only`: if specified, the script should only generate the `manifest.json` file without creating the ZIP file, allowing for a manifest to be created separately.



