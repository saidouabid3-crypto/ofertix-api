from repositories.mystery_box_repository import mystery_box_repository


class MysteryBoxService:
    def today(self, current_user: dict):
        return mystery_box_repository.get_today_box(user_id=current_user['uid'])

    def open(self, payload, current_user: dict):
        return mystery_box_repository.open_today_box(
            user_id=current_user['uid'],
            unlock_method=payload.unlock_method,
            riddle_answer=payload.riddle_answer,
            client_nonce=payload.client_nonce,
        )

    def claim(self, payload, current_user: dict):
        return mystery_box_repository.claim_reward(user_id=current_user['uid'], reward_id=payload.reward_id)

    def history(self, current_user: dict, limit: int = 30):
        return {'items': mystery_box_repository.history(user_id=current_user['uid'], limit=limit)}


mystery_box_service = MysteryBoxService()
