# Crear un proyecto

Un **proyecto** mantiene juntos los ajustes y el almacenamiento anonimizado. Créelo una vez en la ventana de escritorio, aunque un servidor ejecute después [sin interfaz](../10-headless/).

## Objetivo

Abrir un proyecto limpio con carpeta de almacenamiento e identidad del sitio listos para importar.

## Crear un proyecto nuevo

1. Desde **Archivo → Nuevo Proyecto**, abra **Configuración de Nuevo Proyecto**.
2. Elija un **Nombre del Proyecto** (corto, menos de 16 caracteres) y confirme el **Directorio de Almacenamiento**.
3. Revise ID del Sitio y Raíz UID (normalmente deje los valores predeterminados salvo que continúe un sitio del Java Anonymizer).
4. Confirme modalidades y ajustes de red con TI si va a consultar un PACS.
5. Guarde / cree el proyecto. Se abre el **Panel de control**.

![Configuración de Nuevo Proyecto](shots/macos/NewProjectSettings.png)

## Acciones cotidianas del proyecto


| Acción | Cómo |
| -------------- | ---------------------------------------------------------------------------------------------------- |
| Cerrar | **Archivo → Cerrar Proyecto** o cierre la ventana |
| Reabrir | **Archivo → Abrir Reciente** |
| Clonar ajustes | **Archivo → Clonar** en una carpeta de almacenamiento nueva (no se copian imágenes). Mantenga la Raíz UID única entre proyectos. |



## Cómo se ve cuando va bien

- El Panel de control muestra el nombre del proyecto y el ID del Sitio.
- El directorio de almacenamiento existe y es escribible.
- Puede abrir el **Conjunto de datos** curado actual (vacío hasta que importe) pulsando **Vista**.



## Cuando hable con TI

Comparta estas ideas (los detalles están en los diálogos de Ajustes del Proyecto):

- **Servidor Local** — dirección, puerto y AE Title que este ordenador usa para **recibir** imágenes.
- **Servidor de Consulta** — el archivo hospitalario desde el que busca y recupera.
- **Servidor de Exportación** o **AWS** — adónde se enviarán los estudios anonimizados.
- **Modalidades / clases de almacenamiento / sintaxis de transferencia** — qué tipos de imagen se permiten.
- **Tiempos de espera de red** — cuánto esperar ante archivos lentos.
- **Script del anonimizador** — qué etiquetas DICOM se conservan, eliminan o transforman (véase [Editor del script del anonimizador](#editor-del-script-del-anonimizador)).
- **Tabla de búsqueda de pacientes** — mapeo opcional CTP `.properties` para PatientID y desplazamiento de fecha (véase [Tabla de búsqueda de pacientes](#tabla-de-búsqueda-de-pacientes)).

Si el proyecto vivirá en un servidor de laboratorio, continúe con [Ejecutar sin interfaz](../10-headless/).

## Ajustes del Proyecto (cada control)

Abra **Archivo → Ajustes del Proyecto** (o Configuración de Nuevo Proyecto al crear). Configure esto antes de Buscar / Enviar:

### Servidor Local

Dirección, puerto y AE Title que este ordenador usa para **recibir** imágenes.

![Servidor Local](shots/macos/LocalServer.png)

### Servidor de Consulta

Archivo hospitalario usado por **Buscar** del Panel de control.

![Servidor de Consulta](shots/macos/QueryServer.png)

### Servidor de Exportación

Destino DICOM usado cuando **Enviar** (la etiqueta de ajustes puede seguir diciendo Export Server).

![Servidor de Exportación](shots/macos/ExportServer.png)

### AWS Cognito (opcional)

Credenciales para Enviar a S3 cuando esté habilitado.

![AWS Cognito](shots/macos/AWSCognito.png)

### Tiempos de Espera de Red

Cuánto esperar ante archivos lentos.

![Tiempos de Espera de Red](shots/macos/NetworkTimeouts.png)

### Modalidades / Clases de Almacenamiento / Sintaxis de Transferencia

Qué tipos de imagen y codificaciones se permiten.

![Modalidades](shots/macos/Modalities.png)
![Clases de Almacenamiento](shots/macos/StorageClasses.png)
![Sintaxis de Transferencia](shots/macos/TransferSyntaxes.png)

### Editor del script del anonimizador

El **script del anonimizador** del proyecto es un XML compatible con CTP que enumera cada etiqueta DICOM conocida y qué hacer con ella. El valor predeterminado empaquetado sigue el perfil DICOM Basic Application Confidentiality descrito en [Protocolo de desidentificación](../deidentification-protocol.md).

Abra **Archivo → Ajustes del Proyecto** (o Configuración de Nuevo Proyecto) y pulse **Editar script del anonimizador**. En un proyecto nuevo también puede **Examinar** primero otra plantilla `.script`.

#### Vistas

| Vista | Qué ve |
| --- | --- |
| **Activos** (predeterminada) | Etiquetas **conservadas** o **transformadas** (no `@remove()`). La lista cotidiana — unas 1,5k filas en lugar de ~4,6k. |
| **Eliminados** | Etiquetas con `@remove()` (se borran al anonimizar). |
| **Todos** | Todas las reglas de etiqueta del script. |

La búsqueda y el filtro de **Operando** se aplican dentro de la vista actual. La lista está **paginada** (Anterior / Siguiente) para mantener la ventana ágil.

#### Cambiar una regla

1. Seleccione una fila de la lista.
2. Edite **Nombre** (solo etiqueta) u **Operando** en el panel de detalle.
3. Operandos admitidos: **Mantener**, **Eliminar**, **Vaciar**, **UID**, **ID de paciente**, **Accession**, **Hashear fecha**, **Buscar ID de paciente**, **Buscar desplazamiento de fecha**, **Redondear edad** (con parámetro de anchura).
4. Elegir **Eliminar** saca la etiqueta de la vista Activos (sigue en el script como `@remove()`).

#### Añadir una etiqueta (camino habitual)

1. Pulse **Añadir desde eliminados…**.
2. Busque en la lista de eliminados y seleccione una etiqueta ya conocida por el script.
3. Elija el operando inicial (predeterminado **Mantener**) → **Añadir**.
4. La etiqueta aparece en **Activos** y queda seleccionada para más ediciones.

Use **Añadir desde diccionario…** solo si la etiqueta **no** está ya en el script (poco frecuente). La búsqueda del diccionario está limitada y con retardo.

#### Guardar

- **Aceptar** valida operandos, escribe una copia privada en `{almacenamiento}/private/{site_id}-anonymizer.script`, recarga las reglas activas y actualiza Ajustes del Proyecto. El recurso empaquetado predeterminado no se sobrescribe.
- **Revertir** recarga el archivo desde el disco y descarta cambios no guardados.
- **Cancelar** cierra sin guardar.

!!! tip "Tablas de búsqueda y el script"
    Cargar una **Tabla de búsqueda de pacientes** también puede reescribir operandos de Patient ID / fecha a `@lookup(...)`. Edite el script después si necesita más cambios a nivel de etiqueta.

### Tabla de búsqueda de pacientes

Mapeo opcional CTP `.properties` de IDs PHI de paciente a IDs anonimizados y desplazamientos de fecha. Examinar → vista previa → Aceptar.

!!! note "Proyectos existentes"
    Cargar una tabla de búsqueda **no** vuelve a anonimizar los archivos ya presentes en el conjunto de datos — permanecen sin cambios. Los pacientes ya importados siguen funcionando sin una fila en la tabla. Los archivos **nuevos** cuyo ID de paciente PHI no esté en la tabla se ponen en cuarentena como **Lookup_Miss** y no se almacenan.

![Tabla de búsqueda](shots/macos/LookupTable.png)

### Niveles de Registro

Suba el registro del anonimizador / red al solucionar problemas con TI.

![Niveles de Registro](shots/macos/LoggingLevels.png)

## Panel de control tras crear

![Panel de control](shots/macos/Dashboard.png)

El Panel de control muestra los botones principales del flujo: **Buscar**, **Vista** y **Enviar**.

## Si falla

- Ruta de almacenamiento no escribible → elija otra carpeta.
- Nombre demasiado largo → acorte el nombre del proyecto.
- Aviso al clonar sobre Raíz UID → use una raíz única por proyecto para evitar choques de ID.
- El editor del script **Aceptar** rechazó → corrija los operandos `@…` no admitidos indicados en el error (los literales sin `@`, como constantes CTP raras, están permitidos).

## Siguientes pasos

Continúe con [Buscar](../06-search/) para importar estudios al proyecto.
