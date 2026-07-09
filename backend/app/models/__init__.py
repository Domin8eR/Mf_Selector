"""SQLAlchemy models package — imports all models so Alembic autogenerate detects them."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy models."""


# ---- Identity / auth (keep from M2) ----------------------------------------
from app.models.firm import Firm  # noqa: E402, F401
from app.models.user import User, UserRole  # noqa: E402, F401

# ---- Reference / master tables (v9) ----------------------------------------
from app.models.amc import AMC  # noqa: E402, F401
from app.models.category import Category  # noqa: E402, F401
from app.models.benchmark import Benchmark  # noqa: E402, F401
from app.models.scheme_plan import Scheme, SchemePlan  # noqa: E402, F401
from app.models.trading_calendar import TradingCalendar  # noqa: E402, F401

# ---- Versioning / ingestion (v9) -------------------------------------------
from app.models.data_version import (  # noqa: E402, F401
    DataVersion,
    DataVersionStatus,
    IngestionRun,
    IngestionRunStatus,
)

# ---- Time series (v9) -------------------------------------------------------
from app.models.nav import (  # noqa: E402, F401
    FundNavDaily,
    BenchmarkLevelDaily,
    FundReturnDaily,
    BenchmarkReturnDaily,
    ExcessReturnDaily,
)

# ---- Metrics (v9) ----------------------------------------------------------
from app.models.metrics import (  # noqa: E402, F401
    MetricDefinition,
    MetricValueSnapshot,
    RollingMetricValue,
)

# ---- Rules / governance (v9) -----------------------------------------------
from app.models.rules import (  # noqa: E402, F401
    RuleSet,
    RuleVersion,
    RuleVersionStatus,
    RuleComponent,
)

# ---- Rankings (v9) ---------------------------------------------------------
from app.models.rankings import (  # noqa: E402, F401
    RankingRun,
    RankingResult,
    RankingComponentContribution,
)

# ---- Governance (M4) -------------------------------------------------------
from app.models.governance import (  # noqa: E402, F401
    ApprovalRequest,
    ApprovalStatus,
    ApprovalComment,
    AuditEvent,
)

# ---- Data quality (M4) -----------------------------------------------------
from app.models.exceptions import (  # noqa: E402, F401
    DataQualityException,
    ExceptionSeverity,
    ExceptionStatus,
)

# ---- Chat / AI audit (M4) --------------------------------------------------
from app.models.chat import (  # noqa: E402, F401
    ChatThread,
    ChatMessage,
    ToolCallLog,
)

# ---- Comparison sessions ---------------------------------------------------
from app.models.comparison import ComparisonSession  # noqa: E402, F401
