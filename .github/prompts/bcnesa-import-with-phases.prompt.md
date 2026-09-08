---
name: bcnesa-import-with-phases
description: The bcnesa import process must support phases for matches
---

# Summary

The bcnesa import process must support phases for matches. 
This means that when importing data, the system should be able to handle different stages or phases of the import process, 
allowing for better organization and management of the data being imported.

# Description

The new unzipped folder structure is as follows:
```
/
├── actas-json/
│   └── <season>/
│       └── <Competition>/
│           └── <Group>/
│               └── <Phase>/
```

Where for Veterans, the `<Phase>` folder can be "1a Fase" or "Other". 
In case of "Other", the parser should not assume that only that one phase exists. The value "Other" means that the parse value for Group is `null`.
In case of "Other" phases, the file name format is `acta_<number>_page_<*>.pdf`, where `<number>` is the "jornada" property number for that phase.
Possible values for phases when "Other" is used are "Play Off", "ASCENS", "DESCENS", "Finals", etc. 
The "fase" field should be populated based on the folder structure, specifically from the `<Phase>` folder name.

# Acceptance Criteria
- [ ] this modification on import process focuses only in BCNESA Veterans competitions.
- [ ] The import process should correctly identify and handle different phases of matches based on the folder structure. Only for Veterans competitions.
- [ ] The "fase" field should be correctly populated in the imported data based on the `<Phase>` folder name.
- [ ] The import process should be able to handle cases where the `<Phase>` folder is named "Other" and correctly interpret the phase information from the file names.
- [ ] The import process should correctly handle multiple phases within the "Other" category.
- [ ] The import process should correctly handle cases where the `<Phase>` folder is named "1a Fase".