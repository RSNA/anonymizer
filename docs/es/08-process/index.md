# Procesar

Las herramientas de **Procesar** cambian **píxeles** anonimizados o **nombres de serie / estudio** tras la importación. Trabaje en **una serie** en Vista de Series (abierta desde [Vista](../07-view/)), o en **muchos estudios** desde el Conjunto de datos ([Procesamiento por lotes de IA](05-run-on-many-studies/)).

Los modelos y licencias se configuran una vez desde Bienvenido — véase [Configuración de Funciones de IA](../03-ai-features-setup/) antes de los capítulos de herramientas siguientes.

## Herramientas

| Capítulo | Herramienta | Serie de demo | Qué practica |
| --- | --- | --- | --- |
| 8.1 | [Quitar PHI de píxeles](02-remove-burned-in-text/) (texto quemado) | **`davidson_cxr`**, **`us_rgb_single_frame`** | Detectar → ocultar; Detectar → fundir con el fondo |
| 8.2 | [Armonizar nombres](03-harmonize-names/) | **`CT_Head_With_Contrast`**, **`davidson_cxr`**, **`us_rgb_single_frame`** | Resultados CT + mensaje cerebral; fuentes Playbook XR/US planar |
| 8.3 | [Desenfocar caras](04-blur-faces/) | **`CT_Head_With_Contrast`** | Desenfoque facial, modo **Gaussian** |
| 8.4 | [Ejecutar en muchos estudios](05-run-on-many-studies/) | Estudios seleccionados | Lote de las mismas herramientas en una cohorte |

Las series de demo están en `tests/controller/assets/test_dcm_files/`. Impórtelas ([Buscar](../06-search/)), luego abra Vista de Series desde el Conjunto de datos ([Vista](../07-view/) — clic derecho en la serie).

## Orden de aprendizaje

1. Termine [Configuración de Funciones de IA](../03-ai-features-setup/) para que los modelos estén listos.
2. Recorra **Quitar PHI de píxeles** en `davidson_cxr` (ocultar), luego pruebe fundir en `us_rgb_single_frame`.
3. Recorra **Harmonize** en `CT_Head_With_Contrast`, luego las demos planares en `davidson_cxr` y `us_rgb_single_frame`; **Desenfoque facial** en la misma serie CT de cabeza.
4. Use **Ejecutar en muchos estudios** cuando necesite las mismas herramientas en una cohorte.

## Siguientes pasos

1. Empiece por [8.1 Quitar PHI de píxeles](02-remove-burned-in-text/)
2. Cuando el procesamiento se vea bien, [Enviar](../09-send/) pacientes anonimizados, o [ejecutar sin interfaz](../10-headless/) en un servidor de laboratorio
