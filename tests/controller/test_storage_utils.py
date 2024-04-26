from utils.storage import JavaAnonymizerExportedStudy, read_java_anonymizer_index_xlsx


def test_read_java_anonymizer_index_xlsx(temp_dir: str, controller):
    index_file = "tests/controller/assets/JavaGeneratedIndex.xlsx"
    studies: list[JavaAnonymizerExportedStudy] = read_java_anonymizer_index_xlsx(index_file)
    assert studies
    assert len(studies) == 13
    assert studies[0].ANON_PatientName == "527408-000001"
    assert studies[0].ANON_PatientID == "527408-000001"
    assert studies[12].ANON_PatientName == "527408-000013"
    assert studies[12].ANON_PatientID == "527408-000013"
