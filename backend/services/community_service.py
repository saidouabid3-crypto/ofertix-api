from repositories.community_repository import community_repository


class CommunityService:
    def vote(self, payload):
        return community_repository.vote(
            target_type=payload.target_type,
            target_id=payload.target_id,
            user_id=payload.user_id,
            vote=payload.vote,
        )

    def summary(self, target_type: str, target_id: str, user_id: str | None = None):
        return community_repository.get_summary(
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
        )


community_service = CommunityService()
