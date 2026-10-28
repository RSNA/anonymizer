# Procesar

**Procesar** completa el trabajo de desidentificación que la importación no hace: limpiar texto quemado en las imágenes, encontrar PHI residual en etiquetas de texto libre e informes, estandarizar nombres de serie y estudio con Armonizar, y desenfocar caras en exámenes de cabeza elegibles. Ejecute una herramienta en una serie en [Vista de Series](../07-view/index.md#series-view-what-you-can-do) con clic derecho en la serie del Conjunto de datos, o en muchos estudios con [Procesamiento por lotes de IA](05-run-on-many-studies/index.md) desde el Conjunto de datos.

Para revisar etiquetas DICOM sin cambiarlas, use [Metadata](../07-view/index.md#metadata-dicom-tags) en Vista de Series. Tras Armonizar en CT o MR, fije chips de anatomía o pinte ROIs de usuario en [Anotación](../07-view/index.md#annotation). Los segmentos de anotación son 3D en CT y MR, y 2D en XR, US y MG planar.

Los modelos y licencias se configuran una vez desde Bienvenido — véase [Configuración de Funciones de IA](../03-ai-features-setup/index.md) antes de los capítulos de herramientas siguientes.

## Flujo del centro {#recommended-site-workflow}

QA unas series en Vista de Series, luego escale con lote de IA desde el Conjunto de datos:

1. **Importar** con [Buscar](../06-search/index.md); abra muestras en [Vista de Series](../07-view/index.md#series-view-what-you-can-do).
2. **Armonizar** una muestra CT/MR y planar; corrija nombres con [Editar descripciones de estudio y serie](../07-view/index.md#edit-study-and-series-descriptions) y [Asignaciones de descripción](../07-view/index.md#description-mappings). Fije o pinte en [Anotación](../07-view/index.md#annotation). Volúmenes de órganos CT/MR: [Analytics](../07-view/index.md#analytics).
3. **Desenfocar caras** en una serie de cabeza elegible; conserve el modo del lote (demo: Gaussian).
4. **Embedded PHI** — [8.1](02-remove-burned-in-text/index.md): [Pixel](02-remove-burned-in-text/index.md#pixel), [Metadata](02-remove-burned-in-text/index.md#metadata) y [Reports](02-remove-burned-in-text/index.md#reports) en muestras.
5. **Lote** con las mismas opciones en la cohorte vía [Procesamiento por lotes de IA](05-run-on-many-studies/index.md); deje Preferir asignaciones de descripción activado.

Los capítulos 8.1–8.3 enseñan cada herramienta; 8.4 es el paso de cohorte.

## Herramientas

| Capítulo | Herramienta | Serie de demo | Qué practica |
| --- | --- | --- | --- |
| 8.1 | [Embedded PHI](02-remove-burned-in-text/index.md) — [Pixel](02-remove-burned-in-text/index.md#pixel) / [Metadata](02-remove-burned-in-text/index.md#metadata) / [Reports](02-remove-burned-in-text/index.md#reports) | `davidson_cxr`, `us_rgb_single_frame`, `demo_report_pdf` | Pixel Detect→Remove; Metadata Detect PHI; Report Text Review |
| 8.2 | [Armonizar nombres](03-harmonize-names/index.md) | `CT_Head_With_Contrast`, `davidson_cxr`, `us_rgb_single_frame` | Resultados CT + mensaje cerebral; [Anotación](../07-view/index.md#annotation) 2D/3D; volúmenes de órganos CT/MR en [Analytics](../07-view/index.md#analytics); Playbook XR/US planar |
| 8.3 | [Desenfocar caras](04-blur-faces/index.md) | `CT_Head_With_Contrast` | Desenfoque facial, modo Gaussian |
| 8.4 | [Ejecutar en muchos estudios](05-run-on-many-studies/index.md) | Estudios seleccionados | Lote de las mismas herramientas en una cohorte |

Las series de demo están en `tests/controller/assets/test_dcm_files/`. Impórtelas ([Buscar](../06-search/index.md)), luego abra Vista de Series desde el Conjunto de datos ([Vista](../07-view/index.md) — clic derecho en la serie).

## Orden de aprendizaje

1. Termine [Configuración de Funciones de IA](../03-ai-features-setup/index.md) para que los modelos estén listos.
2. Recorra Embedded PHI [Pixel](02-remove-burned-in-text/index.md#pixel) en `davidson_cxr` / `us_rgb_single_frame`, luego [Metadata](02-remove-burned-in-text/index.md#metadata) y [Reports](02-remove-burned-in-text/index.md#reports) en un informe de muestra.
3. Recorra Harmonize en `CT_Head_With_Contrast`, luego las demos planares en `davidson_cxr` y `us_rgb_single_frame`; revise o pinte segmentos en [Anotación](../07-view/index.md#annotation); en CT/MR revise gráficos de volumen de órganos de Armonizar en [Analytics](../07-view/index.md#analytics); Desenfoque facial en la misma serie CT de cabeza.
4. Use Ejecutar en muchos estudios cuando necesite las mismas herramientas en una cohorte — véase [Flujo del centro](#recommended-site-workflow) para el patrón QA en Vista de Series → lote desde el Conjunto de datos.

## Siguientes pasos

1. Empiece por [8.1 Embedded PHI](02-remove-burned-in-text/index.md)
2. Cuando el procesamiento se vea bien, [Enviar](../09-send/index.md) pacientes anonimizados, o [ejecutar sin interfaz](../10-headless/index.md) en un servidor de laboratorio
