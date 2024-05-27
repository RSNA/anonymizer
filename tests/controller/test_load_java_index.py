from utils.storage import JavaAnonymizerExportedStudy, read_java_anonymizer_index_xlsx
from controller.anonymizer import AnonymizerController


def test_read_java_anonymizer_index_xlsx(temp_dir: str, controller):
    index_file = "tests/controller/assets/JavaGeneratedIndex.xlsx"
    studies: list[JavaAnonymizerExportedStudy] = read_java_anonymizer_index_xlsx(index_file)
    assert studies
    assert len(studies) == 112
    assert studies[0].ANON_PatientName == "527408-000001"
    assert studies[0].ANON_PatientID == "527408-000001"
    assert studies[0].PHI_PatientName == "TEST"
    assert studies[0].PHI_PatientID == "999"
    assert studies[69].PHI_PatientName == "Mary Martinez"
    assert studies[69].PHI_PatientID == "574856-000200"


def test_load_java_index_into_new_project(temp_dir: str, controller):
    index_file = "tests/controller/assets/JavaGeneratedIndex.xlsx"
    studies: list[JavaAnonymizerExportedStudy] = read_java_anonymizer_index_xlsx(index_file)

    controller.anonymizer.model.process_java_phi_studies(studies)
    assert controller.anonymizer.model.get_patient_id_count() == 83
    assert controller.anonymizer.model.get_phi_name("527408-000001") == "TEST"
