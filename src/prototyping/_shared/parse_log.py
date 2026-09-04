phi_patient_ids = []
phi_study_ids = []
phi_series_ids = []
phi_instance_ids = []

complete_phi_study_ids = []
complete_study_move_operations = []

anon_patient_ids = []
anon_study_ids = []
anon_series_ids = []
anon_instance_ids = []

completed = {}

with open("/Users/michaelevans/Downloads/anonymizer_query.log", "r") as f:
    for line in f:
        if "project._handle_store" in line:
            path = line.split("=>")[1].strip()
            components = path.split("/")
            phi_patient_ids.append(components[0])
            phi_study_ids.append(components[1])
            phi_series_ids.append(components[2])
            phi_instance_ids.append(components[3])

        if "complete study_uid" in line:
            complete_phi_study_ids.append(line.split(":")[-1].strip())

        # query_retrieve_import._monitor_move_response.668 Study Move Complete: uid:1.3.12.2.1107.5.2.31.30134.30000020011512433390600000001, completed:148, failed:0

        if "Study Move Complete:" in line:
            study_uid = line.split("uid:")[1].split(",")[0].strip()
            operations = int(line.split("completed:")[1].split(",")[0].strip())
            completed[study_uid] = operations

        if "=> E:\\Anonymizer2_5" in line:
            path = line.split("=>")[1].strip()
            components = path.split("\\")[2:]
            anon_patient_ids.append(components[0])
            anon_study_ids.append(components[1])
            anon_series_ids.append(components[2])
            anon_instance_ids.append(components[3])

print("incoming phi:", len(phi_patient_ids))
print("unique phi_patient_ids:", len(set(phi_patient_ids)))
print("unique phi_study_ids:", len(set(phi_study_ids)))
print("unique phi_series_ids:", len(set(phi_series_ids)))
print("unique phi_instance_ids:", len(set(phi_instance_ids)))

print("completed phi study move operations", len(complete_phi_study_ids))
print("unique completed study move operations:", len(set(complete_phi_study_ids)))


print("anon files:", len(anon_patient_ids))
print("unique anon_patient_ids:", len(set(anon_patient_ids)))
print("unique anon_study_ids:", len(set(anon_study_ids)))
print("unique anon_series_ids:", len(set(anon_series_ids)))
print("unique anon_instance_ids:", len(set(anon_instance_ids)))

# for patient_id in set(phi_patient_ids):
#     print(patient_id)

complete_not_incoming = set(complete_phi_study_ids) - set(phi_study_ids)
print("complete_not_incoming:", len(complete_not_incoming))
# print(complete_not_incoming)

print("completed study move operations:", len(completed))
# for item in completed.items():
#     print(item)

total_operations = 0
total_operations_complete_not_incoming = 0
for study_uid, operations in completed.items():
    total_operations += operations
    if study_uid in complete_not_incoming:
        total_operations_complete_not_incoming += operations

print("total completed move sub-operations:", total_operations)
print(
    "total completed move sub-operations for complete_not_incoming:",
    total_operations_complete_not_incoming,
)

query_result_dict = {}

with open("/Users/michaelevans/Downloads/anonymizer_query.log", "r") as f:
    for line in f:
        if "StudyInstanceUID" in line:
            study_uid = None
            if "[" in line and "]" in line:
                study_uid = line.split("[")[1].split("]")[0].strip()
        elif "NumberOfStudyRelatedSeries" in line:
            num_series = None
            if "[" in line and "]" in line:
                num_series = int(line.split("[")[1].split("]")[0].strip())
        elif "NumberOfStudyRelatedInstances" in line:
            num_instances = None
            if "[" in line and "]" in line:
                num_instances = int(line.split("[")[1].split("]")[0].strip())
            if study_uid is not None and num_series is not None and num_instances is not None:
                query_result_dict[study_uid] = (num_series, num_instances)

query_result_study_uids = set(query_result_dict.keys())
incomplete_study_uids = query_result_study_uids - set(complete_phi_study_ids)

print("incomplete study uids:", incomplete_study_uids)
# remove incomplete studies from query result dict
for study_uid in incomplete_study_uids:
    query_result_dict.pop(study_uid, None)

print("query results:", len(query_result_dict))
total_instances = sum([x[1] for x in query_result_dict.values()])
print("total instances:", total_instances)


print("query results:", len(query_result_dict))
total_instances = sum([x[1] for x in query_result_dict.values()])
print("total instances:", total_instances)
