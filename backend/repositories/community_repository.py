from datetime import datetime
from typing import Optional

from core.firebase import db


class CommunityRepository:
    VOTES_COLLECTION = 'community_votes'
    TARGET_COLLECTIONS = {
        'reel': 'smart_reels',
        'product': 'products',
        'coupon': 'coupons',
        'user_deal': 'user_generated_deals',
    }

    def __init__(self):
        self.votes = db.collection(self.VOTES_COLLECTION)

    def vote(self, target_type: str, target_id: str, user_id: str, vote: str) -> dict:
        target_type = target_type.strip()
        target_id = target_id.strip()
        user_id = user_id.strip()
        vote = vote.strip().lower()
        now = datetime.utcnow().isoformat()
        vote_id = f'{target_type}_{target_id}_{user_id}'
        ref = self.votes.document(vote_id)
        snap = ref.get()

        previous_vote = None
        created_at = now
        if snap.exists:
            old = snap.to_dict() or {}
            previous_vote = old.get('vote')
            created_at = old.get('created_at') or now

        data = {
            'id': vote_id,
            'target_type': target_type,
            'target_id': target_id,
            'user_id': user_id,
            'vote': vote,
            'created_at': created_at,
            'updated_at': now,
        }
        ref.set(data)
        self._sync_target_summary(target_type, target_id, previous_vote=previous_vote, next_vote=vote)
        return data

    def get_summary(self, target_type: str, target_id: str, user_id: Optional[str] = None) -> dict:
        target_type = target_type.strip()
        target_id = target_id.strip()
        docs = list(
            self.votes.where('target_type', '==', target_type)
            .where('target_id', '==', target_id)
            .stream()
        )
        hot_votes = 0
        cold_votes = 0
        user_vote = None
        for doc in docs:
            data = doc.to_dict() or {}
            if data.get('vote') == 'hot':
                hot_votes += 1
            elif data.get('vote') == 'cold':
                cold_votes += 1
            if user_id and data.get('user_id') == user_id:
                user_vote = data.get('vote')
        hot_score = self._calculate_score(hot_votes, cold_votes)
        return {
            'target_type': target_type,
            'target_id': target_id,
            'hot_votes': hot_votes,
            'cold_votes': cold_votes,
            'hot_score': hot_score,
            'temperature': hot_score,
            'user_vote': user_vote,
        }

    def _sync_target_summary(self, target_type: str, target_id: str, previous_vote: Optional[str], next_vote: str) -> None:
        collection = self.TARGET_COLLECTIONS.get(target_type)
        if not collection:
            return
        ref = db.collection(collection).document(target_id)
        snap = ref.get()
        current = snap.to_dict() if snap.exists else {}
        hot_votes = int((current or {}).get('hot_votes', 0))
        cold_votes = int((current or {}).get('cold_votes', 0))

        if previous_vote == next_vote:
            pass
        else:
            if previous_vote == 'hot':
                hot_votes = max(0, hot_votes - 1)
            if previous_vote == 'cold':
                cold_votes = max(0, cold_votes - 1)
            if next_vote == 'hot':
                hot_votes += 1
            if next_vote == 'cold':
                cold_votes += 1

        hot_score = self._calculate_score(hot_votes, cold_votes)
        ref.set({
            'hot_votes': hot_votes,
            'cold_votes': cold_votes,
            'hot_score': hot_score,
            'temperature': hot_score,
            'updated_at': datetime.utcnow().isoformat(),
        }, merge=True)

    @staticmethod
    def _calculate_score(hot_votes: int, cold_votes: int) -> int:
        total = hot_votes + cold_votes
        if total <= 0:
            return 50
        return max(0, min(100, round((hot_votes / total) * 100)))


community_repository = CommunityRepository()
