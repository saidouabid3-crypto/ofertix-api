from repositories.review_repository import review_repository


class ReviewService:
    def create_review(self, payload, current_user: dict):
        reviewer_id = current_user['uid']
        reviewer_name = (
            current_user.get('name')
            or current_user.get('email', '').split('@')[0]
            or 'User'
        )
        return review_repository.create_review(
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            reviewee_id=payload.reviewee_id,
            listing_id=payload.listing_id,
            conversation_id=payload.conversation_id,
            rating=payload.rating,
            comment=payload.comment,
        )

    def list_reviews_for_user(self, uid: str, limit: int = 20):
        return review_repository.list_reviews_for_user(uid=uid, limit=limit)


review_service = ReviewService()
