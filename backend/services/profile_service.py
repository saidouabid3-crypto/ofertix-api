from repositories.profile_repository import profile_repository


class ProfileService:
    def get_profile(self, uid: str):
        profile = profile_repository.sync_creator_counters(uid)
        if profile:
            return profile
        return profile_repository.get_profile(uid)

    def get_creator_reels(self, uid: str, limit: int = 30):
        return profile_repository.get_creator_reels(creator_id=uid, limit=limit)

    def get_sell_items(self, uid: str, limit: int = 30):
        return profile_repository.get_sell_items(seller_id=uid, limit=limit)

    def update_profile(self, uid: str, data: dict):
        return profile_repository.update_profile(uid, data)

    def get_creator_profile(self, uid: str, limit: int = 30):
        profile = self.get_profile(uid)
        if not profile:
            return None
        return {
            'profile': profile,
            'reels': self.get_creator_reels(uid, limit=limit),
        }

    def follow_profile(self, uid: str, follower_uid: str):
        return profile_repository.follow_profile(target_uid=uid, follower_uid=follower_uid)

    def unfollow_profile(self, uid: str, follower_uid: str):
        return profile_repository.unfollow_profile(target_uid=uid, follower_uid=follower_uid)


profile_service = ProfileService()
