import uuid

from fastapi import APIRouter, status

from api.dependencies import BotAuth, DBSession
from api.reviews import service as review_service
from api.reviews.schemas import ReviewCreate, ReviewRead

# A review belongs to a commission, so it is addressed through one.
router = APIRouter(prefix="/commissions", tags=["reviews"])


@router.post(
    "/{commission_id}/review",
    response_model=ReviewRead,
    status_code=status.HTTP_201_CREATED
)
async def create_commission_review(
        commission_id: uuid.UUID,
        body: ReviewCreate,
        db: DBSession,
        _auth: BotAuth
) -> ReviewRead:
    review = await review_service.create_review(db, commission_id, body)
    return ReviewRead.model_validate(review)
