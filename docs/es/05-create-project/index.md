# Crear un proyecto

Un **proyecto** mantiene juntos los ajustes y el almacenamiento anonimizado. Créelo una vez en la ventana de escritorio, aunque un servidor ejecute después el modo [sin interfaz](../10-headless/index.md).

En la pantalla **Bienvenido**, elija **Archivo → Nuevo Proyecto** y recorra **Configuración de Nuevo Proyecto** **de arriba abajo** (el mismo orden que el diálogo).

## Objetivo

Crear un proyecto con identidad del sitio, servidores de red, almacenamiento (directorio y qué estudios aceptar), opciones de desidentificación y registro, acordados con TI.

## 1. Identidad del proyecto

En Bienvenido, elija **Archivo → Nuevo Proyecto**.

![Archivo → Nuevo Proyecto en Bienvenido](shots/macos/NewProject_Menu.png)

En **Configuración de Nuevo Proyecto**:

- Defina el **Nombre del Proyecto** (corto, menos de 16 caracteres).
- Revise el **ID del Sitio** — se rellena automáticamente desde el reloj (un número corto a partir de intervalos de 30 minutos desde 1970) para que cada proyecto nuevo tenga su propio código de sitio; aquí no se puede editar. Si usa **Cargar Archivo de Índice JAVA**, el ID del Sitio se toma de ese índice.
- Revise la **Raíz UID** — la base fija de RSNA usada para construir nuevos UID DICOM anonimizados. Deje el valor predeterminado para un sitio nuevo. Si usa **Cargar Archivo de Índice JAVA**, la Raíz UID se extrae de los UID de estudio anonimizados de ese archivo (junto con el ID del Sitio) para continuar el mismo sitio.

## 2. Ajustes del proyecto

**Configuración de Nuevo Proyecto** es el diálogo de abajo. Configúrelo de arriba abajo; las secciones numeradas siguientes siguen este diseño.

![Configuración de Nuevo Proyecto](shots/macos/NewProjectSettings.png)

## 3. Servidores de red {#3-network-and-modalities}

### Cuando hable con TI {#when-you-talk-to-it}

Comparta estas ideas (los detalles están en los diálogos siguientes):

- **Servidor Local** — dirección, puerto y AE Title que este ordenador usa para **recibir** imágenes.
- **Servidor de Consulta** — el archivo hospitalario desde el que busca y recupera.
- **Servidor de Exportación** o **AWS** — adónde se enviarán los estudios anonimizados.
- **Tiempos de espera de red** — cuánto esperar ante archivos lentos.

Si el proyecto vivirá en un servidor de laboratorio, continúe con [Ejecutar sin interfaz](../10-headless/index.md).

### Servidor Local

Dirección, puerto y AE Title que este ordenador usa para **recibir** imágenes.

![Servidor Local](shots/macos/LocalServer.png)

### Servidor de Consulta

Archivo hospitalario para consulta / recuperación.

![Servidor de Consulta](shots/macos/QueryServer.png)

Para remotos que hablan **DICOMweb**, abra el diálogo del Servidor de Consulta y active **DICOMweb**. Introduzca **Puerto HTTP**, **Ruta** (por ejemplo `/dicom-web`), **Use HTTPS** opcional y usuario/contraseña opcionales. La consulta usa entonces QIDO-RS y la recuperación WADO-RS. El puerto DIMSE y el AE Title siguen para **Echo** y servidores dual-stack. Echo sigue usando DIMSE.

### Servidor de Exportación

Destino DICOM usado cuando **Enviar** (la etiqueta de ajustes puede seguir diciendo Export Server).

![Servidor de Exportación](shots/macos/ExportServer.png)

Con **DICOMweb** activado en el Servidor de Exportación, Enviar usa STOW-RS en lugar de C-STORE.

### AWS Cognito (opcional)

Credenciales para Enviar a S3 cuando esté habilitado.

![AWS Cognito](shots/macos/AWSCognito.png)

### Tiempos de Espera de Red {#network-timeouts}

Cuánto esperar ante archivos lentos.

![Tiempos de Espera de Red](shots/macos/NetworkTimeouts.png)

## 4. Almacenamiento {#storage-classes}

### Directorio de almacenamiento

Elija el **Directorio de Almacenamiento** donde vivirán los archivos anonimizados de este proyecto (por defecto sigue el Nombre del Proyecto bajo Documentos / RSNA Anonymizer).

### Modalidades / Clases de Almacenamiento / Sintaxis de Transferencia

Estos tres ajustes deciden qué estudios aceptará este proyecto al buscar en un archivo remoto, al recibir por red o al traer archivos desde el disco.

**Modalidades** — tipos de estudio como CT, MR o US. Al cambiar las modalidades se rellenan inicialmente las **Clases de Almacenamiento** correspondientes.

![Modalidades](shots/macos/Modalities.png)

**Clases de Almacenamiento** — los tipos de objeto DICOM que el anonimizador **aceptará** (por ejemplo CT Image Storage). La lista se **establece inicialmente a partir de las modalidades seleccionadas**, pero puede editarla después (añadir o quitar clases). Los archivos cuya clase de almacenamiento no esté en esta lista no se anonimizan en el proyecto — van a cuarentena.

![Clases de Almacenamiento](shots/macos/StorageClasses.png)

**Sintaxis de Transferencia** — cómo se codifican los píxeles al llegar o al guardarse:

- Las codificaciones **sin comprimir** conservan cada muestra tal cual. Los archivos ocupan más disco.
- Las codificaciones **comprimidas** (JPEG, JPEG 2000 y similares) reducen el tamaño; el mismo estudio ocupa menos espacio.

El proyecto conserva cada archivo en la sintaxis de transferencia que ya tiene. La **transcodificación** de una sintaxis a otra **no está habilitada** hoy — elija las sintaxis que ya usan sus fuentes (y que quiere conservar en disco).

![Sintaxis de Transferencia](shots/macos/TransferSyntaxes.png)

## 5. Opciones de desidentificación {#2-de-identification-options}

Abra **Opciones de desidentificación**. Las opciones de desidentificación son las decisiones de confidencialidad DICOM de [PS 3.15 Apéndice E](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) (Basic Profile, Modified Dates, Retain Safe Private y opciones relacionadas). Aparecen con sus nombres estándar en **De-identification Options**.

![Opciones de desidentificación](shots/macos/DeidentificationOptions.png)

### Ajustes predefinidos

| Ajuste | Qué selecciona |
| --- | --- |
| **Basic** | Solo Basic Profile |
| **Retain** | Basic Profile + Modified Dates + Patient Characteristics + Retain Safe Private |

Los ajustes predefinidos solo marcan las casillas. El proyecto almacena los **códigos de opción seleccionados**, no el nombre del ajuste.

### Cómo las opciones construyen el script del anonimizador

Al crear (y siempre que **Acepte** nuevas opciones en un proyecto existente), la aplicación **compila** el script del anonimizador del proyecto:

- Parte del `default-anonymizer.script` empaquetado.
- Aplica **superposiciones de opción** por cada opción de confidencialidad elegida (qué etiquetas conservar, eliminar o transformar).
- Escribe el resultado como `{site_id}-anonymizer.script` privado del proyecto junto a `ProjectModel.json`.

El proyecto usa **solo ese script** para la anonimización de etiquetas (no NER/OCR). El lenguaje completo de reglas y las etiquetas de sello están en [Protocolo de desidentificación](../deidentification-protocol.md). Los revisores que busquen la lista PS 3.15 § E.1.3 deben usar la [Declaración de conformidad DICOM](../dicom-conformance-statement.md).

!!! warning "Cambiar opciones más tarde"
    En un proyecto **existente**, aplicar opciones distintas pide confirmación. **Aceptar** **recompila** desde el predeterminado empaquetado más superposiciones — **se pierden las ediciones personalizadas del script**. Los archivos ya almacenados en el proyecto no se vuelven a procesar.

### Opciones de limpieza y modalidades

Las opciones de limpieza (Clean Pixel Data, Clean Structured Content, Clean Descriptors, Clean Recognizable Visual Features) solo pueden elegirse si la función de IA correspondiente está instalada — se le ofrecerá descargar el modelo. Elegir Clean Structured Content o Clean Descriptors habilita modalidades SR/PDF; habilitar de nuevo SR o PDF activa Clean Structured Content si estaba desactivado.

La limpieza de píxeles, informes y caras sigue usando las herramientas opcionales de [Procesar](../08-process/index.md) cuando hay esos objetos. Véase [Protocolo de desidentificación](../deidentification-protocol.md#pixel-and-face-options-in-the-dicom-profile).

La mayoría de los sitios nunca editan el script compilado a mano. Reglas de etiqueta avanzadas, estrategias de fechas y tablas de búsqueda: [Script del anonimizador (avanzado)](anonymizer-script.md).

## 6. Registro


Suba el registro del anonimizador / red al solucionar problemas con TI.

![Niveles de Registro](shots/macos/LoggingLevels.png)

## Crear el proyecto

Cuando los ajustes estén listos, elija **Crear Proyecto**. El script compilado del anonimizador se guarda junto a `ProjectModel.json` como `{site_id}-anonymizer.script`. Se abre el **Panel de control**.

![Panel de control](shots/macos/Dashboard.png)

## Después de crear

| Acción | Cómo |
| --- | --- |
| Cerrar | **Archivo → Cerrar Proyecto** o cierre la ventana |
| Clonar ajustes | **Archivo → Clonar** en una carpeta de almacenamiento nueva (no se copian imágenes). Mantenga la Raíz UID única entre proyectos. |

## Cómo se ve cuando va bien

- El Panel de control muestra el nombre del proyecto y el ID del Sitio.
- El directorio de almacenamiento existe y es escribible.
- Las opciones de desidentificación coinciden con su plan de privacidad; `{site_id}-anonymizer.script` existe junto a `ProjectModel.json`.
- Los diálogos de red y modalidad coinciden con lo que TI espera para este centro.

## Si falla

- Ruta de almacenamiento no escribible → elija otra carpeta.
- Nombre demasiado largo → acorte el nombre del proyecto.
- Aviso al clonar sobre Raíz UID → use una raíz única por proyecto para evitar choques de ID.

## Siguientes pasos

Continúe con [Buscar](../06-search/index.md).
