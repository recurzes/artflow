import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.commission import Commission, CommissionStatus
from shared.schemas.commission import CommissionCreate, QuoteCreate

VALID_TRANSITIONS: dict[CommissionStatus, set[CommissionStatus]] = {
    CommissionStatus.INQUIRY: {CommissionStatus.INTAKE, CommissionStatus.CANCELLED},
    CommissionStatus.INTAKE: {CommissionStatus.QUOTED, CommissionStatus.CANCELLED},
    CommissionStatus.QUOTED: {CommissionStatus.TOS_PENDING, CommissionStatus.CANCELLED},
    CommissionStatus.TOS_PENDING: {CommissionStatus.PAYMENT_PENDING, CommissionStatus.CANCELLED},
    CommissionStatus.PAYMENT_PENDING: {CommissionStatus.IN_PROGRESS, CommissionStatus.CANCELLED},
    CommissionStatus.IN_PROGRESS: {CommissionStatus.WIP, CommissionStatus.DISPUTED},
    CommissionStatus.WIP: {CommissionStatus.DELIVERED, CommissionStatus.DISPUTED},
    CommissionStatus.DELIVERED: {CommissionStatus.COMPLETED, CommissionStatus.DISPUTED},
    CommissionStatus.COMPLETED: set(),
    CommissionStatus.DISPUTED: {CommissionStatus.COMPLETED, CommissionStatus.CANCELLED},
    CommissionStatus.CANCELLED: set(),
}