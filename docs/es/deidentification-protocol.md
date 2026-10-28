# Protocolo de desidentificación

Esta página resume en lenguaje sencillo cómo el Anonymizer sigue el DICOM Basic Application Confidentiality Profile ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/2023b/output/chtml/part15/chapter_E.html)). La respuesta formal § E.1.3 para revisores es la [Declaración de conformidad DICOM](dicom-conformance-statement.md).

## HIPAA Safe Harbor y MIDI-B {#hipaa-safe-harbor-and-midi-b}

Los centros de EE. UU. suelen preguntar por **HIPAA Safe Harbor**. Esa norma es un **método de desidentificación** bajo la Privacy Rule (eliminar las categorías de identificadores listadas, sin conocimiento real de reidentificación)—no una certificación de producto de HHS. El Anonymizer **no** afirma estar «certificado HIPAA» ni ser «conforme con Safe Harbor» como software.

Lo que *sí* afirmamos:

- La ruta de importación predeterminada implementa las opciones de confidencialidad DICOM PS 3.15 (Basic Profile y las opciones de retención que seleccione).
- Esas opciones, y la clave de respuestas / puntuador oficial público **MIDI-B** usados en las pruebas, están diseñados en torno a la eliminación de identificadores de imagen al estilo **Safe Harbor** más prácticas de metadatos de investigación al estilo TCIA.
- El **desplazamiento de fechas** predeterminado conserva el espaciado longitudinal (Modified Dates). Eso **no** es lo mismo que la regla Safe Harbor de solo año. Los centros que necesiten solo año (o Expert Determination) deben fijar la política con su responsable de privacidad.
- El texto en píxeles, la prosa de informes y las caras siguen necesitando los pasos opcionales de IA / Review de texto de informe cuando esos objetos están presentes.

Use las puntuaciones MIDI-B y este protocolo como **evidencia para la revisión**, no como sustituto de la determinación institucional.

## Qué se elimina o se sustituye

- El nombre y el ID del paciente pasan a valores anonimizados del ámbito del proyecto (ID del Sitio + número secuencial de paciente). La misma persona conserva el mismo ID anonimizado en los estudios del proyecto.
- Los UIDs se sustituyen por valores deterministas derivados para el proyecto para que los enlaces entre imágenes se mantengan coherentes. Estos hashes son **sin secreto** (enlace estable en el proyecto, no seudonimización con clave) — ver la sección en inglés [Deterministic replacements](/anonymizer/deidentification-protocol/#deterministic-replacements-uids-dates-accessions).
- Se eliminan muchas etiquetas de flujo clínico y privadas.
- El archivo registra que se eliminó la identidad del paciente y nombra el RSNA DICOM Anonymizer como método.

## Fechas

Las fechas se desplazan por paciente (desplazamiento basado en hash) para que el **orden y el espaciado** de los estudios de un paciente sigan siendo significativos, pero las fechas de calendario no son las originales. La hora del día suele dejarse igual.

## Qué puede conservarse (opciones parciales)

Ejemplos de contexto clínico retenido (según script / opciones de perfil):

- Descripciones de Estudio y Serie (más adelante puede estandarizar nombres de serie con Harmonize)
- Sexo, edad, talla, peso y características similares cuando esté configurado
- Fabricante / modelo cuando esté configurado

## Sustituciones deterministas (UIDs, fechas, accesiones) {#deterministic-replacements-uids-dates-accessions}

Los UIDs, desplazamientos de fecha y hashes de accession son **sin secreto** y mantienen enlaces estables en el proyecto. Tabla detallada: sección en inglés [Deterministic replacements](/anonymizer/deidentification-protocol/#deterministic-replacements-uids-dates-accessions).

## Opciones de píxeles y cara en el perfil DICOM {#pixel-and-face-options-in-the-dicom-profile}

Las opciones clásicas del perfil “clean pixel data” y “clean recognizable visual features” **no** se reivindican solo como bits automáticos del perfil DICOM. En V19, use en su lugar las Funciones de IA opcionales:

- [Quitar texto quemado](08-process/02-remove-burned-in-text/index.md)
- [Desenfocar caras](08-process/04-blur-faces/index.md)

## Informes estructurados y superposiciones

Se eliminan los grupos de curva/superposición. Si se aceptan objetos Structured Report lo controlan los ajustes de clase de almacenamiento del proyecto.

!!! note "Para revisión de cumplimiento"
    Pida a su responsable de privacidad que revise las [opciones de desidentificación](05-create-project/index.md#2-de-identification-options) y cualquier [edición personalizada del script](05-create-project/index.md#4-custom-script-edits), además de las herramientas de IA para su institución. Véase también la [Declaración de conformidad DICOM](dicom-conformance-statement.md) y [HIPAA Safe Harbor y MIDI-B](#hipaa-safe-harbor-and-midi-b). Este manual es orientación operativa, no asesoramiento legal.
