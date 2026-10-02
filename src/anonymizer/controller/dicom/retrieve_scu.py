"""C-MOVE / C-GET retrieve SCU with Get preference when negotiated."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydicom import Dataset
from pynetdicom.events import EVT_C_STORE
from pynetdicom.status import QR_GET_SERVICE_CLASS_STATUS, QR_MOVE_SERVICE_CLASS_STATUS

from anonymizer.controller.dicom import dicomweb as dicomweb_api
from anonymizer.controller.dicom.hierarchies import StudyUIDHierarchy
from anonymizer.controller.dicom.requests import MoveStudiesRequest
from anonymizer.model.project import DICOMNode, DICOMRuntimeError
from anonymizer.utils.dicom import C_PENDING_A, C_PENDING_B, C_SUCCESS, C_WARNING
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

RetrieveModality = Literal["GET", "MOVE", "WADO"]
RetrieveLevel = Literal["STUDY", "SERIES", "INSTANCE"]


class RetrieveMixin:
    """Study-Root retrieve (prefer C-GET when accepted, else C-MOVE)."""

    def _normalize_retrieve_level(self, level: str | None) -> RetrieveLevel:
        if not level:
            return "SERIES"
        upper = level.upper()
        if "STUDY" in upper:
            return "STUDY"
        if upper in (_("IMAGE").upper(), _("INSTANCE").upper(), "IMAGE", "INSTANCE"):
            return "INSTANCE"
        return "SERIES"

    def _association_accepts_sop(self, association, sop_uid: str) -> bool:
        return any(str(cx.abstract_syntax) == sop_uid for cx in association.accepted_contexts)

    def _association_accepts_get(self, association) -> bool:
        return self._association_accepts_sop(association, self._STUDY_ROOT_QR_CLASSES[2])

    def _qr_support_cache_key(self, scp: str | DICOMNode) -> str:
        if isinstance(scp, str):
            return scp
        return f"{scp.ip}:{scp.port}:{scp.aet}"

    def _probe_qr_sop_support(
        self,
        scp: str | DICOMNode,
        *,
        service: Literal["GET", "MOVE"],
        cache: dict[str, bool],
        contexts,
        sop_uid: str,
        ext_neg=None,
        log_retrieve_choice: bool = False,
    ) -> bool:
        """Associate and check whether ``sop_uid`` was accepted. Logs at INFO."""
        label = self._qr_support_cache_key(scp)
        cached = cache.get(label)
        if cached is not None:
            if service == "GET" and log_retrieve_choice:
                if cached:
                    logger.info(
                        "Remote SCP %s accepts Study-Root C-GET (cached) — retrieve will use C-GET",
                        label,
                    )
                else:
                    logger.info(
                        "Remote SCP %s does not accept Study-Root C-GET (cached) — retrieve will use C-MOVE",
                        label,
                    )
            else:
                logger.info(
                    "Remote SCP %s Study-Root C-%s %s (cached)",
                    label,
                    service,
                    "accepted" if cached else "not accepted",
                )
            return cached

        association = None
        supported = False
        try:
            association = self._connect_to_scp(scp, contexts, ext_neg=ext_neg)
            supported = self._association_accepts_sop(association, sop_uid)
            if service == "GET" and log_retrieve_choice:
                if supported:
                    logger.info(
                        "Remote SCP %s accepts Study-Root C-GET — retrieve will use C-GET",
                        label,
                    )
                else:
                    logger.info(
                        "Remote SCP %s does not accept Study-Root C-GET — retrieve will use C-MOVE",
                        label,
                    )
            else:
                logger.info(
                    "Remote SCP %s Study-Root C-%s %s",
                    label,
                    service,
                    "accepted" if supported else "not accepted",
                )
        except Exception as exc:
            if service == "GET" and log_retrieve_choice:
                logger.info(
                    "Remote SCP %s Study-Root C-GET probe failed (%s) — retrieve will use C-MOVE",
                    label,
                    exc,
                )
            else:
                logger.info(
                    "Remote SCP %s Study-Root C-%s probe failed (%s) — treating as not accepted",
                    label,
                    service,
                    exc,
                )
            supported = False
        finally:
            if association and association.is_established:
                association.release()
        cache[label] = supported
        return supported

    def _probe_qr_get_support(self, scp: str | DICOMNode) -> bool:
        """Probe (or recall) whether the remote SCP accepts Study-Root C-GET."""
        return self._probe_qr_sop_support(
            scp,
            service="GET",
            cache=self._qr_get_supported,
            contexts=self.get_study_root_get_contexts(),
            sop_uid=self._STUDY_ROOT_QR_CLASSES[2],
            ext_neg=self._storage_scp_roles(),
            log_retrieve_choice=True,
        )

    def _probe_qr_move_support(self, scp: str | DICOMNode) -> bool:
        """Probe (or recall) whether the remote SCP accepts Study-Root C-MOVE."""
        return self._probe_qr_sop_support(
            scp,
            service="MOVE",
            cache=self._qr_move_supported,
            contexts=self.get_study_root_move_contexts(),
            sop_uid=self._STUDY_ROOT_QR_CLASSES[1],
        )

    def probe_study_root_qr_support(self, scp: str | DICOMNode) -> tuple[bool, bool]:
        """Return ``(c_get_accepted, c_move_accepted)`` for a remote SCP (Test Connection / diagnostics)."""
        return self._probe_qr_get_support(scp), self._probe_qr_move_support(scp)

    def _wait_pending_instances(
        self,
        study: StudyUIDHierarchy,
        *,
        label: str,
        done_when,
    ) -> None:
        prev_pending = study.pending_instances
        import_timer = int(self.model.network_timeouts.network)
        while import_timer:
            if self._abort_move:
                raise DICOMRuntimeError(f"{label} aborted")
            study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                study.uid, study.get_number_of_instances()
            )
            if done_when(study):
                logger.info("%s import complete", label)
                return
            if study.pending_instances != prev_pending:
                prev_pending = study.pending_instances
                import_timer = int(self.model.network_timeouts.network)
            import_timer -= 1
            time.sleep(1)
        raise TimeoutError(f"{label} Import Timeout")

    def _process_qr_statuses(self, responses, *, label: str, status_table, on_status) -> None:
        for status, identifier in responses:
            time.sleep(0.1)
            if self._abort_move:
                raise DICOMRuntimeError(f"{label} aborted")
            if not status:
                raise ConnectionError(_("Connection timed out or aborted") + f": {label}")
            if status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B, C_WARNING):
                detail = status_table.get(status.Status, (None, "Unknown"))[1]
                raise DICOMRuntimeError(f"{label} failure, status:{hex(status.Status).upper()}: {detail}")
            if status.Status == C_SUCCESS:
                logger.info("%s request SUCCESS", label)
            on_status(status)
            if identifier:
                logger.info("%s identifier: %s", label, identifier)

    def _build_level_dataset(self, study: StudyUIDHierarchy, level: RetrieveLevel, series=None, instance=None) -> Dataset:
        ds = Dataset()
        ds.StudyInstanceUID = study.uid
        if level == "STUDY":
            ds.QueryRetrieveLevel = "STUDY"
            return ds
        assert series is not None
        ds.SeriesInstanceUID = series.uid
        if series.number:
            ds.SeriesNumber = series.number
        if level == "SERIES":
            ds.QueryRetrieveLevel = "SERIES"
            return ds
        assert instance is not None
        ds.QueryRetrieveLevel = "IMAGE"
        ds.SOPInstanceUID = instance.uid
        if instance.number:
            ds.InstanceNumber = instance.number
        return ds

    def _open_retrieve_association(self, scp_name: str, modality: RetrieveModality):
        if modality == "GET":
            return self._connect_to_scp(
                scp_name,
                self.get_study_root_get_contexts(),
                evt_handlers=[(EVT_C_STORE, self._handle_store)],
                ext_neg=self._storage_scp_roles(),
            )
        return self._connect_to_scp(scp_name, self.get_study_root_move_contexts())

    def _send_retrieve(self, association, dataset: Dataset, *, modality: RetrieveModality, dest_scp_ae: str):
        if modality == "GET":
            return association.send_c_get(
                dataset=dataset,
                query_model=self._STUDY_ROOT_QR_CLASSES[2],
                priority=1,
            )
        return association.send_c_move(
            dataset=dataset,
            move_aet=dest_scp_ae,
            query_model=self._STUDY_ROOT_QR_CLASSES[1],
            priority=1,
        )

    def _status_table(self, modality: RetrieveModality):
        return QR_GET_SERVICE_CLASS_STATUS if modality == "GET" else QR_MOVE_SERVICE_CLASS_STATUS

    def _ingest_wado_datasets(self, scp_name: str, datasets) -> int:
        """Feed WADO-retrieved datasets into the anonymizer (peer of C-STORE SCP handler)."""
        node = self._resolve_remote(scp_name)
        count = 0
        for ds in datasets:
            if self._abort_move:
                raise DICOMRuntimeError("WADO retrieve aborted")
            time.sleep(self._handle_store_time_slice_interval)
            self.anonymizer.anonymize_dataset_ex(node, ds)
            count += 1
        return count

    def _retrieve_study_dicomweb(
        self,
        scp_name: str,
        study: StudyUIDHierarchy,
        level: RetrieveLevel,
    ) -> str | None:
        tag = f"WADO@{level}"
        logger.info("%s[%s] scp:%s", tag, study.uid, scp_name)
        error_msg = None
        if study is None or len(study.series) == 0:
            return "No Series in Study"
        target_count = study.get_number_of_instances()
        if target_count == 0:
            return "No Instances in Study"
        study.pending_instances = self.anonymizer.model.get_pending_instance_count(study.uid, target_count)
        if level != "INSTANCE" and study.pending_instances == 0:
            return "All Instances already imported"

        try:
            node = self._resolve_remote(scp_name)
            with dicomweb_api.open_session(node, self.model.network_timeouts) as session:
                if level == "STUDY":
                    datasets = dicomweb_api.iter_instances(
                        session, study_uid=study.uid, abort_check=lambda: self._abort_move
                    )
                    self._ingest_wado_datasets(scp_name, datasets)
                    self._wait_pending_instances(
                        study,
                        label=f"{tag}[{study.uid}]",
                        done_when=lambda s: s.pending_instances == 0,
                    )
                elif level == "SERIES":
                    for series in study.series.values():
                        if series.instance_count == 0:
                            continue
                        if self.anonymizer.model.series_complete(series.uid, series.instance_count):
                            continue
                        before = study.pending_instances
                        datasets = dicomweb_api.iter_instances(
                            session,
                            study_uid=study.uid,
                            series_uid=series.uid,
                            abort_check=lambda: self._abort_move,
                        )
                        self._ingest_wado_datasets(scp_name, datasets)
                        self._wait_pending_instances(
                            study,
                            label=f"{tag}[{study.uid}/{series.uid}]",
                            done_when=lambda s, b=before, n=series.instance_count: (b - s.pending_instances) >= n,
                        )
                else:
                    for series in study.series.values():
                        for instance in series.instances.values():
                            if self.anonymizer.model.instance_received(instance.uid):
                                continue
                            datasets = dicomweb_api.iter_instances(
                                session,
                                study_uid=study.uid,
                                series_uid=series.uid,
                                instance_uid=instance.uid,
                                abort_check=lambda: self._abort_move,
                            )
                            self._ingest_wado_datasets(scp_name, datasets)
                    self._wait_pending_instances(
                        study,
                        label=f"{tag}[{study.uid}]",
                        done_when=lambda s: s.pending_instances == 0,
                    )
            logger.info("%s study complete:\n%s", tag, study)
        except Exception as e:
            error_msg = str(e)
            study.last_error_msg = error_msg
            logger.error("%s", error_msg)
        return error_msg

    def _retrieve_study(
        self,
        scp_name: str,
        dest_scp_ae: str,
        study: StudyUIDHierarchy,
        level: RetrieveLevel,
        modality: RetrieveModality,
    ) -> str | None:
        if modality == "WADO":
            return self._retrieve_study_dicomweb(scp_name, study, level)

        tag = f"C-{modality}@{level}"
        logger.info("%s[%s] scp:%s dest:%s", tag, study.uid, scp_name, dest_scp_ae if modality == "MOVE" else "-")
        association = None
        error_msg = None

        if study is None or len(study.series) == 0:
            return "No Series in Study"
        target_count = study.get_number_of_instances()
        if target_count == 0:
            return "No Instances in Study"

        study.pending_instances = self.anonymizer.model.get_pending_instance_count(study.uid, target_count)
        # STUDY/SERIES early-out when fully imported; INSTANCE skips per-SOP and may return success with 0 ops
        if level != "INSTANCE" and study.pending_instances == 0:
            return "All Instances already imported"

        status_table = self._status_table(modality)

        try:
            if level == "STUDY":
                association = self._open_retrieve_association(scp_name, modality)
                ds = self._build_level_dataset(study, "STUDY")
                logger.info("%s[%s] Request instances=%s", tag, study.uid, study.get_number_of_instances())
                responses = self._send_retrieve(association, ds, modality=modality, dest_scp_ae=dest_scp_ae)

                def _on_status(status):
                    study.update_move_stats(status)
                    study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                        study.uid, study.get_number_of_instances()
                    )

                self._process_qr_statuses(
                    responses, label=f"{tag}[{study.uid}]", status_table=status_table, on_status=_on_status
                )
                self._wait_pending_instances(
                    study,
                    label=f"{tag}[{study.uid}]",
                    done_when=lambda s: s.pending_instances == 0,
                )

            elif level == "SERIES":
                for series in study.series.values():
                    if series.instance_count == 0:
                        logger.info("%s skip series %s instance_count=0", tag, series.uid)
                        continue
                    if self.anonymizer.model.series_complete(series.uid, series.instance_count):
                        logger.info("%s skip series %s already imported", tag, series.uid)
                        continue
                    association = self._open_retrieve_association(scp_name, modality)
                    before = study.pending_instances
                    ds = self._build_level_dataset(study, "SERIES", series=series)
                    logger.info(
                        "%s[%s/%s] Request modality=%s instances=%s",
                        tag,
                        study.uid,
                        series.uid,
                        series.modality,
                        series.instance_count,
                    )
                    responses = self._send_retrieve(association, ds, modality=modality, dest_scp_ae=dest_scp_ae)

                    def _on_series_status(status, series=series):
                        series.update_move_stats(status)
                        study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                            study.uid, study.get_number_of_instances()
                        )

                    self._process_qr_statuses(
                        responses,
                        label=f"{tag}[{study.uid}/{series.uid}]",
                        status_table=status_table,
                        on_status=_on_series_status,
                    )
                    self._wait_pending_instances(
                        study,
                        label=f"{tag}[{study.uid}/{series.uid}]",
                        done_when=lambda s, b=before, n=series.instance_count: (b - s.pending_instances) >= n,
                    )
                    association.release()
                    association = None

            else:  # INSTANCE
                association = self._open_retrieve_association(scp_name, modality)
                for series in study.series.values():
                    if len(series.instances) == 0:
                        logger.error("No instances in Series: %s skipping", series.uid)
                        continue
                    for instance in series.instances.values():
                        if self.anonymizer.model.instance_received(instance.uid):
                            continue
                        ds = self._build_level_dataset(study, "INSTANCE", series=series, instance=instance)
                        logger.info("%s[%s] request series=%s instance=%s", tag, study.uid, series.uid, instance.uid)
                        responses = self._send_retrieve(association, ds, modality=modality, dest_scp_ae=dest_scp_ae)

                        def _on_inst_status(status, series=series):
                            series.update_move_stats_instance_level(status)
                            study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                                study.uid, study.get_number_of_instances()
                            )

                        self._process_qr_statuses(
                            responses,
                            label=f"{tag}[{study.uid}/{series.uid}/{instance.uid}]",
                            status_table=status_table,
                            on_status=_on_inst_status,
                        )
                self._wait_pending_instances(
                    study,
                    label=f"{tag}[{study.uid}]",
                    done_when=lambda s: s.pending_instances == 0,
                )

            logger.info("%s study complete:\n%s", tag, study)

        except Exception as e:
            error_msg = str(e)
            study.last_error_msg = error_msg
            logger.error(error_msg)
        finally:
            if association:
                if self._abort_move:
                    association.abort()
                else:
                    association.release()
        return error_msg

    # Back-compat wrappers used by older Orthanc tests / callers
    def _move_study_at_study_level(self, scp_name: str, dest_scp_ae: str, study: StudyUIDHierarchy) -> str | None:
        return self._retrieve_study(scp_name, dest_scp_ae, study, "STUDY", "MOVE")

    def _move_study_at_series_level(self, scp_name: str, dest_scp_ae: str, study: StudyUIDHierarchy) -> str | None:
        return self._retrieve_study(scp_name, dest_scp_ae, study, "SERIES", "MOVE")

    def _move_study_at_instance_level(self, scp_name: str, dest_scp_ae: str, study: StudyUIDHierarchy) -> str | None:
        return self._retrieve_study(scp_name, dest_scp_ae, study, "INSTANCE", "MOVE")

    def bulk_move_active(self) -> bool:
        return self._move_futures is not None

    def manage_move(self, req: MoveStudiesRequest, *, force_move: bool = False) -> None:
        """Public retrieve entry point (C-GET preferred unless force_move)."""
        self._manage_move(req, force_move=force_move)

    def _manage_move(self, req: MoveStudiesRequest, *, force_move: bool = False) -> None:
        logger.info(
            "Import retrieve started for %s study(ies) at level=%s from SCP %s",
            len(req.studies),
            req.level,
            req.scp_name,
        )
        self._move_futures = []
        self._move_executor = ThreadPoolExecutor(
            max_workers=self._study_move_thread_pool_size,
            thread_name_prefix="MoveStudy",
        )
        level = self._normalize_retrieve_level(req.level)
        remote = self._resolve_remote(req.scp_name)
        if remote.dicomweb:
            modality: RetrieveModality = "WADO"
            logger.info(
                "Remote SCP %s is DICOMweb — retrieve uses WADO-RS (C-GET/C-MOVE not applicable)",
                req.scp_name,
            )
        else:
            use_force = force_move or getattr(req, "force_move", False)
            if use_force:
                modality = "MOVE"
                logger.info(
                    "Remote SCP %s retrieve forced to C-MOVE (force_move)",
                    req.scp_name,
                )
            else:
                modality = "GET" if self._probe_qr_get_support(req.scp_name) else "MOVE"
        self._last_retrieve_modality = modality
        logger.info(
            "Retrieve modality=%s level=%s studies=%s remote=%s",
            modality,
            level,
            len(req.studies),
            remote,
        )

        with self._move_executor as executor:
            for study in req.studies:
                future = executor.submit(
                    self._retrieve_study,
                    req.scp_name,
                    req.dest_scp_ae,
                    study,
                    level,
                    modality,
                )
                self._move_futures.append((future, modality, study))

            for future, __, study in self._move_futures:
                try:
                    error_msg = future.result()
                    if error_msg:
                        logger.warning("Study[%s] retrieve error: %s", study.uid, error_msg)
                except Exception as e:
                    logger.error("Study[%s] retrieve future exception: %s", study.uid, e)

        self._move_futures = None
        self._move_executor = None

    def move_studies_ex(self, mr: MoveStudiesRequest) -> None:
        threading.Thread(target=self._manage_move, name="ManageMove", args=(mr,), daemon=True).start()

    def abort_move(self):
        logger.info("Abort Move/Get")
        self._abort_move = True
        if self._move_executor:
            self._move_executor.shutdown(wait=True, cancel_futures=True)
        self._move_futures = None
        self._move_executor = None
        self._abort_move = False
