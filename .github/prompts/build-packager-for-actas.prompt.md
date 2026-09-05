# Resumen
Construir un empaquetador que cree un ZIP con los ficheros JSON de las actas.

# Descripción
Crear el script Python `src/packager/package_actas.py`, que empaquete el
contenido de `resources/actas-json/` en `resources/actas-json.zip` por defecto.
El directorio raíz del repositorio debe calcularse a partir de la ubicación del
script, no depender del directorio de trabajo actual.

# Goal

El ZIP resultante debe conservar ambas estructuras y evitar colisiones de nombres usando estos prefijos obligatorios dentro del archivo:

```text
actas-json/<ruta-relativa-al-directorio-de-actas>
manifest.json
```

## Formato de `manifest.json`

El manifiesto debe tener exactamente esta estructura:

```json
{
	"source": "BCNESA",
	"seasons": [
		"2025-2026"
	],
	"assets": {
		"ACTAS": {
			"files": ["actas-json/...", "..."]
		}
	}
}
```

Reglas del formato:

- `source` es siempre la cadena `"FCTT"`.
- `seasons` es una lista ordenada alfabéticamente de las temporadas `YYYY-YYYY`
  presentes en las rutas de los JSON incluidos. Puede estar vacía si no hay
  temporadas.
- `assets` es un diccionario con una clave `"ACTAS"` que contiene otro diccionario
  con la clave `"files"`, que es una lista de cadenas; contiene una ruta por cada JSON que se añade al ZIP incluidos sus prefijos `actas-json/` y puede estar vacía si no se encuentra ningún JSON.
- Cada cadena de `files` es la ruta relativa al directorio de entrada, usando
  `/` como separador incluso en Windows. Debe coincidir con el nombre del
  fichero dentro del ZIP.
- Las entradas de `files` se ordenan alfabéticamente por ruta.
- El manifiesto se serializa como JSON UTF-8, con `ensure_ascii=False`, dos
  espacios de indentación y un salto de línea final.

## Parámetros de uso

El script debe aceptar estos parámetros opcionales:

- `--input-dir`: directorio que contiene los JSON. Por defecto,
  `resources/actas-json/`.
- `--output-file`: ruta del ZIP de salida. Si no se indica, se usa
  `resources/actas-json.zip`, o `resources/actas-json-<seasons>.zip` cuando se
  indica `--season`, usando las temporadas normalizadas y separadas por comas.
- `--force`: permite reemplazar el ZIP si ya existe. Sin esta opción, la
  existencia del fichero de salida debe producir un error.
- `--season`: limita la búsqueda a los JSON cuya primera carpeta relativa bajo
  `--input-dir` sea una de las temporadas indicadas. Acepta una temporada o
  varias separadas por comas, por ejemplo `2023-2024,2024-2025`; se ignoran
  espacios alrededor de cada valor, se eliminan duplicados y cada valor debe
  tener formato `YYYY-YYYY`. Un `--output-file` explícito tiene prioridad
  sobre el nombre automático.

El script debe comprobar que el directorio de entrada existe, crear los
directorios padre de la salida si es necesario y usar compresión
`ZIP_DEFLATED`.

```powershell
python src/packager/package_actas.py [--input-dir <input_dir>] [--output-file <output_file>] [--force] [--season <season>]
```