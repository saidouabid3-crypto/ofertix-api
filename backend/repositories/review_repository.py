from datetime import datetime, timezone
from typing import Optional

from core.firebase import db
from repositories.message_repository import MessageRepository

REVIEWS_COLLECTION = 'marketplace_reviews'
MESSAGES_COLLECTION = 'chat_messages'
USERS_COLLECTION = 'users'


class _UnavailableCollection:
    def _raise(self):
        raise RuntimeError('Firestore is not configured for marketplace reviews')

    def document(self, *_args, **_kwargs):
        self._raise()

    def where(self, *_args, **_kwargs):
        self._raise()


class ReviewRepository:
    def __init__(self):
        if db is None:
            unavailable = _UnavailableCollection()
            self.reviews = unavailable
            self.messages = unavailable
            self.users = unavailable
            return
        self.reviews = db.collection(REVIEWS_COLLECTION)
        self.messages = db.collection(MESSAGES_COLLECTION)
        self.users = db.collection(USERS_COLLECTION)

    def create_review(
        self,
        *,
        reviewer_id: str,
        reviewer_name: str,
        reviewee_id: str,
        listing_id: str,
        conversation_id: str,
        rating: int,
        comment: str,
    ) -> dict:
        reviewer_id = str(reviewer_id or '').strip()
        reviewee_id = str(reviewee_id or '').strip()
        listing_id = str(listing_id or '').strip()

        if not reviewer_id or not reviewee_id or not listing_id:
            raise ValueError('Invalid review request')
        if reviewer_id == reviewee_id:
            raise PermissionError('You cannot review yourself')

        conversation = self._resolve_conversation(
            reviewer_id=reviewer_id,
            reviewee_id=reviewee_id,
            listing_id=listing_id,
            conversation_id=conversation_id,
        )
        if not conversation:
            raise PermissionError('You must interact with this seller before reviewing')

        review_id = f'{listing_id}_{reviewer_id}_{reviewee_id}'
        review_ref = self.reviews.document(review_id)
        if review_ref.get().exists:
            raise ValueError('You already reviewed this listing')

        now = datetime.now(timezone.utc).isoformat()
        review = {
            'id': review_id,
            'listing_id': listing_id,
            'conversation_id': conversation.get('id', ''),
            'reviewer_id': reviewer_id,
            'reviewer_name': reviewer_name or 'User',
            'reviewee_id': reviewee_id,
            'rating': int(rating),
            'comment': str(comment or '').strip()[:500],
            'status': 'active',
            'created_at': now,
            'updated_at': now,
        }
        review_ref.set(review)
        self._update_rating_aggregate(reviewee_id, int(rating))
        return review

    def list_reviews_for_user(self, uid: str, limit: int = 20) -> dict:
        uid = str(uid or '').strip()
        if not uid:
            return {'items': [], 'average': 0, 'count': 0}

        limit = max(1, min(limit, 50))
        docs = list(
            self.reviews
            .where('reviewee_id', '==', uid)
            .where('status', '==', 'active')
            .limit(limit)
            .stream()
        )
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(data)
        items.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)

        profile_snap = self.users.document(uid).get()
        profile_data = profile_snap.to_dict() or {} if profile_snap.exists else {}
        average = float(profile_data.get('rating_average') or 0)
        count = int(profile_data.get('rating_count') or 0)
        return {'items': items, 'average': average, 'count': count}

    def _resolve_conversation(
        self,
        *,
        reviewer_id: str,
        reviewee_id: str,
        listing_id: str,
        conversation_id: str,
    ) -> Optional[dict]:
        message_repo = MessageRepository()
        conversation_id = str(conversation_id or '').strip()
        if not conversation_id:
            legacy_listing_id = (
                f'conv_{reviewer_id}_{reviewee_id}_marketplace_{listing_id}'
            )
            for candidate_id in (
                message_repo._conversation_id(reviewer_id, reviewee_id),
                message_repo._old_conversation_id(reviewer_id, reviewee_id),
                legacy_listing_id,
            ):
                conversation = message_repo.get_conversation(
                    candidate_id,
                    current_user={'uid': reviewer_id},
                )
                if conversation:
                    conversation_id = candidate_id
                    break
            else:
                conversation = None
        else:
            conversation = message_repo.get_conversation(
                conversation_id, current_user={'uid': reviewer_id}
            )
        if not conversation:
            return None
        if reviewee_id not in (conversation.get('participants') or []):
            return None
        if conversation.get('listing_id') and conversation.get('listing_id') != listing_id:
            return None

        has_message = list(
            self.messages
            .where('conversation_id', '==', conversation_id)
            .limit(1)
            .stream()
        )
        if not has_message:
            return None

        return conversation

    def _update_rating_aggregate(self, uid: str, rating: int) -> None:
        from google.cloud.firestore_v1 import Increment

        user_ref = self.users.document(uid)
        user_ref.set(
            {
                'rating_sum': Increment(rating),
                'rating_count': Increment(1),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            },
            merge=True,
        )
        snap = user_ref.get()
        data = snap.to_dict() or {}
        rating_sum = float(data.get('rating_sum') or 0)
        rating_count = int(data.get('rating_count') or 0)
        average = round(rating_sum / rating_count, 2) if rating_count > 0 else 0
        user_ref.set({'rating_average': average}, merge=True)


review_repository = ReviewRepository()
