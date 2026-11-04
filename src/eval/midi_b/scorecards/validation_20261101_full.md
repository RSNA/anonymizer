# MIDI-B scorecard — Synthetic Validation (full)

**Final score: 99.03%**

| Field | Value |
| --- | --- |
| Split | Synthetic Validation (full) |
| Source run | `validation_20261101T154826Z_full` |
| Commit | `6afbe5c` (2026-11-02) |
| Scorer | Official MIDI validation `Score` (Pass / Total) from `scoring_report_instance.xlsx` Scoring sheet |
| Project | `eval.midi_b` assets: Retain stack + Retain TCIA Research; Retain Device Identity off |
| AI batch | Embedded PHI (pixel + metadata + reports) |

Known residual fails dominated by source / answer-key mismatches: see
[source_answer_errors.md](source_answer_errors.md).

## By action

| Action | Pass | Fail | Total | Fail % |
|---|---:|---:|---:|---:|
| `<text_retained>` | 3398108 | 55431 | 3453539 | 0.90% |
| `<tag_retained>` | 1098934 | 2157 | 1101091 | 0.03% |
| `<text_removed>` | 341535 | 2048 | 343583 | 0.03% |
| `<text_notnull>` | 618460 | 79 | 618539 | 0.00% |
| `<uid_consistent>` | 234386 | 32 | 234418 | 0.00% |
| `<uid_changed>` | 234386 | 32 | 234418 | 0.00% |
| `<pixels_hidden>` | 13 | 22 | 35 | 0.00% |
| `<pixels_retained>` | 23881 | 5 | 23886 | 0.00% |
| `<patid_consistent>` | 23921 | 0 | 23921 | 0.00% |
| `<date_shifted>` | 139774 | 0 | 139774 | 0.00% |
| **Total** | **6113398** | **59806** | **6173204** | **0.97%** |

## Top failing tags by action

### `<text_retained>` — 55431 fails / 3453539 (1.61% fail rate)

| Tag | Name | Fails |
|---|---|---:|
| `<(0009,"GEMS_PETD_01",b8)>` | `<[PET ir_loop_filt_parm]>` | 8226 |
| `<(0009,"GEMS_PETD_01",b2)>` | `<[PET ir_num_iterations]>` | 6016 |
| `<(0009,"GEMS_PETD_01",b3)>` | `<[PET ir_num_subsets]>` | 6016 |
| `<(0009,"GEMS_PETD_01",b6)>` | `<[PET ir_loop_filter]>` | 6016 |
| `<(0009,"GEMS_PETD_01",ba)>` | `<[PET post_filter]>` | 6016 |
| `<(0009,"GEMS_PETD_01",c6)>` | `<[PET seg_qc_parm]>` | 2538 |
| `<(0009,"GEMS_PETD_01",e9)>` | `<[PET acq_bin_dur_percent]>` | 2538 |
| `<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",24)>[<0000>]<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",c0)>` | `<Private tag data>` | 700 |
| `<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",24)>[<0000>]<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",c1)>` | `<Private tag data>` | 700 |
| `<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",24)>[<0000>]<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",c2)>` | `<Private tag data>` | 700 |
| `<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",24)>[<0000>]<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",c3)>` | `<Private tag data>` | 700 |
| `<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",24)>[<0001>]<(0117,"UCSF BIRP PRIVATE CREATOR 011710XX",c0)>` | `<Private tag data>` | 700 |

### `<tag_retained>` — 2157 fails / 1101091 (0.20% fail rate)

| Tag | Name | Fails |
|---|---|---:|
| `<(0020,1040)>` | `<Position Reference Indicator>` | 878 |
| `<(0018,0060)>` | `<KVP>` | 601 |
| `<(0020,0012)>` | `<Acquisition Number>` | 601 |
| `<(0008,0068)>` | `<Presentation Intent Type>` | 25 |
| `<(2050,0020)>` | `<Presentation LUT Shape>` | 25 |
| `<(0018,1000)>` | `<Device Serial Number>` | 20 |
| `<(0018,7004)>` | `<Detector Type>` | 6 |
| `<(0018,5101)>` | `<View Position>` | 1 |

### `<text_removed>` — 2048 fails / 343583 (0.60% fail rate)

| Tag | Name | Fails |
|---|---|---:|
| `<(0009,"GEMS_PETD_01",37)>` | `<[PET batch_description]>` | 547 |
| `<(0010,21b0)>` | `<Additional Patient History>` | 304 |
| `<(0010,2000)>` | `<Medical Alerts>` | 292 |
| `<(0032,4000)>` | `<Study Comments>` | 286 |
| `<(0040,0275)>[<0000>]<(0040,0007)>` | `<Scheduled Procedure Step Description>` | 162 |
| `<(0008,1030)>` | `<Study Description>` | 125 |
| `<(0020,0011)>` | `<Series Number>` | 114 |
| `<(0018,a001)>[<0000>]<(0008,1040)>` | `<Institutional Department Name>` | 90 |
| `<(0029,"SIEMENS MEDCOM HEADER",31)>` | `<[PMTF Information 1]>` | 64 |
| `<(0040,a123)>` | `<Person Name>` | 31 |
| `<(0020,4000)>` | `<Image Comments>` | 16 |
| `<(0040,a730)>[<0003>]<(0040,a160)>` | `<Text Value>` | 2 |

### `<text_notnull>` — 79 fails / 618539 (0.01% fail rate)

| Tag | Name | Fails |
|---|---|---:|
| `<(0008,0068)>` | `<Presentation Intent Type>` | 25 |
| `<(2050,0020)>` | `<Presentation LUT Shape>` | 25 |
| `<(0018,1000)>` | `<Device Serial Number>` | 20 |
| `<(0020,0062)>` | `<Image Laterality>` | 8 |
| `<(0020,0011)>` | `<Series Number>` | 1 |

### `<uid_consistent>` — 32 fails / 234418 (0.01% fail rate)

| Tag | Name | Fails |
|---|---|---:|
| `<(0040,a504)>[<0000>]<(0008,0118)>` | `<Mapping Resource UID>` | 10 |
| `<(0040,a730)>[<0004>]<(0040,a504)>[<0000>]<(0008,0118)>` | `<Mapping Resource UID>` | 10 |
| `<(0040,a730)>[<0005>]<(0040,a730)>[<0000>]<(0040,a504)>[<0000>]<(0008,0118)>` | `<Mapping Resource UID>` | 10 |
| `<(0008,0110)>[<0000>]<(0008,010c)>` | `<Coding Scheme UID>` | 2 |

### `<uid_changed>` — 32 fails / 234418 (0.01% fail rate)

| Tag | Name | Fails |
|---|---|---:|
| `<(0040,a504)>[<0000>]<(0008,0118)>` | `<Mapping Resource UID>` | 10 |
| `<(0040,a730)>[<0004>]<(0040,a504)>[<0000>]<(0008,0118)>` | `<Mapping Resource UID>` | 10 |
| `<(0040,a730)>[<0005>]<(0040,a730)>[<0000>]<(0040,a504)>[<0000>]<(0008,0118)>` | `<Mapping Resource UID>` | 10 |
| `<(0008,0110)>[<0000>]<(0008,010c)>` | `<Coding Scheme UID>` | 2 |

### `<pixels_hidden>` — 22 fails / 35 (62.86% fail rate)

| Tag | Name | Fails |
|---|---|---:|
| `None` | `(none)` | 22 |

### `<pixels_retained>` — 5 fails / 23886 (0.02% fail rate)

| Tag | Name | Fails |
|---|---|---:|
| `None` | `(none)` | 5 |
