# DICOM tests

```
tests/controller/dicom/
├── conftest.py          # session-scoped managed Orthanc
├── support/             # PACS simulator, Orthanc bundle, helpers, nodes
├── dimse/               # C-ECHO / C-STORE / C-FIND / C-GET / C-MOVE
│   ├── test_echo.py
│   ├── test_store_scp.py
│   ├── test_store_find.py
│   ├── test_find_edges.py
│   ├── test_retrieve_preference.py   # C-GET vs C-MOVE selection
│   ├── test_retrieve_move.py
│   └── test_orthanc_e2e.py           # dicom_integration
└── dicomweb/            # QIDO-RS / STOW-RS / WADO-RS
    ├── test_unit.py                  # mocked HTTP (+ multipart WADO)
    └── test_orthanc_e2e.py           # dicom_integration
```

```bash
pytest tests/controller/dicom -q
pytest tests/controller/dicom/dimse -q
pytest tests/controller/dicom/dicomweb -q
pytest tests/controller/dicom -m 'not dicom_integration' -q
```
