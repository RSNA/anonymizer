from pathlib import Path
import threading
from time import perf_counter

from anonymizer.controller.project import ProjectController
from anonymizer.model.anonymizer import PHI, AnonymizerModel, Series, Study

# patient, study, series


def generator(model: AnonymizerModel, num_patients=100, num_studies_per_patient=100, num_series_per_study=100):
    for patient in range(1, num_patients):
        studies = []  # studies for each patient
        for study in range(1, num_studies_per_patient):
            series = []  # series for each study
            for serie in range(1, num_series_per_study):
                # Generate new serie
                new_serie = Series(
                    series_uid=f"serie_{serie}", series_desc="X" * 1024, modality="X" * 1024, instance_count=10
                )
                series.append(new_serie)
            # Generate new study
            new_study = Study(
                study_uid=f"study_{study}",
                source="X" * 1024,
                study_date="X" * 1024,
                anon_date_delta=0,
                accession_number="X" * 1024,
                study_desc="X" * 1024,
                series=series,
            )
            studies.append(new_study)
        # Create new patient and save the studies
        model._phi_lookup[f"patient_{patient}"] = PHI(studies=studies)

    return model


# Commented out as it does not work outside of the tests directory and it not used as an actual unit test, rather as a proof on concept
# def test_AnonymizerModel_save_timings(temp_dir: str, controller: ProjectController) -> None:

# """Save patients data to test the impact of saving large files to disk"""
# model: AnonymizerModel = controller.anonymizer.model

# print("Is on main thread: ", threading.current_thread() is threading.main_thread())

# start_time = perf_counter()
# # 100, 100, 3000 for 1GB
# generator(model=model, num_patients=10, num_series_per_study=10, num_studies_per_patient=30)
# duration = perf_counter() - start_time
# print(f"Generator duration: {duration:.6f} seconds")

# print("Is on main thread: ", threading.current_thread() is threading.main_thread())

# start_time = perf_counter()
# model_filename = Path(temp_dir)
# assert model.save(model_filename)
# duration = perf_counter() - start_time
# print(f"Model save duration: {duration:.6f} seconds")

# print("Is on main thread: ", threading.current_thread() is threading.main_thread())

# # 51s, 120s, 70s, 86s, 120s
