# Script del anonimizador (avanzado)

Las [opciones de desidentificación](index.md#2-de-identification-options) compilan el script del proyecto en la mayoría de sitios. Use esta página para cambiar reglas de etiqueta concretas, elegir una estrategia de fechas, cargar una tabla de búsqueda de pacientes o importar un `.script` CTP.

## Abrir el editor

Con el proyecto ya creado: **Archivo → Ajustes del Proyecto → Editar script del anonimizador**.

El editor carga `{site_id}-anonymizer.script` junto a `ProjectModel.json` en la carpeta de almacenamiento del proyecto (la carpeta que se muestra arriba del **Panel de control**). La línea **Script** del diálogo es la ruta de ese archivo de script. El `default-anonymizer.script` empaquetado nunca se sobrescribe.

Estado de cabecera: resumen de opciones (**Basic**, **Retain** u opciones seleccionadas abreviadas). **Custom** indica que el script en vivo ya no coincide con una compilación nueva de las opciones guardadas.

![Editor del script del anonimizador](shots/macos/AnonymizerScriptEditor.png)

## Vistas

| Vista | Contenido |
| --- | --- |
| **Activos** (predeterminada) | Reglas que conservan o transforman el valor (no `@remove()`). |
| **Eliminados** | Reglas cuya operación es `@remove()`. |
| **Todos** | Todas las reglas del script. |

**Buscar** y el filtro de barra **Operando** se aplican dentro de la vista actual.

## Cambiar una regla {#4-custom-script-edits}

1. Seleccione una fila.
2. Inspeccione operandos con el filtro **Operando** de la barra o el control **Operando** del detalle — **Cómo funciona este operando** se actualiza al instante; la regla no cambia hasta **Aplicar**.
3. Si el operando exige un parámetro, **Aplicar** lo solicita (véase [Operandos](#operands)). **Cambiar parámetro** edita el parámetro en una regla que ya usa ese operando.
4. **@remove()** y luego **Aplicar** saca la etiqueta de **Activos** (la regla permanece en el script).

## Catálogo de operandos {#operands}

Las operaciones admitidas coinciden con el catálogo del editor de script y el recorrido de ingestión. Los parámetros se piden en **Aplicar** cuando hacen falta. Las operaciones de delta de fecha en campos de fecha deben usar la misma operación que **StudyDate** (el editor ofrece alineación en un clic).

| Operando (texto de script) | Parámetro | Comportamiento |
| --- | --- | --- |
| `@keep` | — | Dejar el valor sin cambios. El texto libre conservado puede seguir siendo escaneado por Embedded PHI / NER de informes. |
| `@safe()` | — | Extensión del producto (no CTP): dejar el valor sin cambios y excluirlo del NER masivo Embedded PHI / PseudoPHI. Para cadenas técnicas retenidas que no deben scrubearse con NER. |
| `@remove()` | — | Eliminar la etiqueta del dataset anonimizado. |
| `@empty()` | — | Mantener la etiqueta presente con valor vacío. |
| `@uid` | — | Sustituir por un UID anonimizado estable. Mismo UID original → mismo UID anonimizado en el proyecto (integridad referencial). |
| `@ptid` | — | Sustituir por el ID de paciente anonimizado del proyecto para este paciente. |
| `@acc` | — | Sustituir por el número de accession anonimizado de este estudio cuando esté asignado. Fuente vacía permanece vacía. |
| `@hashdate` | — | Desplazar fecha/fechahora con un desfase estable por paciente derivado del ID de paciente PHI. Se preservan los intervalos entre estudios de ese paciente. Establece `(0028,0303) LongitudinalTemporalInformationModified = MODIFIED` cuando corre cualquier delta de fecha (código 113107 si Modified Dates está seleccionado). |
| `@lookup(this,ptid)` | — | Sustituir por el ID de paciente anonimizado de la tabla de búsqueda (`filas ptid/` en `.properties` CTP). Si la tabla no está cargada, **Aplicar** abre **Cargar tabla de búsqueda de pacientes**. |
| `@lookup(this,dateoffset)` | — | Aplicar el desfase en días por paciente de la tabla (`filas dateoffset/`). Si no están cargadas, **Aplicar** abre **Cargar tabla de búsqueda de pacientes**. |
| `@incrementdate(this,n)` | **`n`**: desfase en días entero con signo (DATEINC del ensayo). Positivo atrasa fechas; negativo las adelanta. Confirmar aplica el mismo `@incrementdate(this,n)` a cada campo de delta de fecha del script (listados en el aviso). | Desplazamiento fijo en días para todos los pacientes. Se preservan los intervalos entre estudios de un paciente. |
| `@rebasedate(this,origin)` | **`origin`**: inicio de época como `YYYYMMDD` (ocho dígitos; predeterminado `19600101`). | Rebase TCIA/NCTN: fecha anonimizada = `origin + (fecha real − basedate)`. Requiere `basedate/<PatientID>=YYYYMMDD` en la tabla. Escribe `(0012,0052)` / `(0012,0053)=REGISTRATION` desde PHI StudyDate − basedate. Si no hay basedates, **Aplicar** abre primero **Cargar tabla de búsqueda de pacientes**. |
| `@round(this,n)` | **`n`**: entero ≥ 1, anchura de banda de edad en años enteros. Las edades se redondean **hacia abajo** al múltiplo más cercano de `n` (VR AS). | Engrosar Patient Age. Anchura `5`: `023Y` → `020Y`, `029Y` → `025Y`. |
| `@always()text` | **`text`**: reemplazo literal no vacío (no debe empezar por `@`). Se guarda como `@always()YES`. Literales sin `@` (`YES`) en scripts antiguos son el mismo operando. | Fijar el elemento a un valor fijo; crear el elemento si falta. |
| `@process()` | — | Conservar el contenedor de secuencia (`SQ`) y aplicar recursivamente las reglas del script a los ítems internos. |

El filtro de barra **Operando** **Todos** muestra cada regla de la vista; un operando concreto filtra la lista y actualiza la ayuda sin asignar hasta **Aplicar**.

## Añadir una etiqueta que falta

**Añadir desde diccionario** (barra inferior) lista etiquetas del diccionario DICOM ausentes del script. **Añadir** inserta una regla con valor predeterminado `@keep`. El botón se oculta cuando el script ya cubre el diccionario.

## Guardar

| Control | Efecto |
| --- | --- |
| **Aceptar** | Validar operandos; escribir `{site_id}-anonymizer.script` en la carpeta de almacenamiento del proyecto; recargar las reglas activas del anonimizador; mantener el proyecto apuntando a ese archivo. |
| **Revertir** | Recargar el archivo de script desde el disco; descartar ediciones no guardadas. |
| **Cancelar** | Cerrar sin guardar. |

!!! note "Opciones vs. ediciones personalizadas"
    Aceptar nuevas [opciones de desidentificación](index.md#2-de-identification-options) recompila desde el predeterminado empaquetado más superposiciones y **descarta** ediciones personalizadas del script. Las instancias ya almacenadas no se vuelven a anonimizar.

## Tabla de búsqueda de pacientes y fechas {#5-patient-lookup-table-and-dates}

### Fechas longitudinales {#longitudinal-dates-tcia-style}

| Estrategia | Operando | Requisito |
| --- | --- | --- |
| Hash por paciente | `@hashdate` | Script compilado predeterminado; sin tabla de búsqueda. |
| Desfase por búsqueda | `@lookup(this,dateoffset)` | Filas `dateoffset/` en el `.properties` de búsqueda. |
| Desfase del ensayo | `@incrementdate(this,n)` | Parámetro `n` (DATEINC); aplicado a todos los campos de delta de fecha. |
| Rebase de época | `@rebasedate(this,origin)` | Filas `basedate/`; parámetro `origin` (`YYYYMMDD`). |

Las cuatro preservan intervalos entre estudios de un paciente y establecen Longitudinal Temporal Information Modified como en `@hashdate`. Advertencias sobre UID/fecha/accession deterministas: [Protocolo de desidentificación](../deidentification-protocol.md#deterministic-replacements-uids-dates-accessions).

### Tabla de búsqueda de pacientes {#patient-lookup-table}

Abra **Cargar tabla de búsqueda de pacientes** mediante:

- **Aplicar** en `@lookup(this,ptid)`, `@lookup(this,dateoffset)` o `@rebasedate(this,origin)` cuando la tabla requerida (o filas `dateoffset` / `basedate`) no esté cargada; o
- **Cargar tabla de búsqueda** / **Reemplazar tabla de búsqueda** junto al control **Operando** del detalle en una regla dependiente de búsqueda.

![Cargar tabla de búsqueda de pacientes](shots/macos/LookupTable.png)

**Cargar tabla de búsqueda de pacientes**:

1. **Examinar…** un archivo `.properties` CTP/TCIA.
2. Confirme los conteos de pacientes y desfases de fecha y los **cambios de script** listados (`@ptid` → `@lookup(this,ptid)`, `@hashdate` → `@lookup(this,dateoffset)` y campos de fecha coincidentes).
3. **Aceptar** guarda una copia privada del proyecto de la tabla, reescribe esas reglas y habilita la búsqueda en tiempo de ejecución. **Cancelar** deja el script sin cambios.

Claves `.properties`:

```text
ptid/<PHI-PatientID>=<anonymized-PatientID>
dateoffset/<PHI-PatientID>=<días-enteros-con-signo>
basedate/<PHI-PatientID>=YYYYMMDD
```

`ptid/` solo es válido. `dateoffset/` habilita `@lookup(this,dateoffset)`. `basedate/` habilita `@rebasedate(this,origin)`.

!!! note "Lookup tras almacenar archivos"
    Cargar una tabla de búsqueda **no** vuelve a anonimizar las instancias ya presentes en el proyecto. Los pacientes ya en el proyecto siguen sin fila en la tabla. Los archivos **nuevos** cuyo ID de paciente PHI no esté en la tabla se ponen en cuarentena como **Lookup_Miss** y no se almacenan.

## Importar un script CTP

**Importar…** carga un archivo `.script` personalizado (no un `.properties` de búsqueda). Se rechazan operandos desconocidos. Las reglas de fecha deben coincidir con la operación StudyDate (corrección en un clic disponible). Al **Aceptar**, confirme qué opciones de desidentificación registrar para ese script (prellenadas desde sus reglas).

## Si falla

- **Aceptar** rechazado → corrija los operandos `@…` no admitidos indicados en el error. `@always()` vacío no es válido; indique un `text` no vacío. Los literales sin `@` se aceptan como valores fijos (`ALWAYS`).

## Véase también

- [Crear un proyecto](index.md) — cómo las opciones compilan `{site_id}-anonymizer.script`
- [Protocolo de desidentificación](../deidentification-protocol.md)
- [Declaración de conformidad DICOM](../dicom-conformance-statement.md)
