"""Import every model so Base.metadata (and Alembic) can see all tables."""

from backend.models.complaint_draft import ComplaintDraft
from backend.models.consent_receipt import ConsentReceipt
from backend.models.incident import Incident
from backend.models.leak_edge import LeakEdge
from backend.models.mail_log import MailLog
from backend.models.report import Report
from backend.models.signup import Signup
from backend.models.user import User

__all__ = [
    "ComplaintDraft",
    "ConsentReceipt",
    "Incident",
    "LeakEdge",
    "MailLog",
    "Report",
    "Signup",
    "User",
]
