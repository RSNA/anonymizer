## regex_spacy — Open-i seeded NAME/DATE/LOCATION (n=120)

engine=regex_spacy available=True seconds=0.188 openi_fp_on_raw_reports={}

label                       P      R     F1   tp   fp   fn
----------------------------------------------------------
NAME                    1.000  1.000  1.000  120    0    0
DATE                    1.000  1.000  1.000  120    0    0
LOCATION                1.000  1.000  1.000  120    0    0
PATIENT_IDENTIFIER      0.000  0.000  0.000    0    0    0
PHONE                   0.000  0.000  0.000    0    0    0
EMAIL                   0.000  0.000  0.000    0    0    0

## regex_spacy — TCIA SR DATE gold (n=20)

tcia_sr_fp_on_narratives={'DATE': 5}

label                       P      R     F1   tp   fp   fn
----------------------------------------------------------
NAME                    0.000  0.000  0.000    0    0    0
DATE                    1.000  1.000  1.000   20    0    0
LOCATION                0.000  0.000  0.000    0    0    0
PATIENT_IDENTIFIER      0.000  0.000  0.000    0    0    0
PHONE                   0.000  0.000  0.000    0    0    0
EMAIL                   0.000  0.000  0.000    0    0    0

## presidio_transformers — Open-i seeded NAME/DATE/LOCATION (n=120)

engine=presidio_transformers available=True seconds=5.544 openi_fp_on_raw_reports={'NAME': 7}

label                       P      R     F1   tp   fp   fn
----------------------------------------------------------
NAME                    1.000  1.000  1.000  120    0    0
DATE                    1.000  1.000  1.000  120    0    0
LOCATION                1.000  1.000  1.000  120    0    0
PATIENT_IDENTIFIER      0.000  0.000  0.000    0    0    0
PHONE                   0.000  0.000  0.000    0    0    0
EMAIL                   0.000  0.000  0.000    0    0    0

## presidio_transformers — TCIA SR DATE gold (n=20)

tcia_sr_fp_on_narratives={'DATE': 5, 'NAME': 2}

label                       P      R     F1   tp   fp   fn
----------------------------------------------------------
NAME                    0.000  0.000  0.000    0    0    0
DATE                    1.000  1.000  1.000   20    0    0
LOCATION                0.000  0.000  0.000    0    0    0
PATIENT_IDENTIFIER      0.000  0.000  0.000    0    0    0
PHONE                   0.000  0.000  0.000    0    0    0
EMAIL                   0.000  0.000  0.000    0    0    0
