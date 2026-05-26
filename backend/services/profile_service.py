from repositories.profile_repository import profile_repository


class ProfileService:
    def get_profile(self, uid: str):
        profile = profile_repository.sync_creator_counters(uid)
        if profile:
            return profile
        return profile_repository.get_profile(uid)

    def get_creator_reels(self, uid: str, limit: int = 30):
        return profile_repository.get_creator_reels(creator_id=uid, limit=limit)

    def get_creator_profile(self, uid: str, limit: int = 30):
        profile = self.get_profile(uid)
        if not profile:
            return None
        return {
            'profile': profile,
            'reels': self.get_creator_reels(uid, limit=limit),
        }


profile_service = ProfileService()
