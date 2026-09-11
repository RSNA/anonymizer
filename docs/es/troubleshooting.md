# Solución de problemas

## Modelos y Funciones de IA

| Mensaje / síntoma | Qué intentar |
| --- | --- |
| No listo / descarga fallida | Vuelva a **Bienvenido**, abra **Funciones de IA**, reintente Descargar, compruebe la red |
| OpenMP / XGBoost en macOS | Instale C++ OpenMP una vez: `brew install libomp` (necesario para Funciones de IA / contraste Harmonize) |
| Errores de licencia | Compruebe longitud/formato de `aca_`; valide en línea |
| Harmonize ya en ejecución | Termine o cancele la otra serie |
| Herramienta en gris | Instale el paquete CT/MR correspondiente |

## Importación y cuarentena

| Síntoma | Qué intentar |
| --- | --- |
| Archivos ignorados | Ya importados (misma SOP Instance) |
| Carpetas de cuarentena llenándose | Lea el nombre de la carpeta (Invalid_DICOM, Missing_Attributes, Lookup_Miss, …) |
| Lookup_Miss | Corrija la [tabla de búsqueda](05-create-project/) o el ID del paciente |

## Lotes y memoria

| Síntoma | Qué intentar |
| --- | --- |
| Poca memoria / detenido | Cierre otras aplicaciones; menos estudios; véase el diálogo de aviso de memoria |
| Todo omitido | Ya procesado—esperado a menos que borre estado/caché |
| Sin series para los estudios | La selección no tiene series DICOM legibles |

## Sin interfaz (headless)

Guía completa: [Ejecutar sin interfaz](10-headless/).

- `--ai-batch-run` necesita **ambos** `-c` y `--ai-batch`
- Las puertas de funciones fallan si los modelos nunca se descargaron en esa máquina
- `studies` vacío / sin índice PHI → importe primero en la GUI

## Pantalla

| Síntoma | Qué intentar |
| --- | --- |
| Ventana Bienvenido pequeña / recortada (macOS) | Use la V19 actual; consejos Tk 9 / reinstalar uv en [Instalación](02-install/) |
| Proyecciones fallan en US en color | Actualice a la V19 actual |
