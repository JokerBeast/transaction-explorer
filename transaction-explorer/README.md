# Transaction Explorer

Sistema de normalización y exploración de transacciones multifuente desarrollado en Python y Streamlit.

## Tecnologías y requisitos

- Python 3.11 o posterior (desarrollo comprobado con Python 3.12).
- Streamlit para la interfaz; Pandas para tablas y datos de gráficos.
- Biblioteca estándar: JSON, fechas, CSV y `Decimal` para el dinero.
- Pytest para ejecutar la suite. Las pruebas del núcleo también son compatibles con `unittest`.
- Windows con PowerShell. Se necesita acceso a PyPI únicamente para instalar dependencias.

## Instalación en Windows / PowerShell

Desde el directorio padre del proyecto:

```powershell
Set-Location -LiteralPath '.\transaction-explorer'
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abra `http://127.0.0.1:8501` si el navegador no se abre automáticamente. Para detener el servidor, presione `Ctrl+C`. Los comandos usan directamente el Python del entorno virtual; no necesitan activar scripts ni cambiar la política de ejecución de PowerShell. Si el proyecto se mueve, adapte la ruta del primer comando.

Si el entorno virtual existente no contiene pip, repárelo con:

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
```

## Uso de la interfaz

1. Al iniciar se cargan los 40 registros de `data/sample_transactions.json`.
2. **Dashboard** muestra calidad, distribuciones y totales por moneda.
3. **Explorador de transacciones** permite combinar fuente, moneda, estado, tipo y validez. Los filtros se intersectan; vaciar una selección muestra cero filas. Las columnas se pueden ordenar desde la tabla.
4. **Registros inválidos** permite seleccionar una fila y consultar sus originales, errores y campos normalizados. Se utiliza el número de fila para distinguir IDs ausentes o duplicados.
5. **Importación de datos** permite elegir un JSON y pulsar **Procesar archivo**. La carga reemplaza el conjunto activo; no mezcla archivos ni modifica el archivo original. Un archivo malformado o vacío muestra un mensaje y conserva el conjunto anterior. El límite de la aplicación es 10 MB.
6. **Utilizar datos de ejemplo** restaura el conjunto incluido.
7. Los dos botones de descarga exportan el conjunto activo completo, independientemente de los filtros: válidas normalizadas e inválidas con diagnósticos y originales. Se utiliza CSV con coma, comillas estándar y UTF-8 con BOM, compatible con importación en Excel. Los montos se exportan con precisión completa; `validation_errors` se representa como un array JSON.

No se requiere interacción por consola después de iniciar la aplicación. Los datos permanecen en la sesión local del navegador y se pierden al cerrar la sesión o reiniciar el servidor.

## Formato de importación

La raíz debe ser un **array JSON no vacío**. Cada elemento debe ser un objeto con `source`. No se acepta un objeto envoltorio como `{"transactions": [...]}`. Elementos que no sean objetos se conservan como inválidos, sin interrumpir el lote. Claves repetidas dentro de un mismo objeto, constantes no JSON como `NaN` y codificaciones distintas de UTF-8 se rechazan como errores del documento.

```json
[
  {"source":"A","id":"A-100","amount":12.50,"currency":"USD","status":"completed","date":"2026-01-10","type":"payment"},
  {"source":"B","transaction_id":"B-100","value":1250,"ccy":"EUR","state":"success","created_at":"10/01/2026","operation":"purchase"},
  {"source":"C","reference":"C-100","total":"12.50","currency_code":"USD","payment_status":"approved","timestamp":"2026-01-10T12:00:00-06:00","category":"charge"}
]
```

## Reglas de procesamiento

`config.json` se lee y utiliza realmente en cada ejecución de la interfaz. Contiene fuentes, campos, monedas, estados, tipos, formatos de fecha y reglas monetarias. Para cambiar una regla, edite el archivo y actualice la página. Una configuración incorrecta muestra un error explícito.

| Fuente | Importe | Fecha | Tipos originales → normalizados |
| --- | --- | --- | --- |
| A: Banco tradicional | Unidades, número JSON o cadena decimal | `YYYY-MM-DD` | `deposit` → DEPOSIT, `withdrawal` → WITHDRAWAL, `payment` → PAYMENT |
| B: Billetera digital | Unidades menores enteras; divisor 100 para USD y EUR | `DD/MM/YYYY` | `topup` → DEPOSIT, `cashout` → WITHDRAWAL, `purchase` → PAYMENT |
| C: Procesador de pagos | Cadena decimal con punto | ISO con hora, segundos y zona | `credit` → DEPOSIT, `debit` → WITHDRAWAL, `charge` → PAYMENT |

- `completed/success/approved` → COMPLETED; `pending/processing/waiting` → PENDING; `failed/error/rejected` → FAILED.
- Se recortan espacios y se unifican mayúsculas en fuentes y monedas. Los estados y tipos se comparan en minúsculas después de recortar espacios.
- Los identificadores admiten cadenas no vacías o enteros (incluido 0), convertidos a texto. Se recortan espacios; se conserva la distinción entre mayúsculas y minúsculas del ID. Booleanos, objetos y arrays no son IDs válidos.
- Todos los importes se procesan con `Decimal`. `json.loads(parse_float=Decimal)` evita una conversión intermedia a `float`. Se rechazan booleanos, comas, símbolos, NaN e infinitos. Los importes de B no admiten fracciones de unidad menor.
- C admite `Z` u offsets `±HH:MM` y fracciones de segundo de hasta seis dígitos, la precisión de `datetime`. `Z` se normaliza a `+00:00`; otros offsets se conservan. No se convierte la hora a UTC. No se inventa hora para A y B.
- Se aceptan cero y estados FAILED válidos; se rechazan importes negativos, campos obligatorios ausentes y categorías desconocidas.
- Todas las apariciones de un mismo ID en la misma fuente se marcan inválidas, incluida la primera. Un mismo ID en fuentes diferentes está permitido. Se comprueban duplicados únicamente en el lote activo.
- Cada campo defectuoso añade su error. No se descartan registros silenciosamente.

## Modelo y diagnóstico

El esquema público mantiene los nueve campos solicitados: `transaction_id`, `source`, `amount`, `currency`, `status`, `transaction_date`, `transaction_type`, `is_valid` y `validation_errors`. En registros válidos, `amount` es `Decimal`, `transaction_date` es texto ISO y `validation_errors` es una lista vacía.

**Representación necesaria para inválidos:** si un importe no puede interpretarse se conserva como `None`, y un campo textual no normalizable como cadena vacía. Usar cero o inventar valores ocultaría el problema. Esta representación solo afecta a registros inválidos, está acompañada de errores y no altera los campos del esquema. En una fuente desconocida no se adivina el mapeo de sus campos.

`ProcessingResult.originals` guarda los originales por separado, alineados por posición con `records`. Así se mantiene el esquema y se pueden diagnosticar incluso filas sin ID. Los números decimales originales se conservan exactamente como `Decimal`; el diagnóstico JSON los muestra como texto para no perder precisión. No se conserva el formato textual o la indentación del archivo original.

## Alcance de las métricas

| Métrica | Registros incluidos |
| --- | --- |
| Total procesadas, válidas, inválidas y porcentaje de validez | Todo el lote |
| Conteo por fuente | Todo el lote; incluye desconocidas y SIN FUENTE |
| Conteo por estado normalizado y por tipo | Solo válidas |
| Totales monetarios por moneda | Solo válidas; cada moneda se suma por separado |

Los totales incluyen todos los estados válidos, también PENDING y FAILED, y todos los tipos, sin invertir signos según la operación. Son una suma de importes registrados, **no un saldo, ingreso neto ni importe liquidado**. No hay tipos de cambio. El porcentaje de un lote vacío se define como cero.

La suma amplía el contexto decimal para evitar redondear importes de alta precisión. La presentación usa dos decimales y redondeo `ROUND_HALF_UP`, sin modificar los datos. La única conversión a `float` corresponde a coordenadas visuales de gráficos ya agregados; no interviene en cálculos ni CSV. Los gráficos de monedas son independientes y sus escalas no implican conversión monetaria.

## Estructura

```text
transaction-explorer/
├── app.py                     # Interfaz, filtros y exportación CSV
├── normalizer.py              # JSON, configuración y normalización
├── validator.py               # Validaciones, duplicados y separación
├── metrics.py                 # Agregaciones exactas y formato visual
├── config.json
├── requirements.txt
├── README.md
├── nota_tecnica.md
├── .streamlit/config.toml     # Tema y servidor local
├── data/sample_transactions.json
└── tests/                     # Núcleo e integración de interfaz
```

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas cubren tres fuentes, estados y tipos, fechas y zonas, precisión decimal, campos faltantes, negativos, duplicados, separación, métricas, JSON malformado y configuración externa. Los casos de interfaz utilizan [AppTest de Streamlit](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest) para simular navegación y filtros; no equivalen a una revisión visual en navegador.

Sin dependencias externas se puede comprobar el núcleo con:

```powershell
py -3 -m unittest discover -s tests -v
```

Los casos de interfaz requieren que Streamlit esté instalado. El estado de las comprobaciones se resume al final.

## Uso de inteligencia artificial

Se utilizó Codex como apoyo para organizar los módulos, implementar funciones, preparar casos de prueba y desarrollar la interfaz. Las reglas de normalización y validación están documentadas en `config.json` y en la nota técnica. El código y los resultados deben revisarse durante la preparación de la entrega.

## Verificación técnica

El registro de desarrollo informa los siguientes resultados con Python 3.12.8:

- **36 pruebas del núcleo aprobadas** con `unittest`; cinco pruebas de interfaz fueron omitidas al no estar disponible Streamlit.
- La comprobación de sintaxis mediante `compileall` terminó correctamente.
- El conjunto de 40 registros de ejemplo produjo **23 válidos y 17 inválidos (57.5 % de validez)**. Importes acumulados de registros válidos: USD `1026.74` y EUR `1594.6784`.
- No fue posible ejecutar `pytest` ni iniciar el servidor de Streamlit en ese entorno porque faltaban las dependencias. La instalación y la comprobación visual deben completarse en el equipo donde se presente el proyecto.

Para repetir las pruebas con las dependencias instaladas:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py
```
