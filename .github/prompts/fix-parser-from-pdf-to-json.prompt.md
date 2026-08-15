# Summary

El script `convert_pdf_to_json.py` es un script que convierte archivos PDF de actas a formato JSON.

Se han encontrado algunos errores de parseo.

# Main Goal

- Corregir y modificar el script `convert_pdf_to_json.py` y genere un JSON válido.

# Hard rules

When processsing this document, you must follow these rules:
- Use the information in the PDF to generate a JSON that matches the structure defined in `/resources/actas-json/model-definition.json`.
- Only sections finished with `PENDING` should be considered as problems to be fixed. Sections marked as `FIXED` should be ignored.

# Source of truth

El formato JSON de salida debe cumplir con la estructura definida en el archivo `/resources/actas-json/model-definition.json`, que define los campos esperados y sus tipos.

# Problemas conocidos

## Informacion de partidos de dobles omitida - FIXED - SKIP

La informacion de los patidos de dobles se encuentra en el nodo "dobles" del JSON generado, pero no se captura correctamente.

### Descripcion del problema

El nodo "dobles" debe contener la informacion de los jugadores de dobles, incluyendo su nombre y número de licencia. por ejemplo:
```json
  "dobles": {
    "local": [
      {
        "nombre": "SANZ GARCIA, CELIA",
        "licencia": 35875
      },
      {
        "nombre": "PIÑÓN PITA, VALERIA",
        "licencia": 39326
      }
    ],
    "visitante": [
      {
        "nombre": "TUBIO MARCO, MARIA LUISA",
        "licencia": 12345
      },
      {
        "nombre": "CRESPO RIAL, MARTA",
        "licencia": 67890
      }
    ]
  }
```

En las actas en PDF, la informacion de cruce de dobles se enceuntra en la ultima posicion de la tabla de partidos, pero no se captura correctamente en el JSON generado.

### Ejemplos de Actas afectadas

`resources\actas-pdf\2025-2026\Preferent\G1\1a Fase\acta_8.pdf`

COn el contenido de texto similar al siguiente:
```text
A 12495 CHEN Xujiaen Y 4682 RIBERA Albert 3 2
B 17045 DE LA CALLE Albert X 11592 SANCHÍS Marc 3 0
C 15363 LI Pinda Z 2452 ESPERT Nil 0 3
A 12495 CHEN Xujiaen X 11592 SANCHÍS Marc 3 0
C 15363 LI Pinda Y 4682 RIBERA Albert 2 3
B 17045 DE LA CALLE Albert Z 2452 ESPERT Nil 1 3
D1 12495 CHEN Xujiaen D1 4682 RIBERA Albert 1 3
D2 17045 DE LA CALLE Albert D2 2452 ESPERT Nil
TT L'HOSPITALET 'B' EL CENTRE Jocs 13 14
4 3
```

Donde las lines que empiezan por `D1` y `D2` o valores diferentes a `A`, `B`, `C` y `X`, `Y`, `Z` son los partidos de dobles, y se debe capturar 
correctamente la informacion de los jugadores de dobles, incluyendo su nombre y número de licencia.

## PDF son multi-acta - PENDING

Los ficheros PDF pueden contener varias actas, y el script actual no maneja correctamente este caso.

### Descripcion del problema

Cada página del PDF contiene exactamente una acta, por lo que el script debe procesar cada página por separado y generar un JSON para cada acta.