# Protocolo de desidentificación

Esta página resume en lenguaje sencillo cómo el Anonymizer sigue el DICOM Basic Application Confidentiality Profile ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/2023b/output/chtml/part15/chapter_E.html)).

## Qué se elimina o se sustituye

- El nombre y el ID del paciente pasan a valores anonimizados del ámbito del proyecto (ID del Sitio + número secuencial de paciente). La misma persona conserva el mismo ID anonimizado en los estudios del proyecto.
- Los UIDs se sustituyen por valores nuevos derivados para el proyecto (hash de los originales en las versiones actuales) para que los enlaces entre imágenes se mantengan coherentes sin exponer los UIDs de origen.
- Se eliminan muchas etiquetas de flujo clínico y privadas.
- El archivo registra que se eliminó la identidad del paciente y nombra el RSNA DICOM Anonymizer como método.

## Fechas

Las fechas se desplazan por paciente (desplazamiento basado en hash) para que el **orden y el espaciado** de los estudios de un paciente sigan siendo significativos, pero las fechas de calendario no son las originales. La hora del día suele dejarse igual.

## Qué puede conservarse (opciones parciales)

Ejemplos de contexto clínico retenido (según script / opciones de perfil):

- Descripciones de Estudio y Serie (más adelante puede estandarizar nombres de serie con Harmonize)
- Sexo, edad, talla, peso y características similares cuando esté configurado
- Fabricante / modelo cuando esté configurado

## Opciones de píxeles y cara en el perfil DICOM

Las opciones clásicas del perfil “clean pixel data” y “clean recognizable visual features” **no** se reivindican solo como bits automáticos del perfil DICOM. En V19, use en su lugar las Funciones de IA opcionales:

- [Quitar texto quemado](08-process/02-remove-burned-in-text)
- [Desenfocar caras](08-process/04-blur-faces)

## Informes estructurados y superposiciones

Se eliminan los grupos de curva/superposición. Si se aceptan objetos Structured Report lo controlan los ajustes de clase de almacenamiento del proyecto.

!!! note "Para revisión de cumplimiento"
    Pida a su responsable de privacidad que revise el script del anonimizador y las herramientas de IA para su institución. Este manual es orientación operativa, no asesoramiento legal.
