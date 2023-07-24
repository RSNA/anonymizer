# TODO: PROJECT MANAGEMENT, separate directory per project for config.json, log.txt, and index.db
# Single Document Interface (SDI) globals, one project open at a time
import logging
from utils.translate import _
import utils.config as config

logger = logging.getLogger(__name__)

SITEID = "DEFAULT-SITE"
PROJECTNAME = "DEFAULT-PROJECT"
TRIALNAME = "DEFAULT-TRIAL"
UIDROOT = "1.2.826.0.1.3680043.10.474"


# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)
config.save(__name__, "SITEID", SITEID)
config.save(__name__, "PROJECTNAME", PROJECTNAME)
config.save(__name__, "TRIALNAME", TRIALNAME)
config.save(__name__, "UIDROOT", UIDROOT)
