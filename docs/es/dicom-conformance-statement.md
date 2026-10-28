# Declaración de conformidad DICOM

Esta página es la respuesta del producto a los [requisitos de conformidad DICOM PS 3.15 § E.1.3](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/sect_E.1.3.html) para aplicaciones que reivindican el **Basic Application Level Confidentiality Profile**.

Está pensada para responsables de privacidad y revisores. El flujo operativo diario está en el [Protocolo de desidentificación](deidentification-protocol.md) y en [Crear un proyecto](05-create-project/index.md#2-de-identification-options).

!!! note "Alcance de esta reivindicación"
    Conformidad aquí significa que la **ruta de importación** implementa el Basic Profile (y las opciones del Apéndice E seleccionadas) aplicando el script del anonimizador del proyecto a los atributos DICOM. La limpieza opcional de píxeles, informes, descriptores y caras se ejecuta **después** del import cuando esas opciones y funciones de IA están habilitadas. Esta declaración no es asesoramiento legal ni una certificación HIPAA del producto — véase [HIPAA Safe Harbor y MIDI-B](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b).

## Perfil y opciones reivindicados

| Elemento | Reivindicación |
| --- | --- |
| Perfil | **Basic Application Level Confidentiality Profile** (código CID 7050 113100) |
| Catálogo de atributos | [PS 3.15 Table E.1-1](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) — el extracto empaquetado `e1_1_retain_tags.json` impulsa los overlays de opciones de retención al compilar |
| Sellos de método | `(0012,0062) Patient Identity Removed = YES`; `(0012,0063) Deidentification Method = RSNA DICOM ANONYMIZER`; códigos de opción seleccionados en `(0012,0064) Deidentification Method Code Sequence` |
| Reglas autorizadas por proyecto | Script compilado `{site_id}-anonymizer.script` junto a `ProjectModel.json` (desde `default-anonymizer.script` empaquetado más overlays, o un script personalizado importado) |

## Lista de comprobación E.1.3

### Qué atributos se eliminan durante la protección

Bajo el **Basic Profile** en el import (script empaquetado por defecto, salvo que una opción de retención o edición personalizada los conserve):

- **Todas las etiquetas privadas** (salvo **Retain Safe Private** — entonces cada elemento privado se resuelve con la base de conocimiento de etiquetas privadas TCIA; los slots desconocidos se eliminan).
- **Grupos curve y overlay**.
- Atributos que Table E.1-1 marca para eliminar o vaciar bajo Basic y que el script del proyecto implementa con `@remove()`, `@empty()` o equivalente (fecha de nacimiento, nombres de médicos, identidad de institución, identidad de dispositivo, características del paciente y muchos identificadores de flujo clínico).
- **Encrypted Attributes** y etiquetas de cifrado relacionadas — **eliminadas**, no rellenadas.
- UIDs de firma digital y elementos de firma relacionados — **eliminados**.

La lista **completa** eliminar/conservar/transformar de un proyecto es el script compilado del anonimizador (editor de script). Las opciones de retención cambian los overlays como en [Opciones de desidentificación](05-create-project/index.md#2-de-identification-options). Las ediciones personalizadas prevalecen hasta que se vuelvan a aceptar opciones (recompilación desde el default empaquetado y **pérdida** de ediciones personalizadas).

### Qué atributos se sustituyen por valores ficticios y cómo se generan

| Clase de atributo | Cómo se generan los valores de sustitución |
| --- | --- |
| **Patient Name / Patient ID** | ID del sitio más un número secuencial de paciente que permanece igual para esa persona **en este proyecto**. |
| **Accession Number** | Hash determinista de un mezclador del proyecto (`site_id` / `uid_root`) más la accession original. |
| **UIDs DICOM** (Study, Series, SOP Instance, Frame of Reference y otras reglas `@uid`) | Prefijo del proyecto (`uid_root` + site id) + MD5 truncado del UID original — mismo original → misma sustitución **dentro del proyecto**. |
| **Fechas / DateTimes** | Estrategia por paciente o ensayo: `@hashdate` por defecto; o `@lookup`, `@incrementdate`, `@rebasedate`. La hora del día suele dejarse igual. Véase [Fechas](deidentification-protocol.md#fechas). |
| **Patient Age** | Redondeada a banda de cinco años (`@round`) incluso con **Retain Patient Characteristics**. |
| **Otros vaciados Basic** | `@empty()` o literales fijos según el script. |

Detalles: [Sustituciones deterministas](deidentification-protocol.md#deterministic-replacements-uids-dates-accessions).

**Retain UIDs** conserva UIDs originales. **Full Dates** conserva fechas de calendario originales.

### Encrypted Attributes Data Sets (reidentificación)

**No admitido.** El Anonymizer **no** coloca originales en un Encrypted Attributes Data Set para reidentificación posterior y **no** selecciona claves de cifrado para ese fin.

- El script por defecto **elimina** Encrypted Attributes Sequence / Encrypted Content / etiquetas relacionadas del grupo 0400 si están presentes.
- El mapa original↔anónimo autorizado vive en la **base de datos privada del proyecto** — debe quedar fuera de los paquetes de exportación/Envío.

### Alcance de la integridad referencial de los valores de sustitución

| Alcance | Comportamiento |
| --- | --- |
| **Dentro de un proyecto** | Mismo Patient ID, Accession o UID original → mismo valor anonimizado para cada SOP Instance del proyecto. |
| **Frame of Reference y UIDs relacionados** | Reglas `@uid` remapeadas de forma coherente si Retain UIDs está desactivado. Algunas secuencias RT/referencia se eliminan bajo Basic. |
| **Reprocesar el mismo Study** | Reimportar al **mismo** proyecto reutiliza mapas PHI/UID almacenados. Recompilar opciones **no** reescribe archivos ya almacenados. |
| **Entre proyectos** | **No** garantizado. |
| **Entre centros solo con DICOM liberado** | Sustituciones **sin secreto**; ver matices de sustituciones deterministas. |

### Qué atributos y valores se insertan durante la protección

| Tag | Valor / comportamiento |
| --- | --- |
| `(0012,0062) Patient Identity Removed` | `YES` (creado con `@always()` si falta) |
| `(0012,0063) Deidentification Method` | `RSNA DICOM ANONYMIZER` |
| `(0012,0064) Deidentification Method Code Sequence` | Un ítem DCM por código de opción **ejecutado** |
| `(0028,0303) Longitudinal Temporal Information Modified` | `MODIFIED` cuando corre una estrategia de delta de fechas |
| `(0012,0052)` / `(0012,0053)` (ruta rebase) | Offset From Event y Event Type `REGISTRATION` con `@rebasedate` |

Las reglas `@always()…` también pueden **crear** elementos no secuencia ausentes con un literal fijo.

### Transfer Syntaxes para Encrypted Attributes Data Set

**No aplicable.** No se crean Encrypted Attributes Data Sets.

### Qué opciones se admiten

| Opción (CID 7050) | ¿Admitida? | Cuándo |
| --- | --- | --- |
| Basic Application Confidentiality Profile (113100) | **Sí** (siempre) | Import |
| Clean Pixel Data (113101) | **Sí** | Tras import — Embedded PHI (requiere modelos) |
| Clean Recognizable Visual Features (113102) | **Sí** | Tras import — Desenfocar caras (requiere modelos) |
| Clean Graphics (113103) | **Solo seleccionable** | Solo intención — véase la nota abajo |
| Clean Structured Content (113104) | **Sí** | Tras import — Review de texto de informe / AI Batch |
| Clean Descriptors (113105) | **Sí** | Tras import — texto de metadatos |
| Retain Longitudinal Temporal Information Full Dates (113106) | **Sí** | Import (excluyente con Modified Dates) |
| Retain Longitudinal Temporal Information Modified Dates (113107) | **Sí** | Import (preset Retain) |
| Retain Patient Characteristics (113108) | **Sí** | Import |
| Retain Device Identity (113109) | **Sí** | Import |
| Retain UIDs (113110) | **Sí** | Import |
| Retain Safe Private (113111) | **Sí** | Import (KB TCIA) |
| Retain Institution Identity (113112) | **Sí** | Import |

Presets y UI: [Crear un proyecto — Opciones de desidentificación](05-create-project/index.md#2-de-identification-options). Significados: [Protocolo de desidentificación](deidentification-protocol.md).

### Por qué Clean Graphics no se ejecuta {#why-clean-graphics-is-not-executed}

La opción DICOM **Clean Graphics** apunta a gráficos quemados **no textuales** en píxeles (logos, reglas, marcas decorativas) más allá de los grupos curve/overlay habituales. Bajo el Basic Profile, este producto ya **elimina los grupos curve y overlay** en el import. Los gráficos quemados no textuales restantes son poco frecuentes en archivos de investigación clínica modernos (la mayor parte del PHI residual en píxeles es **texto**, cubierto por Clean Pixel Data / Embedded PHI). No se ha priorizado un detector/limpiador aparte para ese caso legado; seleccionar Clean Graphics solo registra la intención del proyecto y **no** ejecuta ni sella una tarea de procesamiento.

### Restricciones adicionales

- **Sin ruta Encrypted Attributes / clave pública** — no se reivindican tamaños de clave ni suites de cifrado.
- Las opciones **Clean\*** requieren funciones de IA instaladas.
- Se pueden importar **scripts CTP personalizados**; operandos desconocidos se rechazan; las reglas de fecha deben coincidir con Study Date.
- **Volver a aceptar opciones** recompila y **descarta** ediciones personalizadas; las instancias ya importadas no se re-anonimizan.
- Las puntuaciones **MIDI-B** son evidencia para revisión de cabeceras, no un sustituto de la determinación institucional ([protocolo](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b)).

!!! note "Para revisión de cumplimiento"
    Pida a su responsable de privacidad que revise esta declaración junto con las [opciones de desidentificación](05-create-project/index.md#2-de-identification-options), el script compilado y cualquier [edición personalizada del script](05-create-project/anonymizer-script.md#4-custom-script-edits). Este manual es documentación operativa y normativa, no asesoramiento legal.
