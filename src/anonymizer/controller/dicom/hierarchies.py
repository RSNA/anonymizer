"""DICOM UID hierarchy trees used by Find / retrieve (C-MOVE / C-GET)."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydicom import Dataset

from anonymizer.utils.dicom import C_SUCCESS


class InstanceUIDHierarchy:
    def __init__(self, uid: str, number: int | None = None):
        self.uid = uid
        self.number = number

    def __str__(self):
        return f"{self.uid},{self.number or ''}"


class SeriesUIDHierarchy:
    def __init__(
        self,
        uid: str,
        number: int | None = None,
        modality: str | None = None,
        sop_class_uid: str | None = None,
        description: str | None = None,  # TODO: add BodyPartExamined?
        instance_count: int = 0,  # from NumberOfSeriesRelatedInstances
        instances: Optional[Dict[str, InstanceUIDHierarchy]] = None,
    ):
        self.uid = uid
        self.number = number
        self.modality = modality
        self.sop_class_uid = sop_class_uid
        self.instance_count = instance_count
        self.description = description
        self.instances = instances if instances is not None else {}
        # from send_c_move status response:
        self.completed_sub_ops = 0
        self.failed_sub_ops = 0
        self.remaining_sub_ops = 0
        self.warning_sub_ops = 0

    def __str__(self):
        instances_str = "{}"
        if self.instances:
            instances_str = ""
            for instance in self.instances.values():
                instances_str += "\n----" + str(instance)
        return f"{self.uid},{self.number or ''},{self.modality or ''},{self.description or ''}[{self.completed_sub_ops},{self.failed_sub_ops},{self.remaining_sub_ops},{self.warning_sub_ops}]i{self.instance_count}{instances_str}"

    def get_number_of_instances(self) -> int:
        return len(self.instances)

    def find_instance(self, instance_uid: str) -> Optional[InstanceUIDHierarchy]:
        if instance_uid in self.instances:
            return self.instances[instance_uid]
        return None

    def update_move_stats(self, status: Dataset):
        if hasattr(status, "NumberOfRemainingSuboperations"):
            self.remaining_sub_ops = status.NumberOfRemainingSuboperations
        else:
            self.remaining_sub_ops = 0  # When status is C_SUCCESS
        self.completed_sub_ops = status.NumberOfCompletedSuboperations
        self.failed_sub_ops = status.NumberOfFailedSuboperations
        self.warning_sub_ops = status.NumberOfWarningSuboperations

    def update_move_stats_instance_level(self, status: Dataset):
        # Do not track RemainingSuboperations
        if status.Status == C_SUCCESS and status.NumberOfCompletedSuboperations == 1:
            self.completed_sub_ops += 1
            self.failed_sub_ops += status.NumberOfFailedSuboperations
            self.warning_sub_ops += status.NumberOfWarningSuboperations


class StudyUIDHierarchy:
    def __init__(
        self,
        uid: str,
        ptid: str,
        series: Dict[str, SeriesUIDHierarchy] | None = None,
    ):
        self.uid = uid
        self.ptid = ptid
        self.last_error_msg: str | None = None  # set by GetStudyHierarchy() or Move Operation
        self.series = series if series is not None else {}
        self.pending_instances = 0  # set by move operation
        # from send_c_move status response:
        self.completed_sub_ops: int = 0
        self.failed_sub_ops: int = 0
        self.remaining_sub_ops: int = 0
        self.warning_sub_ops: int = 0

    def __str__(self):
        series_str = "{}"
        if self.series:
            series_str = ""
            for series in self.series.values():
                series_str += "\n--" + str(series)
        return f"{self.uid},{self.last_error_msg or ''},[{self.completed_sub_ops},{self.failed_sub_ops},{self.remaining_sub_ops},{self.warning_sub_ops}]i{self.get_number_of_instances()}{series_str}"

    def get_number_of_instances(self) -> int:
        if self.series is None:
            return 0
        return sum(series.instance_count for series in self.series.values())

    def get_instances(self) -> List[InstanceUIDHierarchy]:
        instances = []
        for series_obj in self.series.values():
            instances.extend(series_obj.instances.values())
        return instances

    def update_move_stats(self, status: Dataset):
        if hasattr(status, "NumberOfRemainingSuboperations"):
            self.remaining_sub_ops = status.NumberOfRemainingSuboperations
        else:
            self.remaining_sub_ops = 0  # When status is C_SUCCESS
        self.completed_sub_ops = status.NumberOfCompletedSuboperations
        self.failed_sub_ops = status.NumberOfFailedSuboperations
        self.warning_sub_ops = status.NumberOfWarningSuboperations

    def find_instance(self, instance_uid: str) -> Optional[InstanceUIDHierarchy]:
        for series in self.series.values():
            if instance_uid in series.instances:
                return series.instances[instance_uid]
        return None

