# TODO: PROJECT MANAGEMENT, separate directory (use storage directory) per project for config.json and lookup tables
# Single Document Interface (SDI) globals, one project open at a time
import logging
from typing import Dict, Tuple, List
from utils.translate import _
import model.config as config

logger = logging.getLogger(__name__)

# Default project globals:
SITEID = "999999"
PROJECTNAME = "DEFAULT-PROJECT"
TRIALNAME = "DEFAULT-TRIAL"
UIDROOT = "1.2.826.0.1.3680043.10.474"

# TODO: move to pandas dataframe and/or sqlite db, hf5, parquet, pickle
patient_id_lookup: Dict[str, str] = {}
uid_lookup: Dict[str, str] = {}
acc_no_lookup: Dict[str, str] = {}
phi_lookup: Dict[str, Tuple[str, str, List[Tuple[str, str, str, str]]]] = {}


# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)

# config.save(__name__, "SITEID", SITEID)
# config.save(__name__, "PROJECTNAME", PROJECTNAME)
# config.save(__name__, "TRIALNAME", TRIALNAME)
# config.save(__name__, "UIDROOT", UIDROOT)


def clear_lookups():
    global patient_id_lookup, uid_lookup, acc_no_lookup
    patient_id_lookup.clear()
    uid_lookup.clear()
    acc_no_lookup.clear()
    phi_lookup.clear()


def update_lookups():
    config.save_bulk(
        __name__,
        {
            "patient_id_lookup": patient_id_lookup,
            "uid_lookup": uid_lookup,
            "acc_no_lookup": acc_no_lookup,
            "phi_lookup": phi_lookup,
        },
    )
