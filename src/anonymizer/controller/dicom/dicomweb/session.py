"""DICOMweb HTTP session factory (transport peer to association._connect_to_scp)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import requests
from requests.auth import HTTPBasicAuth

from anonymizer.model.project import DICOMNode, NetworkTimeouts

logger = logging.getLogger(__name__)


@dataclass
class DicomWebSession:
    """Authenticated HTTP session bound to a DICOMweb root URL."""

    node: DICOMNode
    root: str
    http: requests.Session
    timeout: tuple[float, float]

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def url(self, *parts: str) -> str:
        """Join path segments under the DICOMweb root (no trailing slash on root)."""
        base = self.root.rstrip("/")
        segs = [p.strip("/") for p in parts if p and p.strip("/")]
        if not segs:
            return base
        return base + "/" + "/".join(segs)


def open_session(node: DICOMNode, timeouts: NetworkTimeouts) -> DicomWebSession:
    """Open a requests session for ``node`` using Basic Auth when credentials are set."""
    if not node.dicomweb:
        raise ValueError(f"Remote {node} does not have DICOMweb enabled")
    root = node.dicomweb_root()
    http = requests.Session()
    # Fail fast: do not retry refused/TLS failures (Test Connection must honor timeouts).
    adapter = requests.adapters.HTTPAdapter(max_retries=0)
    http.mount("http://", adapter)
    http.mount("https://", adapter)
    if node.username:
        http.auth = HTTPBasicAuth(node.username, node.password or "")
    http.headers.update({"Accept": "application/dicom+json, application/json, */*"})
    timeout = (float(timeouts.tcp_connection), float(timeouts.network))
    logger.debug("DICOMweb session root=%s auth=%s", root, bool(node.username))
    return DicomWebSession(node=node, root=root, http=http, timeout=timeout)


def probe_connection(node: DICOMNode, timeouts: NetworkTimeouts) -> tuple[bool, str]:
    """Verify DICOMweb reachability and auth via QIDO-RS studies?limit=1.

    Returns ``(success, message)``. HTTP 200/204 count as success; 401/403 as auth failure.
    Honors ``NetworkTimeouts.tcp_connection`` / ``network`` on the HTTP request.
    """
    from anonymizer.utils.translate import _

    if not node.dicomweb:
        return False, _("DICOMweb is not enabled for this node")
    try:
        with open_session(node, timeouts) as session:
            url = session.url("studies")
            resp = session.http.get(url, params=[("limit", "1")], timeout=session.timeout)
    except requests.Timeout:
        logger.error("DICOMweb probe timed out")
        return False, _("Connection timed out")
    except requests.ConnectionError as e:
        logger.error("DICOMweb probe failed: %s", e)
        detail = str(e).lower()
        if "refused" in detail:
            return False, _("Connection refused")
        if any(s in detail for s in ("name or service not known", "nodename nor servname", "getaddrinfo")):
            return False, _("Host not found")
        return False, _("Connection error")
    except requests.RequestException as e:
        logger.error("DICOMweb probe failed: %s", e)
        return False, str(e)
    except Exception as e:
        logger.error("DICOMweb probe failed: %s", e)
        return False, str(e)

    code = int(resp.status_code)
    if code in (200, 204):
        return True, _("DICOMweb connection successful")
    if code in (401, 403):
        return False, _("Authentication failed")
    return False, _("HTTP error ({code})").format(code=code)
