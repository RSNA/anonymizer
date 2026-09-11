# Ejecutar sin interfaz

Use el modo headless en un **laboratorio o servidor** cuando no necesite la ventana de escritorio. Cree y configure el proyecto primero en la GUI.

## Objetivo

- Seguir recibiendo DICOM en un proyecto existente, y/o
- Ejecutar un lote de IA una vez en ese proyecto y salir.

## Dos comandos

### 1. Solo recibir (escucha DICOM)

```bash
rsna-anonymizer -c path/to/ProjectModel.json
```

La aplicación carga el proyecto y escucha imágenes entrantes usando los ajustes del servidor local del proyecto.

### 2. Lote de IA una vez, luego salir

```bash
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

Tanto `-c` / `--config` como `--ai-batch` son obligatorios con `--ai-batch-run`.

## Para qué sirve cada archivo

| Archivo | Propósito |
| --- | --- |
| **ProjectModel.json** | Sitio, nombre del proyecto, ruta de almacenamiento, nodos DICOM, modalidades, tiempos de espera—la definición del proyecto. |
| **AiBatchConfig.json** | Qué herramientas de IA ejecutar, modos de desenfoque/OCR, selección de estudios (`all` o una lista), anulaciones opcionales de resolución CT/MR. |

Ejemplo de configuración de lote de IA (descargable: [`AiBatchConfig.example.json`](AiBatchConfig.example.json)):

```json
{
  "algorithms": ["harmonize", "face_blur", "remove_pixel_phi"],
  "blur_mode": "gaussian",
  "pixel_phi_removal_mode": "blackout",
  "use_modality_whitelist": true,
  "include_brain_structures": false,
  "ct_segmentation_mode": "3mm",
  "mr_segmentation_mode": "3mm",
  "studies": "all",
  "skip_already_processed": true
}
```

Las listas blancas OCR permanecen bajo el directorio `whitelists/` del proyecto (igual que en la GUI).

## Requisitos previos

- Proyecto ya creado en la GUI ([Crear un proyecto](../05-create-project/)).
- Modelos y licencia de cara ya configurados en **esta máquina** ([Configuración de Funciones de IA](../03-ai-features-setup)).
- Memoria libre suficiente para los algoritmos seleccionados.

## Cómo se ve cuando va bien

- Modo recepción: el proceso sigue en marcha; los estudios nuevos aparecen bajo el almacenamiento / Conjunto de datos cuando abra la GUI más tarde.
- Modo lote: el registro muestra fases y un resumen; el proceso sale al terminar (código de salida 0 si tiene éxito).

## Fallos habituales

| Problema | Qué comprobar |
| --- | --- |
| `--ai-batch-run` sin archivos | Proporcione tanto `-c` como `--ai-batch` |
| Errores de puerta de funciones | Descargue modelos / licencia en esa estación |
| Lista de estudios vacía | Importe datos primero, o corrija `studies` en AiBatchConfig |
| Poca memoria | Reduzca la carga concurrente; véase [Solución de problemas](../troubleshooting.md) |

## Para clínicos

Headless **no** sustituye revisar una muestra en el Conjunto de datos o Vista de Series. Use la GUI para la configuración inicial y controles de calidad; use headless para recepción rutinaria o lote nocturno.

!!! tip "El mismo trabajo que el lote de la GUI"
    Pasos de escritorio: [Ejecutar en muchos estudios](../08-process/05-run-on-many-studies/). Headless usa las mismas herramientas de IA con una receta JSON.

## Siguientes pasos

1. [Solución de problemas](../troubleshooting.md) si algo falla
2. [Tutoriales](../tutorials/) para recorridos cortos
3. Volver a [Inicio](../) para la lista completa de capítulos
