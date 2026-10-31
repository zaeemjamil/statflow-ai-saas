"""
Every model must be imported here so `Base.metadata` is fully populated
- both for Alembic autogenerate (env.py imports this module) and for
`Base.metadata.create_all()` in tests. Adding a 10th model later means
adding one line here, nothing else.
"""

from app.models.analysis import Analysis, AnalysisStatus
from app.models.file import File, FileType
from app.models.password_reset_token import PasswordResetToken
from app.models.project import Project, ProjectStatus
from app.models.report import Report
from app.models.statistic import Statistic
from app.models.subscription import Subscription, SubscriptionPlan, SubscriptionStatus
from app.models.usage import UsageRecord
from app.models.user import User
from app.models.visualization import Visualization

__all__ = [
    "Analysis",
    "AnalysisStatus",
    "File",
    "FileType",
    "PasswordResetToken",
    "Project",
    "ProjectStatus",
    "Report",
    "Statistic",
    "Subscription",
    "SubscriptionPlan",
    "SubscriptionStatus",
    "UsageRecord",
    "User",
    "Visualization",
]
