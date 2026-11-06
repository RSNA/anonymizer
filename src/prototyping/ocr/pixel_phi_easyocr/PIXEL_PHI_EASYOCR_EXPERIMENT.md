# Pixel PHI EasyOCR experiment log

Tune `readtext` kwargs for MIDI-B `pixel_phi` gold boxes. Prefer ≥95% case accuracy at **relative_cost ≤ product baseline** (~3.0 for non-US with rotation TTA). Promote winners into `detect_text._easyocr_readtext`.

## eval 2026-11-02T12:29:12.503173+00:00

### `product_baseline` → **FAIL** (case_acc=64.5% 40/62; box_recall=64.5% 40/62; rel_cost=3.00)
overrides={}
failures (showing 12 of 22):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '14']
- validation/5220588395 DX: miss=['MWF'] raw=['ERECT', '3', '2', 'POPTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', 'PORTABLE', '#6']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', 'PORTABLE', '#6']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', 'G']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', 'PORTABLE', '1']
- validation/3615823051 DX: miss=['MSS'] raw=['BEMIL-ERECT', 'PORTABLE', '1']

## corpus sweep 2026-11-02T13:50:20.663129+00:00

manifest=`/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/manifest.json` n_cases=62 n_configs=16 target=95% max_rel_cost=3.50

memory: one frame at a time; torch cache cleared after each image

### `product_baseline:product_baseline` → **FAIL** (case_acc=67.7% 42/62; box_recall=67.7% 42/62; rel_cost=3.00)
overrides={}
failures (showing 12 of 20):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '14']
- validation/5220588395 DX: miss=['MWF'] raw=['ERECT', '3', '2', 'POPTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', 'PORTABLE', '#6']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', 'PORTABLE', '#6']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['7', '2']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', 'G']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', 'PORTABLE', '1']
- validation/5454430957 CR: miss=['MHS'] raw=['R', '4', '2']

### `rot_none_cheaper:{"rotation_info":[]}` → **FAIL** (case_acc=80.6% 50/62; box_recall=80.6% 50/62; rel_cost=1.00)
overrides={'rotation_info': []}
failures (showing 12 of 12):
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', 'REIT']
- validation/5220588395 DX: miss=['MWF'] raw=['OEA', 'ERECT', 'NRUYNH', 'POPTABLE']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['J', '7XM']
- validation/3056777156 CR: miss=['CMS'] raw=['EVA']
- validation/3056777156 CR: miss=['CMS'] raw=['2VJ']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', '1', 'PORTABLE']
- validation/6208874732 DX: miss=['ROC'] raw=['R8C']
- validation/6208874732 DX: miss=['ROC'] raw=['RQC']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGH', '242', 'PORTABLE']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHT', '142', 'PORTABLE', '1']
- test/113575183 CR: miss=['FTA'] raw=['PORTABLE', 'SEMI-ERECT', 'UOD', '7 33']

### `rot_90_only:{"rotation_info":[90]}` → **FAIL** (case_acc=74.2% 46/62; box_recall=74.2% 46/62; rel_cost=2.00)
overrides={'rotation_info': [90]}
failures (showing 12 of 16):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', 'UT']
- validation/5220588395 DX: miss=['MWF'] raw=['ERECT', '3', '2', 'POPTABLE']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['7', '1']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['2']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', 'PORTABLE', '1']
- validation/5454430957 CR: miss=['MHS'] raw=['R', '4', '10 0 0']
- validation/6208874732 DX: miss=['ROC'] raw=['R8C']
- validation/6208874732 DX: miss=['ROC'] raw=['8']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHT', '242', 'PORTABLE']

### `margin_0.15:{"add_margin":0.15}` → **FAIL** (case_acc=62.9% 39/62; box_recall=62.9% 39/62; rel_cost=3.00)
overrides={'add_margin': 0.15}
failures (showing 12 of 23):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5864436320 CR: miss=['SWU'] raw=['3', 'SEMI-ERECT', 'PORTABLE']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '2']
- validation/5220588395 DX: miss=['MWF'] raw=['ERECT', '3', '2', 'PORTABLE']
- validation/2051580196 CR: miss=['NKF'] raw=['7MV']
- validation/2051580196 CR: miss=['NKF'] raw=['7', '7XM']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', 'G']
- validation/3031860897 CR: miss=['CEF'] raw=['PORTABLE', '4', 'UPRIGHT']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['SEMIL-ERECT', 'PORTABLE', '1']
- validation/3615823051 DX: miss=['TJN'] raw=['PORTABLE', 'SEMI-ERECT', '2/2', '3', 'PORTABLE', '#6']

### `margin_0.2:{"add_margin":0.2}` → **FAIL** (case_acc=67.7% 42/62; box_recall=67.7% 42/62; rel_cost=3.00)
overrides={'add_margin': 0.2}
failures (showing 12 of 20):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5864436320 CR: miss=['SWU'] raw=['5', '8', 'PORTABLE']
- validation/5220588395 DX: miss=['MWF'] raw=['ERECT', '2', '2', 'PORTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['8', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', '#6', 'PORTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['8', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', '#6', 'PORTABLE']
- validation/2051580196 CR: miss=['NKF'] raw=['1']
- validation/2051580196 CR: miss=['NKF'] raw=['7', '=']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', 'G']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['SEML-ERECT', 'PORTABLE', '1']
- validation/5454430957 CR: miss=['MHS'] raw=['R', '#', '2']

### `width_0.05:{"width_ths":0.05}` → **FAIL** (case_acc=67.7% 42/62; box_recall=67.7% 42/62; rel_cost=3.00)
overrides={'width_ths': 0.05}
failures (showing 12 of 20):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '14']
- validation/5220588395 DX: miss=['MWF'] raw=['ERECT', '3', '2', 'POPTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', 'PORTABLE', '#6']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', 'PORTABLE', '#6']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['7', '2']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', 'G']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', 'PORTABLE', '1']
- validation/5454430957 CR: miss=['MHS'] raw=['R', '4', '2']

### `width_0.2:{"width_ths":0.2}` → **FAIL** (case_acc=64.5% 40/62; box_recall=64.5% 40/62; rel_cost=3.00)
overrides={'width_ths': 0.2}
failures (showing 12 of 22):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/527545790 MG: miss=['BELL AUSTIN [U] 02.29.2012'] raw=['|', 'DOB: 01.24.1964', 'RCC']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '14']
- validation/5220588395 DX: miss=['MWF'] raw=['SEMLERECT', '2', 'POPTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', '1']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', '1']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['7', '2']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', 'G']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', 'PORTABLE', '1']

### `text_0.55_low_0.35:{"low_text":0.35,"text_threshold":0.55}` → **FAIL** (case_acc=64.5% 40/62; box_recall=64.5% 40/62; rel_cost=3.00)
overrides={'text_threshold': 0.55, 'low_text': 0.35}
failures (showing 12 of 22):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '124']
- validation/5220588395 DX: miss=['MWF'] raw=['SEMLERECT', '2', 'PORTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', '001', 'INTRA', 'OP', 'SUPINE', 'PORTABLE #6']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', '001', 'INTRA', 'OP', 'SUPINE', 'PORTABLE #6']
- validation/2051580196 CR: miss=['NKF'] raw=['1']
- validation/2051580196 CR: miss=['NKF'] raw=['J', '7XM']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', '8']
- validation/3031860897 CR: miss=['CEF'] raw=['PORTABLE', '9', 'UPRIGHT', '2']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['BEML-ERECT', 'PORTABLE', '1']

### `contrast_mild:{"adjust_contrast":0.7,"contrast_ths":0.05}` → **FAIL** (case_acc=67.7% 42/62; box_recall=67.7% 42/62; rel_cost=3.00)
overrides={'contrast_ths': 0.05, 'adjust_contrast': 0.7}
failures (showing 12 of 20):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '14']
- validation/5220588395 DX: miss=['MWF'] raw=['ERECT', '3', '2', 'POPTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', 'PORTABLE', '#6']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA', 'OP', 'SUPINE', 'PORTABLE', '#6']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['7', '2']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', 'G']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', 'PORTABLE', '1']
- validation/5454430957 CR: miss=['MHS'] raw=['R', '4', '2']

### `cheap_combo_margin_width_text:{"add_margin":0.15,"low_text":0.35,"text_threshold":0.55,"width_ths":0.05}` → **FAIL** (case_acc=62.9% 39/62; box_recall=62.9% 39/62; rel_cost=3.00)
overrides={'add_margin': 0.15, 'width_ths': 0.05, 'text_threshold': 0.55, 'low_text': 0.35}
failures (showing 12 of 23):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '81']
- validation/5220588395 DX: miss=['MWF'] raw=['SEMILERECT', '2', 'PORTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['5', 'PORTABLE', '83', 'INTRA', 'OP', 'SUPINE', 'PORTABLE #6']
- validation/8697164365 DX: miss=['ICG'] raw=['5', 'PORTABLE', '83', 'INTRA', 'OP', 'SUPINE', 'PORTABLE #6']
- validation/2051580196 CR: miss=['NKF'] raw=['7V']
- validation/2051580196 CR: miss=['NKF'] raw=['7', '7XM']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', '8']
- validation/3031860897 CR: miss=['CEF'] raw=['PORTABLE', '9', 'UPRIGHT', '09']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['SEMIL-ERECT', 'PORTABLE', '1']

### `cheap_combo_plus_contrast:{"add_margin":0.2,"adjust_contrast":0.7,"contrast_ths":0.05,"low_text":0.3,"text_threshold":0.55,"width_ths":0.05}` → **FAIL** (case_acc=66.1% 41/62; box_recall=66.1% 41/62; rel_cost=3.00)
overrides={'add_margin': 0.2, 'width_ths': 0.05, 'text_threshold': 0.55, 'low_text': 0.3, 'contrast_ths': 0.05, 'adjust_contrast': 0.7}
failures (showing 12 of 21):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '1A']
- validation/5220588395 DX: miss=['MWF'] raw=['SEMLERECT', '2', 'PORTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['8', 'PORTABLE', '3', 'INTRA', 'OP', 'SUPINE', 'PORTABLE #6']
- validation/8697164365 DX: miss=['ICG'] raw=['8', 'PORTABLE', '3', 'INTRA', 'OP', 'SUPINE', 'PORTABLE #6']
- validation/2051580196 CR: miss=['NKF'] raw=['7XM']
- validation/2051580196 CR: miss=['NKF'] raw=['L', '7XM']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', '18']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['2MJ']
- validation/3615823051 DX: miss=['JGR'] raw=['SEML-ERECT', 'PORTABLE', '1']
- validation/6208874732 DX: miss=['ROC'] raw=['58']

### `rot_none_plus_cheap_combo:{"add_margin":0.2,"adjust_contrast":0.7,"contrast_ths":0.05,"low_text":0.3,"rotation_info":[],"text_threshold":0.55,"width_ths":0.05}` → **FAIL** (case_acc=79.0% 49/62; box_recall=79.0% 49/62; rel_cost=1.00)
overrides={'rotation_info': [], 'add_margin': 0.2, 'width_ths': 0.05, 'text_threshold': 0.55, 'low_text': 0.3, 'contrast_ths': 0.05, 'adjust_contrast': 0.7}
failures (showing 12 of 13):
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', 'JIT']
- validation/5220588395 DX: miss=['MWF'] raw=['SEMLERECT', 'PORTABLE', 'IRNWNN']
- validation/2051580196 CR: miss=['NKF'] raw=['7XM']
- validation/2051580196 CR: miss=['NKF'] raw=['J', '7XM']
- validation/3056777156 CR: miss=['CMS'] raw=['21A']
- validation/3056777156 CR: miss=['CMS'] raw=['2MJ']
- validation/3615823051 DX: miss=['JGR'] raw=['SEML-ERECT', '1', 'PORTABLE']
- validation/6208874732 DX: miss=['ROC'] raw=['R8']
- validation/6208874732 DX: miss=['ROC'] raw=['R8']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHT', '242', 'PORTABLE']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHT', '4/2', 'PORTABLE', '1']
- test/113575183 CR: miss=['FTA'] raw=['0NO', 'PORTABLE', 'SEMI-ERECT', '732']

### `hires_no_tta_1800:{"canvas_size":1800,"rotation_info":[]}` → **FAIL** (case_acc=77.4% 48/62; box_recall=77.4% 48/62; rel_cost=1.50)
overrides={'canvas_size': 1800, 'rotation_info': []}
failures (showing 12 of 14):
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', 'UI']
- validation/5220588395 DX: miss=['MWF'] raw=['QELERECT', '7RRUN', 'PORTABLE']
- validation/2051580196 CR: miss=['NKF'] raw=['7MM']
- validation/2051580196 CR: miss=['NKF'] raw=['7XM']
- validation/1867354909 DX: miss=['YH'] raw=['SPORERBCF', '4']
- validation/3056777156 CR: miss=['CMS'] raw=['EVA']
- validation/3056777156 CR: miss=['CMS'] raw=['2VJ']
- validation/3615823051 DX: miss=['JGR'] raw=['OMILERECT', '1', 'PORTABLE', '1']
- validation/6208874732 DX: miss=['ROC'] raw=['RQC']
- validation/6208874732 DX: miss=['ROC'] raw=['RQC']
- test/8225398083 DX: miss=['RCN'] raw=['UPRICH', '242', 'PORVABLE']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHT', '1E', 'PORTABLE', '1']

### `hires_no_tta_2560:{"canvas_size":2560,"rotation_info":[]}` → **FAIL** (case_acc=80.6% 50/62; box_recall=80.6% 50/62; rel_cost=2.13)
overrides={'canvas_size': 2560, 'rotation_info': []}
failures (showing 12 of 12):
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABL', 'U']
- validation/5220588395 DX: miss=['MWF'] raw=['BEM-ERECT', 'KNRHH', 'POPTABLE']
- validation/2051580196 CR: miss=['NKF'] raw=['7V']
- validation/2051580196 CR: miss=['NKF'] raw=['7XM']
- validation/3056777156 CR: miss=['CMS'] raw=['EVA']
- validation/3056777156 CR: miss=['CMS'] raw=['4', '2VJ']
- validation/3615823051 DX: miss=['JGR'] raw=['OEM-ERECT', '1', 'PORTABLE', '1', '1']
- validation/6208874732 DX: miss=['ROC'] raw=['R8C']
- test/8225398083 DX: miss=['RCN'] raw=['UPACAT', '242', 'POPALABLE']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHT', '142', 'PORTABLE', '1']
- test/3427864259 DX: miss=['CERVANTES CHRISTOPHER [M] 07.09.2014'] raw=['CIIE', 'CTOM', 'LALI', 'ET', 'DOE', 'OEOS', '1930', 'PORTABLE']
- test/113575183 CR: miss=['FTA'] raw=['PORTABLE', 'SEMI-ERECT', 'UOD', '32']

### `hires_no_tta_2560_combo:{"add_margin":0.2,"adjust_contrast":0.7,"canvas_size":2560,"contrast_ths":0.05,"low_text":0.3,"rotation_info":[],"text_threshold":0.55,"width_ths":0.05}` → **FAIL** (case_acc=75.8% 47/62; box_recall=75.8% 47/62; rel_cost=2.13)
overrides={'canvas_size': 2560, 'rotation_info': [], 'add_margin': 0.2, 'width_ths': 0.05, 'text_threshold': 0.55, 'low_text': 0.3, 'contrast_ths': 0.05, 'adjust_contrast': 0.7}
failures (showing 12 of 15):
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', 'UIT']
- validation/5220588395 DX: miss=['MWF'] raw=['SEMLERECT', 'PORTABLE', 'LONWUF']
- validation/2051580196 CR: miss=['NKF'] raw=['7XM']
- validation/2051580196 CR: miss=['NKF'] raw=['J', '7XM', '0']
- validation/3031860897 CR: miss=['CEF'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/3056777156 CR: miss=['CMS'] raw=['2VJ']
- validation/3056777156 CR: miss=['CMS'] raw=[']', '2MJ']
- validation/3615823051 DX: miss=['JGR'] raw=['SEMIL-ERECT', 'PORTABLE', '1']
- validation/6208874732 DX: miss=['ROC'] raw=['R8']
- validation/6208874732 DX: miss=['ROC'] raw=['R8F']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHTT', '212', 'PORTABLE']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHT', '442', 'PORTABLE', '1']

### `hires_keep_tta_1600:{"canvas_size":1600}` → **FAIL** (case_acc=72.6% 45/62; box_recall=72.6% 45/62; rel_cost=4.00)
overrides={'canvas_size': 1600}
failures (showing 12 of 17):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/5864436320 CR: miss=['SWU'] raw=['9', 'SEMI-ERECT', 'PORTABLE']
- validation/5155749005 DX: miss=['JT'] raw=['3', 'PORTABLE']
- validation/5220588395 DX: miss=['MWF'] raw=['BEMLERECT', '2', 'PORITABLE']
- validation/2051580196 CR: miss=['NKF'] raw=['1']
- validation/2051580196 CR: miss=['NKF'] raw=['1']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['OEMILERECT', 'PORTABLE', '1', '1']
- validation/5454430957 CR: miss=['MHS'] raw=['R', '1', 'TA / /', '3']
- validation/6208874732 DX: miss=['ROC'] raw=['8']
- validation/6208874732 DX: miss=['ROC'] raw=['8']


**Best under cost cap 3.50:** `rot_none_cheaper:{"rotation_info":[]}` acc=80.6% box=80.6% cost=1.00 met_target=False

Wrote `/Users/michaelevans/CODE/anonymizer/src/prototyping/ocr/pixel_phi_easyocr/out/sweep_corpus/best_params.json`


## initials_rotation 2026-11-02T14:08:40.989370+00:00

conclusion: FTA recovered on gold crop at +15° deskew. Merge candidate: local fine-angle TTA on free-form / short-marker crops only (not full-image 90° TTA).

```json
{
  "full_frame": {
    "texts": [
      "PORTABLE",
      "SEMI-ERECT",
      "UOD",
      "7 33"
    ],
    "found_fta": false,
    "found_r": true
  },
  "first_angle_fta_gold": 15.0,
  "first_angle_fta_top_left": 15.0,
  "first_angle_r_top_left": 30.0
}
```
## eval 2026-11-03T16:46:26.478024+00:00

### `product_baseline` → **FAIL** (case_acc=59.7% 37/62; box_recall=59.7% 37/62; rel_cost=3.00)
overrides={}
failures (showing 12 of 25):
- validation/333877207 DX: miss=['JT'] raw=['PORTABLE', 'UPRIGHT', '5']
- validation/527545790 MG: miss=['BELL AUSTIN [U] 02.29.2012'] raw=['|', 'DOB: 01.24.1964', 'RCC']
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', '14']
- validation/5220588395 DX: miss=['MWF'] raw=['SEMLERECT', '2', 'POPTABLE']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA OP', 'SUPINE', '1']
- validation/8697164365 DX: miss=['ICG'] raw=['6', 'PORTABLE', 'INTRA OP', 'SUPINE', '1']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['2']
- validation/2548095243 CR: miss=['ACO'] raw=['SEMI-ERECT', 'PORTABLE', 'G']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3056777156 CR: miss=['CMS'] raw=['8']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', 'PORTABLE']

## banner line 7590034066 2026-11-05

Gold line: `JOHNSON MICHELLE [F] 02.10.2012` (CR, 3480×4240). Detail: `out/banner_line_7590034066.json`.

Product defaults (`rotation_info=[90, 270]`, canvas 1200, `width_ths=0.1`) miss the rest of the line. The detector still finds that crop; 90/270 recognition scores `|` at 0.8 and replaces the upright read `MICHELLE [F] 02.10.2012` at 0.7 (`set_result_with_confidence`).

Turning `rotation_info` off, with every other product knob unchanged, returns the full line. Canvas, `text_threshold`, `mag_ratio`, and contrast did not need to move. Those later rows also hit only because they kept rotation off.

## eval 2026-11-05T10:02:41.841686+00:00

### `product_baseline` → **FAIL** (case_acc=80.6% 50/62; box_recall=80.6% 50/62; rel_cost=3.00)
overrides={}
failures (showing 12 of 12):
- validation/5155749005 DX: miss=['JT'] raw=['UPRIGHT', 'PORTABLE', 'REIT', '14']
- validation/5220588395 DX: miss=['MWF'] raw=['OEA', 'ERECT', 'NRUYNH', 'POPTABLE', '3', '2']
- validation/2051580196 CR: miss=['NKF'] raw=['7M']
- validation/2051580196 CR: miss=['NKF'] raw=['7XM', '2']
- validation/3056777156 CR: miss=['CMS'] raw=['EVA', '8']
- validation/3056777156 CR: miss=['CMS'] raw=['2VJ', '8']
- validation/3615823051 DX: miss=['JGR'] raw=['BEMIL-ERECT', 'PORTABLE']
- validation/6208874732 DX: miss=['ROC'] raw=['R8C']
- validation/6208874732 DX: miss=['ROC'] raw=['RQC', '8']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGH', '242', 'PORTABLE', 'UPRIGHT']
- test/8225398083 DX: miss=['RCN'] raw=['UPRIGHT', '142', 'PORTABLE', '1']
- test/113575183 CR: miss=['FTA'] raw=['PORTABLE', 'SEMI-ERECT', 'UOD', '7 33', '8', '8']

