"""C-FIND SCU and Study UID hierarchy building."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, List, Tuple

from pydicom import Dataset
from pynetdicom.status import QR_FIND_SERVICE_CLASS_STATUS

from anonymizer.controller.dicom import dicomweb as dicomweb_api
from anonymizer.controller.dicom.hierarchies import (
    InstanceUIDHierarchy,
    SeriesUIDHierarchy,
    StudyUIDHierarchy,
)
from anonymizer.controller.dicom.requests import FindStudyRequest, FindStudyResponse
from anonymizer.model.project import DICOMRuntimeError
from anonymizer.utils.dicom import C_FAILURE, C_PENDING_A, C_PENDING_B, C_SUCCESS
from anonymizer.utils.translate import _

if TYPE_CHECKING:
    from pynetdicom.association import Association

logger = logging.getLogger(__name__)


class FindMixin:
    def abort_query(self):
        logger.info("Abort Query")
        self._abort_query = True

    def _emit_find_success(self, ux_Q) -> None:
        if not ux_Q:
            return
        ds = Dataset()
        ds.Status = C_SUCCESS
        ux_Q.put(FindStudyResponse(ds, None))

    def _emit_find_failure(self, ux_Q, error_msg: str) -> None:
        if not ux_Q:
            return
        ds = Dataset()
        ds.Status = C_FAILURE
        ds.ErrorComment = error_msg
        ux_Q.put(FindStudyResponse(ds, None))

    def _accept_study_result(self, study_result: Dataset, *, verify_attributes: bool) -> bool:
        if verify_attributes:
            missing = self._missing_attributes(self._required_attributes_study_query, study_result)
            if missing:
                logger.error("Query result is missing required attributes: %s", missing)
                logger.error("\n%s", study_result)
                return False
        self._strip_query_result_fields(study_result)
        return True

    def _find_studies_dicomweb(
        self,
        scp_name: str,
        name: str,
        id: str,
        acc_no: str,
        study_date: str,
        modality: str,
        ux_Q=None,
        verify_attributes=True,
    ) -> list[Dataset]:
        results: list[Dataset] = []
        self._abort_query = False
        try:
            node = self._resolve_remote(scp_name)
            logger.info(
                "QIDO-RS[study] to %s Query: %s, %s, %s, %s, %s",
                node,
                name,
                id,
                acc_no,
                study_date,
                modality,
            )
            with dicomweb_api.open_session(node, self.model.network_timeouts) as session:
                studies = dicomweb_api.find_studies(
                    session,
                    patient_name=name or "",
                    patient_id=id or "",
                    accession=acc_no or "",
                    study_date=study_date or "",
                    modality=modality or "",
                    abort_check=lambda: self._abort_query,
                )
            for study_result in studies:
                if self._abort_query:
                    raise RuntimeError("Query aborted")
                if not self._accept_study_result(study_result, verify_attributes=verify_attributes):
                    continue
                results.append(study_result)
                if ux_Q:
                    status = Dataset()
                    status.Status = C_PENDING_A
                    ux_Q.put(FindStudyResponse(status, study_result))
            self._emit_find_success(ux_Q)
        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            AttributeError,
            DICOMRuntimeError,
        ) as e:
            logger.error("%s", e)
            self._emit_find_failure(ux_Q, str(e))
        if not results:
            logger.info("No query results found")
        else:
            logger.info("%s Query results found", len(results))
        return results

    def _find_studies_via_acc_nos_dicomweb(
        self,
        scp_name: str,
        acc_no_list: list,
        ux_Q=None,
        verify_attributes=True,
    ) -> list[Dataset]:
        results: list[Dataset] = []
        self._abort_query = False
        try:
            node = self._resolve_remote(scp_name)
            acc_no_list = list(set(acc_no_list))
            logger.info("QIDO-RS Accession Query to %s: %s accession numbers", node, len(acc_no_list))
            with dicomweb_api.open_session(node, self.model.network_timeouts) as session:
                for acc_no in acc_no_list:
                    if self._abort_query:
                        raise RuntimeError("Query aborted")
                    if acc_no == "":
                        continue
                    studies = dicomweb_api.find_studies(
                        session,
                        accession=acc_no,
                        abort_check=lambda: self._abort_query,
                    )
                    for identifier in studies:
                        if not self._accept_study_result(identifier, verify_attributes=verify_attributes):
                            continue
                        if getattr(identifier, "AccessionNumber", None) != acc_no:
                            logger.error(
                                "Remote Server Accession Number partial match: %s != %s",
                                getattr(identifier, "AccessionNumber", None),
                                acc_no,
                            )
                            continue
                        results.append(identifier)
                        if ux_Q:
                            status = Dataset()
                            status.Status = C_PENDING_A
                            ux_Q.put(FindStudyResponse(status, identifier))
            self._emit_find_success(ux_Q)
            logger.info("Find Accession Numbers complete")
        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            AttributeError,
            DICOMRuntimeError,
        ) as e:
            logger.error("%s", e)
            self._emit_find_failure(ux_Q, str(e))
        if not results:
            logger.info("No query results found")
        else:
            logger.info("%s Query results found", len(results))
        return results

    # TODO: to be implemented as helper for refactoring find routines below
    def _query(
        self,
        query_association: Association,
        ds: Dataset,
        ux_Q=None,
        required_attributes: list[str] | None = None,
    ) -> list[Dataset]:
        """
        Executes a query using the provided query_association and dataset.

        Args:
            query_association (Association): The association used for the query.
            ds (Dataset): The dataset containing the query parameters.
            ux_Q (Queue, optional): The queue used for returning results to the UX. Defaults to None.
            required_attributes (list[str] | None, optional): The list of required attributes in the query result. Defaults to None.

        Returns:
            list[Dataset]: The list of query results.

        Raises:
            RuntimeError: If the query is aborted.
            ConnectionError: If the connection times out, is aborted, or receives an invalid response.
            DICOMRuntimeError: If the C-FIND operation fails with status not pending or success.
            Any Exception raised by pynetdicom or the underlying transport layer:
                ConnectionError, TimeoutError, RuntimeError, ValueError, AttributeError
        """
        results = []
        error_msg = ""
        self._abort_query = False
        try:
            # Send C-FIND request
            responses = query_association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],  # Find
            )

            # Process the response(s) received from the peer
            # one response with C_PENDING with identifier and one response with C_SUCCESS and no identifier
            for status, identifier in responses:
                if self._abort_query:
                    raise RuntimeError("Query aborted")

                if not status:
                    raise ConnectionError("Connection timed out, was aborted, or received an invalid response")
                if status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    logger.error(f"C-FIND failure, status: {hex(status.Status)}")
                    raise DICOMRuntimeError(f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status][1]}")

                if identifier:
                    if required_attributes:
                        missing_attributes = self._missing_attributes(required_attributes, identifier)
                        if missing_attributes != []:
                            logger.error(f"Query result is missing required attributes: {missing_attributes}")
                            logger.error(f"\n{identifier}")
                            continue

                    self._strip_query_result_fields(identifier)

                    results.append(identifier)

                    # Only return identifiers back to UX
                    # do not return (C_SUCCESS, None) as in find()
                    if ux_Q:
                        ux_Q.put(FindStudyResponse(status, identifier))

            # Signal success to UX once full list of accession numbers has been processed
            if ux_Q:
                logger.info("Find Accession Numbers complete")
                ds = Dataset()
                ds.Status = C_SUCCESS
                ux_Q.put(FindStudyResponse(ds, None))

        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            AttributeError,
            DICOMRuntimeError,
        ) as e:
            # Reflect status dataset back to UX client to provide find error detail
            error_msg = str(e)  # latch exception error msg
            logger.error(error_msg)
            if ux_Q:
                ds = Dataset()
                ds.Status = C_FAILURE
                ds.ErrorComment = error_msg
                ux_Q.put(FindStudyResponse(ds, None))

        finally:
            if query_association:
                query_association.release()

        return results

    def find_studies(
        self,
        scp_name: str,
        name: str,
        id: str,
        acc_no: str,
        study_date: str,
        modality: str,
        ux_Q=None,
        verify_attributes=True,
    ) -> list[Dataset] | None:
        """
        Blocking: Query remote server for studies matching the given query parameters:

        Args:
            scp_name (str): The name of the SCP (Service Class Provider) to connect to from the ProjectModel's remote_scps dictionary.
            name (str): The name of the patient.
            id (str): The ID of the patient.
            acc_no (str): The accession number of the study.
            study_date (str): The date of the study.
            modality (str): The modality of the study.
            ux_Q (Queue, optional): The queue to put the find study responses in. Defaults to None.
            verify_attributes (bool, optional): Flag to indicate whether to verify the attributes of the study results. Defaults to True.

        Returns:
            list[Dataset] | None: A list of study results as Dataset objects, or None if no results are found
            On any error: the error message is captured and reflected back to the UX client via a pydicom status dataset within FindStudyResponse placed in ux_Q.

        """
        results: list[Dataset] = []
        query_association = None
        try:
            node = self._resolve_remote(scp_name)
            if node.dicomweb:
                return self._find_studies_dicomweb(
                    scp_name, name, id, acc_no, study_date, modality, ux_Q, verify_attributes
                )

            scp = node
            logger.info(f"C-FIND[study] to {scp} Study Level Query: {name}, {id}, {acc_no}, {study_date}, {modality}")

            # Phase 1: Study Level Query
            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.AccessionNumber = acc_no
            ds.StudyDate = study_date
            ds.ModalitiesInStudy = modality
            ds.SOPClassesInStudy = ""
            ds.PatientName = name
            ds.PatientID = id
            ds.PatientSex = ""
            ds.PatientBirthDate = ""

            ds.NumberOfStudyRelatedSeries = ""
            ds.NumberOfStudyRelatedInstances = ""
            ds.StudyDescription = ""
            ds.StudyInstanceUID = ""

            error_msg = ""
            self._abort_query = False

            query_association = self._connect_to_scp(scp_name, self.get_study_root_find_contexts())

            study_responses = query_association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],
            )

            for study_status, study_result in study_responses:
                if self._abort_query:
                    raise RuntimeError("Query aborted")

                # Timeouts (Network & DIMSE) are reflected by status being None:
                if not study_status:
                    raise ConnectionError(
                        "Connection timed out (DIMSE or IDLE), was aborted, or received an invalid response"
                    )

                if study_status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    logger.error(f"C-FIND Study failure, status: {hex(study_status.Status)}")
                    raise DICOMRuntimeError(f"C-FIND Study Failed: {QR_FIND_SERVICE_CLASS_STATUS[study_status.Status]}")

                if study_status.Status == C_SUCCESS:
                    logger.info("C-FIND study query success")

                if study_result:
                    if verify_attributes:
                        missing_study_attributes = self._missing_attributes(
                            self._required_attributes_study_query, study_result
                        )
                        if missing_study_attributes != []:
                            logger.error(f"Query result is missing required attributes: {missing_study_attributes}")
                            logger.error(f"\n{study_result}")
                            continue

                    self._strip_query_result_fields(study_result)

                    results.append(study_result)

                if ux_Q:
                    ux_Q.put(FindStudyResponse(study_status, study_result))

        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            AttributeError,
            DICOMRuntimeError,
        ) as e:
            # Reflect status dataset back to UX client to provide find error detail
            error_msg = str(e)  # latch exception error msg
            logger.error(error_msg)
            if ux_Q:
                ds = Dataset()
                ds.Status = C_FAILURE
                ds.ErrorComment = error_msg
                ux_Q.put(FindStudyResponse(ds, None))

        finally:
            if query_association:
                if self._abort_query:
                    query_association.abort()
                else:
                    query_association.release()

        if len(results) == 0:
            logger.info("No query results found")
        else:
            logger.info(f"{len(results)} Query results found")
            for result in results:
                logger.debug(
                    # f"{getattr(result, 'PatientName', 'N/A')}, "
                    # f"{getattr(result, 'PatientID', 'N/A')}, "
                    # f"{getattr(result, 'StudyDate', 'N/A')}, "
                    # f"{getattr(result, 'AccessionNumber', 'N/A')}, "
                    # f"{getattr(result, 'StudyInstanceUID', 'N/A')} "
                    f"{getattr(result, 'StudyDescription', 'N/A')}, "
                    f"{getattr(result, 'ModalitiesInStudy', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedSeries', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedInstances', 'N/A')}, "
                )

        return results

    def find_studies_via_acc_nos(
        self,
        scp_name: str,
        acc_no_list: list,
        ux_Q=None,
        verify_attributes=True,
    ) -> list[Dataset] | None:
        """
        Blocking: Query remote server for studies corresponding to list of accession numbers

        Args:
            scp_name (str): The name of the SCP (Service Class Provider) to connect to.
            acc_no_list (list): A list of accession numbers to search for.
            ux_Q (Queue, optional): A queue to send intermediate results to the user interface. Defaults to None.
            verify_attributes (bool, optional): Flag to indicate whether to verify the attributes of the query results. Defaults to True.

        Returns:
            list[Dataset] | None: A list of Dataset objects representing the query results, or None if no results were found.
            If PACS does an implicit wildcard search remove these responses, only accept exact AccessionNumber matches
            On any error: the error message is captured and reflected back to the UX client via a pydicom status dataset within FindStudyResponse placed in ux_Q.
        """
        results: list[Dataset] = []
        query_association = None
        try:
            node = self._resolve_remote(scp_name)
            if node.dicomweb:
                return self._find_studies_via_acc_nos_dicomweb(scp_name, acc_no_list, ux_Q, verify_attributes)

            scp = node
            logger.info(f"C-FIND to {scp} Accession Query: {len(acc_no_list)} accession numbers...")
            acc_no_list = list(set(acc_no_list))  # remove duplicates
            logger.debug(f"{acc_no_list}")

            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.ModalitiesInStudy = ""
            ds.NumberOfStudyRelatedSeries = ""
            ds.NumberOfStudyRelatedInstances = ""
            ds.StudyDescription = ""
            ds.StudyInstanceUID = ""
            ds.PatientName = ""
            ds.PatientID = ""
            ds.StudyDate = ""

            error_msg = ""
            self._abort_query = False

            query_association = self._connect_to_scp(scp_name, self.get_study_root_find_contexts())

            for acc_no in acc_no_list:
                if self._abort_query:
                    raise RuntimeError("Query aborted")

                if acc_no == "":
                    continue

                ds.AccessionNumber = acc_no

                responses = query_association.send_c_find(
                    ds,
                    query_model=self._STUDY_ROOT_QR_CLASSES[0],  # Find
                )

                # Process the response(s) received from the peer
                # one response with C_PENDING with identifier and one response with C_SUCCESS and no identifier
                for status, identifier in responses:
                    if not status:
                        raise ConnectionError("Connection timed out, was aborted, or received an invalid response")
                    if status.Status not in (
                        C_SUCCESS,
                        C_PENDING_A,
                        C_PENDING_B,
                    ):
                        logger.error(f"C-FIND failure, status: {hex(status.Status)}")
                        raise DICOMRuntimeError(f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status][1]}")

                    if identifier:
                        if verify_attributes:
                            missing_study_attributes = self._missing_attributes(
                                self._required_attributes_study_query, identifier
                            )
                            if missing_study_attributes != []:
                                logger.error(f"Query result is missing required attributes: {missing_study_attributes}")
                                logger.error(f"\n{identifier}")
                                continue

                        # If PACS does an implicit wildcard search remove these responses, only accept exact matches:
                        if identifier.AccessionNumber != acc_no:
                            logger.error(
                                f"Remote Server Accession Number partial match: AccessionNumber {identifier.AccessionNumber} does not match request: {acc_no}"
                            )
                            continue

                        self._strip_query_result_fields(identifier)

                        results.append(identifier)

                        # Only return identifiers back to UX
                        # do not return (C_SUCCESS, None) as in find()
                        if ux_Q:
                            ux_Q.put(FindStudyResponse(status, identifier))

            # Signal success to UX once full list of accession numbers has been processed
            if ux_Q:
                logger.info("Find Accession Numbers complete")
                ds = Dataset()
                ds.Status = C_SUCCESS
                ux_Q.put(FindStudyResponse(ds, None))

        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            AttributeError,
            DICOMRuntimeError,
        ) as e:
            # Reflect status dataset back to UX client to provide find error detail
            error_msg = str(e)  # latch exception error msg
            logger.error(error_msg)
            if ux_Q:
                ds = Dataset()
                ds.Status = C_FAILURE
                ds.ErrorComment = error_msg
                ux_Q.put(FindStudyResponse(ds, None))

        finally:
            if query_association:
                query_association.release()

        if len(results) == 0:
            logger.info("No query results found")
        else:
            logger.info(f"{len(results)} Query results found")
            for result in results:
                logger.debug(
                    f"{getattr(result, 'PatientName', 'N/A')}, "
                    f"{getattr(result, 'PatientID', 'N/A')}, "
                    f"{getattr(result, 'StudyDate', 'N/A')}, "
                    f"{getattr(result, 'StudyDescription', 'N/A')}, "
                    f"{getattr(result, 'AccessionNumber', 'N/A')}, "
                    f"{getattr(result, 'ModalitiesInStudy', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedSeries', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedInstances', 'N/A')}, "
                    f"{getattr(result, 'StudyInstanceUID', 'N/A')} "
                )

        return results

    def find_ex(self, fr: FindStudyRequest) -> None:
        """
        Non-blocking: Find studies based on the provided search parameters or accession numbers.

        Args:
            fr (FindStudyRequest): The FindStudyRequest object containing the search parameters or just accession numbers in the acc_no field.

        Returns:
            None
        """
        if isinstance(fr.acc_no, list):
            logger.info("Find studies from list of accession numbers...")
            # Due to client removing numbers as they are found, make a copy of the list:
            acc_no_list = fr.acc_no.copy()
            fr.acc_no = acc_no_list
            threading.Thread(
                target=self.find_studies_via_acc_nos,
                name="FindStudiesAccNos",
                args=(
                    fr.scp_name,
                    fr.acc_no,
                    fr.ux_Q,
                ),
                daemon=True,  # daemon threads are abruptly stopped at shutdown
            ).start()
        else:
            logger.info("Find studies from search parameters...")
            threading.Thread(
                target=self.find_studies,
                name="FindStudies",
                args=(
                    fr.scp_name,
                    fr.name,
                    fr.id,
                    fr.acc_no,
                    fr.study_date,
                    fr.modality,
                    fr.ux_Q,
                ),
                daemon=True,  # daemon threads are abruptly stopped at shutdown
            ).start()

    def _get_study_uid_hierarchy_dicomweb(
        self,
        scp_name: str,
        study_uid: str,
        patient_id: str,
        instance_level: bool = False,
    ) -> Tuple[str | None, StudyUIDHierarchy]:
        study_uid_hierarchy = StudyUIDHierarchy(uid=study_uid, ptid=patient_id, series={})
        error_msg = None
        try:
            node = self._resolve_remote(scp_name)
            logger.info(
                "QIDO-RS hierarchy from %s StudyUID=%s PatientID=%s instance_level=%s",
                node,
                study_uid,
                patient_id,
                instance_level,
            )
            with dicomweb_api.open_session(node, self.model.network_timeouts) as session:
                series_results = dicomweb_api.find_series(
                    session, study_uid, abort_check=lambda: self._abort_query
                )
                for identifier in series_results:
                    if self._abort_query:
                        raise RuntimeError("Query aborted")
                    missing_attributes = self._missing_attributes(
                        self._required_attributes_series_query, identifier
                    )
                    if missing_attributes:
                        logger.error(
                            "Skip Series for Study:%s, missing attributes: %s",
                            study_uid,
                            missing_attributes,
                        )
                        continue
                    if getattr(identifier, "StudyInstanceUID", None) != study_uid:
                        continue
                    if identifier.Modality not in self.model.modalities:
                        logger.info(
                            "Skip Series[Modality=%s]:%s with mismatched modality",
                            identifier.Modality,
                            identifier.SeriesInstanceUID,
                        )
                        continue
                    sop_class_uid = identifier.get("SOPClassUID", None)
                    if sop_class_uid and sop_class_uid not in self.model.storage_classes:
                        continue
                    series_descr = (
                        identifier.SeriesDescription if hasattr(identifier, "SeriesDescription") else "?"
                    )
                    instance_count = int(identifier.get("NumberOfSeriesRelatedInstances", 0) or 0)
                    if identifier.SeriesInstanceUID in study_uid_hierarchy.series:
                        study_uid_hierarchy.series[identifier.SeriesInstanceUID].instance_count += 1
                    else:
                        study_uid_hierarchy.series[identifier.SeriesInstanceUID] = SeriesUIDHierarchy(
                            uid=identifier.SeriesInstanceUID,
                            number=identifier.get("SeriesNumber", None),
                            modality=identifier.Modality,
                            sop_class_uid=sop_class_uid,
                            description=series_descr,
                            instance_count=instance_count,
                            instances={},
                        )

                if len(study_uid_hierarchy.series) == 0:
                    raise DICOMRuntimeError(
                        "QIDO-RS[series] Failed: No series found in study matching project modalities"
                    )

                need_instances = instance_level or any(
                    s.instance_count == 0 for s in study_uid_hierarchy.series.values()
                )
                if need_instances:
                    for series in study_uid_hierarchy.series.values():
                        instances = dicomweb_api.find_instances(
                            session,
                            study_uid,
                            series.uid,
                            abort_check=lambda: self._abort_query,
                        )
                        for identifier in instances:
                            if self._abort_query:
                                raise RuntimeError("Query aborted")
                            missing_attributes = self._missing_attributes(
                                self._required_attributes_instance_query, identifier
                            )
                            if missing_attributes:
                                continue
                            if (
                                getattr(identifier, "StudyInstanceUID", None) == study_uid
                                and getattr(identifier, "SeriesInstanceUID", None) == series.uid
                            ):
                                series.instances[identifier.SOPInstanceUID] = InstanceUIDHierarchy(
                                    uid=identifier.SOPInstanceUID,
                                    number=identifier.InstanceNumber
                                    if hasattr(identifier, "InstanceNumber")
                                    else None,
                                )
                        series.instance_count = len(series.instances)

            study_uid_hierarchy.pending_instances = study_uid_hierarchy.get_number_of_instances()
        except Exception as e:
            error_msg = str(e)
            study_uid_hierarchy.last_error_msg = error_msg
            logger.error("%s", error_msg)
        return error_msg, study_uid_hierarchy

    def get_study_uid_hierarchy(
        self,
        scp_name: str,
        study_uid: str,
        patient_id: str,
        instance_level: bool = False,
    ) -> Tuple[str | None, StudyUIDHierarchy]:
        """
        Blocking: Query remote DICOM server for study/series/instance uid hierarchy (required for iterative move) for the specified Study UID.
        Perform a SERIES level query first to get the list of Series UIDs for the Study UID.
        IF the remote SCP does not respond with NumberOfSeriesRelatedInstances and instance_level is False, raise an exception & catch error message.
        IF instance_level is True, perform an INSTANCE level query for each Series UID to get the list of Instance UIDs.

        Args:
            scp_name (str): The name of the SCP.
            study_uid (str): The Study UID.
            patient_id (str): The Patient ID. (not used for query, copied to StudyUIDHierarchy object)
            instance_level (bool, optional): Flag indicating whether to retrieve instance-level information. Defaults to False.

        Returns:
            Tuple[str | None, StudyUIDHierarchy]: A tuple containing the error message (if any) and the StudyUIDHierarchy object.
            The error message reflects any exception caught during the query process.
        """
        study_uid_hierarchy = StudyUIDHierarchy(uid=study_uid, ptid=patient_id, series={})
        error_msg = None
        query_association: Association | None = None

        try:
            node = self._resolve_remote(scp_name)
            if node.dicomweb:
                return self._get_study_uid_hierarchy_dicomweb(scp_name, study_uid, patient_id, instance_level)

            scp = node
            logger.info(
                f"Get StudyUIDHierarchy from {scp_name} for StudyUID={study_uid}, PatientID={patient_id} instance_level={instance_level}"
            )

            # 1. Connect to SCP:
            query_association = self._connect_to_scp(scp_name, self.get_study_root_find_contexts())

            # 2. Get list of Series UIDs for the Study UID:
            logger.info(f"C-FIND[series] to {scp} study_uid={study_uid}")
            ds = Dataset()
            ds.QueryRetrieveLevel = "SERIES"
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = ""
            ds.SeriesNumber = ""
            ds.SeriesDescription = ""
            ds.Modality = ""
            ds.SOPClassUID = ""
            ds.NumberOfSeriesRelatedInstances = ""

            responses = query_association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],  # Find
            )

            for status, identifier in responses:
                if self._abort_query:
                    raise RuntimeError("Query aborted")
                if not status:
                    raise ConnectionError("Connection timed out, was aborted, or received an invalid response")
                if status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B):
                    logger.error(f"C-FIND[series] failure, status: {hex(status.Status)}")
                    raise DICOMRuntimeError(f"C-FIND[series] Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status]}")

                if status.Status == C_SUCCESS:
                    logger.info("C-FIND[series] query success")
                if identifier:
                    missing_attributes = self._missing_attributes(self._required_attributes_series_query, identifier)
                    if missing_attributes:
                        logger.error(
                            f"Skip Series for Study:{study_uid}, Series Level Query result is missing required attributes: {missing_attributes}"
                        )
                        logger.error(f"\n{identifier}")
                        continue
                    if identifier.StudyInstanceUID != study_uid:
                        logger.error(
                            f"Skip Series:{identifier.SeriesInstanceUID} Mismatch: StudyUID:{study_uid}<>{identifier.StudyInstanceUID}"
                        )
                        continue
                    if identifier.Modality not in self.model.modalities:
                        logger.info(
                            f"Skip Series[Modality={identifier.Modality}]:{identifier.SeriesInstanceUID} with mismatched modality"
                        )
                        continue
                    # Some PACS may provide SOPClassUID at series & study level if they contain a single class
                    # ALL PACS should provide SOPClassUID at instance level
                    sop_class_uid = identifier.get("SOPClassUID", None)
                    if sop_class_uid and sop_class_uid not in self.model.storage_classes:
                        logger.info(
                            f"Skip Series[SOPClassUID={identifier.SOPClassUID}]:{identifier.SeriesInstanceUID} with mismatched sop_class_uid"
                        )
                        continue

                    # New SeriesUIDHierarchy:
                    series_descr = identifier.SeriesDescription if hasattr(identifier, "SeriesDescription") else "?"
                    instance_count = identifier.get("NumberOfSeriesRelatedInstances", 0)
                    if not instance_level and not instance_count:
                        raise DICOMRuntimeError(
                            _("Unable to retrieve UID Hierarchy for reliable import operation via DICOM C-MOVE.")
                            + f" {scp_name} "
                            + _("Server")
                            + " "
                            + _("did not return the number of instances in a series.")
                            + " "
                            + _(
                                "Standard DICOM field (0020,1209) NumberOfSeriesRelatedInstances is missing in the query response."
                            )
                        )

                    # IF this Series already exists in the hierarchy,
                    # assume the scp is sending a query response for each instance and increment the series instance count:
                    # TODO: is this acceptable? alternatively could force instance level query below
                    if identifier.SeriesInstanceUID in study_uid_hierarchy.series:
                        if instance_count != 1:
                            raise DICOMRuntimeError(
                                f"SCP Series Query Response for series:{identifier.SeriesInstanceUID}, inconsistent NumberOfSeriesRelatedInstances: {instance_count}"
                            )
                        study_uid_hierarchy.series[identifier.SeriesInstanceUID].instance_count += 1
                        logger.info(
                            f"Add instance to existing series: {identifier.SeriesInstanceUID} i{study_uid_hierarchy.series[identifier.SeriesInstanceUID].instance_count}"
                        )
                    else:
                        study_uid_hierarchy.series[identifier.SeriesInstanceUID] = SeriesUIDHierarchy(
                            uid=identifier.SeriesInstanceUID,
                            number=identifier.get("SeriesNumber", None),  # TODO: should this be auto-generated if None?
                            modality=identifier.Modality,
                            sop_class_uid=sop_class_uid,
                            description=series_descr,
                            instance_count=instance_count,
                            instances={},
                        )
                        logger.info(
                            f"New Series[Modality={identifier.Modality},SOPClassUID={sop_class_uid}]: {series_descr}/{identifier.SeriesInstanceUID}/{identifier.SeriesNumber} | {instance_count}"
                        )

            logger.info(f"StudyUID={study_uid}, {len(study_uid_hierarchy.series)} Series found")
            if len(study_uid_hierarchy.series) == 0:
                raise DICOMRuntimeError("C-FIND[series] Failed: No series found in study matching project modalities")

            if instance_level:
                # 3. If Instance level required: Get list of Instance UIDs for each Series UID:
                for series in study_uid_hierarchy.series.values():
                    ds = Dataset()
                    ds.QueryRetrieveLevel = "IMAGE"
                    ds.StudyInstanceUID = study_uid
                    ds.SeriesInstanceUID = series.uid
                    ds.SOPInstanceUID = ""
                    ds.InstanceNumber = ""

                    responses = query_association.send_c_find(
                        ds,
                        query_model=self._STUDY_ROOT_QR_CLASSES[0],  # Find
                    )
                    for status, identifier in responses:
                        if self._abort_query:
                            raise RuntimeError("Query aborted")
                        if not status:
                            raise ConnectionError("Connection timed out, was aborted, or received an invalid response")
                        if status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B):
                            logger.error(f"C-FIND[instance] failure, status: {hex(status.Status)}")
                            raise DICOMRuntimeError(
                                f"C-FIND[instance] Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status]}"
                            )

                        if status.Status == C_SUCCESS:
                            logger.info("C-FIND[instance] query success")

                        if identifier:
                            missing_attributes = self._missing_attributes(
                                self._required_attributes_instance_query, identifier
                            )
                            if missing_attributes:
                                logger.error(
                                    f"Skip Instance for Series:{series.uid}, Instance Level Query result is missing required attributes: {missing_attributes}"
                                )
                                logger.error(f"\n{identifier}")
                                continue
                            if identifier.StudyInstanceUID == study_uid and identifier.SeriesInstanceUID == series.uid:
                                series.instances[identifier.SOPInstanceUID] = InstanceUIDHierarchy(
                                    uid=identifier.SOPInstanceUID,
                                    number=identifier.InstanceNumber if hasattr(identifier, "InstanceNumber") else None,
                                )
                            else:
                                logger.error(
                                    f"Mismatch: Study:{study_uid}<>{identifier.StudyInstanceUID} and/or Series:{series.uid}<>{identifier.SeriesInstanceUID}"
                                )

                    logger.info(f"SeriesUID={series.uid}: {len(series.instances)} Instance UIDs found")
                    # Overwrite instance_count with actual instance count:
                    series.instance_count = len(series.instances)

            # Initialise Study pending instances to total instance count:
            study_uid_hierarchy.pending_instances = study_uid_hierarchy.get_number_of_instances()

        except Exception as e:
            error_msg = str(e)  # latch exception error msg
            study_uid_hierarchy.last_error_msg = error_msg
            logger.error(error_msg)

        finally:
            if query_association:
                if self._abort_query:
                    query_association.abort()
                else:
                    query_association.release()

        return error_msg, study_uid_hierarchy

    def get_study_uid_hierarchies(self, scp_name: str, studies: List[StudyUIDHierarchy], instance_level: bool) -> None:
        """
        Blocking: Get List of StudyUIDHierarchies based on value of study_uid within each element of list of StudyUIDHierarchy objects.
        last_error_msg of each StudyUIDHierarch object is set by get_study_uid_hierarchy()

        TODO: Optimization: make this multi-threaded using futures & thread executor as for manage_move

        Args:
            scp_name (str): The name of the SCP.
            studies (List[StudyUIDHierarchy]): A list of StudyUIDHierarchy objects representing the studies.
            instance_level (bool): A flag indicating whether to retrieve instance-level information.

        Returns:
            None
        """
        logger.info(f"Get StudyUIDHierarchies for {len(studies)} studies, instance_level: {instance_level}")
        self._abort_query = False
        for study in studies:
            if self._abort_query:
                logger.info("GetStudyUIDHierarchies Aborted")
                break
            error_msg, study_uid_hierarchy = self.get_study_uid_hierarchy(
                scp_name, study.uid, study.ptid, instance_level
            )
            study.series = study_uid_hierarchy.series
            study.last_error_msg = error_msg
            # Initialise Study pending instances to total instance count:
            study.pending_instances = study_uid_hierarchy.pending_instances

        logger.info("Get StudyUIDHierarchies done")

    def get_study_uid_hierarchies_ex(
        self, scp_name: str, studies: List[StudyUIDHierarchy], instance_level: bool
    ) -> None:
        """
        Non-blocking Get List of StudyUIDHierarchies

        Args:
            scp_name (str): The name of the SCP (Service Class Provider).
            studies (List[StudyUIDHierarchy]): A list of StudyUIDHierarchy objects representing the studies.
            instance_level (bool): Indicates whether to retrieve instance-level hierarchies.

        Returns:
            None
        """
        threading.Thread(
            target=self.get_study_uid_hierarchies,
            name="GetStudyUIDHierarchies",
            args=(scp_name, studies, instance_level),
            daemon=True,  # daemon threads are abruptly stopped at shutdown
        ).start()

    def get_number_of_pending_instances(self, study: StudyUIDHierarchy) -> int:
        """
        Calculates the number of pending instances for a given study by subtracting the number of instance in StudyUIDHierarchy
        from the total number of instances stored in the AnonymizerModel. (not from reading the file system)

        Args:
            study (StudyUIDHierarchy): The study for which to calculate the number of pending instances.

        Returns:
            int: The number of pending instances for the study.
        """
        return study.get_number_of_instances() - self.anonymizer.model.get_stored_instance_count(study_uid=study.uid)

