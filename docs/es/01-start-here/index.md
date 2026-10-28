# Empezar aquí

## Qué hace este programa

El RSNA DICOM Anonymizer es una aplicación independiente que **elimina información de identidad protegida** de los estudios de imagen médica y guarda una copia segura para investigación en su ordenador.

Puede traer imágenes desde una carpeta o desde un sistema de imagen hospitalario, revisarlas, aplicar opcionalmente herramientas de IA (texto quemado en píxeles, limpieza de entidades nombradas en texto de informes, nombres estándar de estudio y serie, face blur) y luego enviar los estudios desidentificados a otro sistema o archivo en la nube.

## Objetivo de privacidad

Los nombres de paciente, IDs y otros identificadores en las «etiquetas» del archivo (tags DICOM) se sustituyen o eliminan en la **importación** mediante el script de desidentificación del proyecto. Las fechas se desplazan para que la temporalidad dentro de un paciente sea coherente, pero no sea la fecha de calendario.

Ese recorrido de tags **no** limpia el texto libre de Structured Reports o Encapsulated PDFs, ni borra nombres dibujados en los píxeles. Cuando conserve objetos de informe (Clean Structured Content), debe ejecutar **Revisión de texto de informe** tras la importación: el reconocimiento de entidades nombradas (NER) en inglés encuentra nombres, fechas, IDs, teléfonos y tramos similares en el cuerpo del informe para que pueda vaciarlos o sustituirlos por valores sintéticos. Por separado, las herramientas de IA opcionales pueden ocultar texto quemado en píxeles y desenfocar caras en exámenes de cabeza — porque aún pueden identificar a alguien después de limpiar las etiquetas.

## Normas y pruebas

El script predeterminado sigue el DICOM **Basic Application Confidentiality Profile** ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html)) y las opciones de retención que elija para el proyecto. Ese perfil y el **Medical Image De-Identification Benchmark (MIDI-B)** público de TCIA / NCI están alineados con la eliminación de identificadores de imagen al estilo **HIPAA Safe Harbor** (no es una afirmación de que el producto esté «certificado HIPAA»). La desidentificación de cabeceras se comprueba con el puntuador oficial MIDI-B (véase [Protocolo de desidentificación](../deidentification-protocol.md)). La lista formal PS 3.15 § E.1.3 está en la [Declaración de conformidad DICOM](../dicom-conformance-statement.md). Su responsable de privacidad debe revisar igualmente las opciones y cualquier script personalizado para su centro — este manual es orientación operativa, no un certificado de cumplimiento.

## Para quién es

- Radiólogos e investigadores de imagen que curan conjuntos de datos
- Centros que envían estudios a archivos de investigación

## Dos formas de trabajar


| Modo | Ideal para |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Ventana de escritorio (GUI)** | Crear proyectos, revisar imágenes, herramientas de IA, exportación |
| **Sin ventana (headless)** | Laboratorio/servidor: seguir recibiendo imágenes o ejecutar lotes de IA por la noche — véase [Ejecutar sin interfaz](../10-headless/index.md) |


!!! important "Cree el proyecto primero en la ventana"
    El modo headless usa un proyecto que ya creó y configuró. Empiece por [Crear un proyecto](../05-create-project/index.md) y pida a TI que ejecute headless si hace falta.

## Siguientes pasos

1. [Instalación y primer inicio](../02-install/index.md)
2. [Configuración de Funciones de IA](../03-ai-features-setup/index.md) (desde Bienvenido)
3. [Palabras que usamos](../04-words-we-use/index.md)
4. [Crear un proyecto](../05-create-project/index.md)
