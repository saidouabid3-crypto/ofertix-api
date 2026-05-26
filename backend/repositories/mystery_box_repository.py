from datetime import datetime, timedelta
from uuid import uuid4

from core.firebase import db


class MysteryBoxRepository:
    BOXES = 'mystery_boxes'
    OPENS = 'mystery_box_opens'
    REWARDS = 'mystery_box_rewards'
    USER_STREAKS = 'user_streaks'

    def __init__(self):
        self.boxes = db.collection(self.BOXES)
        self.opens = db.collection(self.OPENS)
        self.rewards = db.collection(self.REWARDS)
        self.streaks = db.collection(self.USER_STREAKS)

    def day_key(self) -> str:
        return datetime.utcnow().strftime('%Y-%m-%d')

    def get_today_box(self, user_id: str) -> dict:
        day_key = self.day_key()
        box_id = f'box_{day_key}'
        box_ref = self.boxes.document(box_id)
        snap = box_ref.get()
        now = datetime.utcnow().isoformat()

        if not snap.exists:
            box = {
                'id': box_id,
                'title': 'Blind Deal Box',
                'subtitle': 'Tu hamza secreta diaria está lista.',
                'reveal_hint': 'Agita el móvil o resuelve el mini reto para revelar la oferta.',
                'unlock_type': 'shake',
                'day_key': day_key,
                'status': 'active',
                'pool': [
                    {
                        'reward_type': 'coins',
                        'title': '+25 Ofertix Coins',
                        'description': 'Premio diario para aumentar tu racha.',
                        'value_label': '+25 coins',
                        'coins': 25,
                        'cashback_boost': 0,
                        'coupon_code': '',
                        'deal_url': '',
                    },
                    {
                        'reward_type': 'cashback_boost',
                        'title': 'Cashback Boost secreto',
                        'description': 'Boost simbólico para futuras compras verificadas.',
                        'value_label': '+2% boost',
                        'coins': 10,
                        'cashback_boost': 2,
                        'coupon_code': '',
                        'deal_url': '',
                    },
                    {
                        'reward_type': 'secret_deal',
                        'title': 'Hamza secreta del día',
                        'description': 'Oferta especial recomendada por Ofertix AI.',
                        'value_label': 'Secret deal',
                        'coins': 15,
                        'cashback_boost': 0,
                        'coupon_code': 'OFERTIXSECRET',
                        'deal_url': 'https://ofertix.app',
                    },
                ],
                'created_at': now,
                'updated_at': now,
            }
            box_ref.set(box)
        else:
            box = snap.to_dict() or {}
            box['id'] = box.get('id') or box_id

        open_id = self._open_id(user_id, day_key)
        open_snap = self.opens.document(open_id).get()
        is_opened = open_snap.exists
        opened = open_snap.to_dict() or {} if is_opened else {}
        streak = self.get_streak(user_id)

        box['is_opened'] = is_opened
        box['can_open'] = not is_opened and box.get('status') == 'active'
        box['opened_at'] = opened.get('opened_at')
        box['streak'] = streak
        return self._public_box(box)

    def open_today_box(self, user_id: str, unlock_method: str, riddle_answer: str = '', client_nonce: str = '') -> dict:
        box = self.get_today_box(user_id)
        if box.get('is_opened'):
            existing = self.get_today_reward(user_id)
            if existing:
                return existing
            raise ValueError('Box already opened today')

        if unlock_method == 'riddle' and riddle_answer.strip() and len(riddle_answer.strip()) < 2:
            raise ValueError('Invalid riddle answer')

        day_key = self.day_key()
        now_dt = datetime.utcnow()
        now = now_dt.isoformat()
        box_id = box['id']
        reward = self._choose_reward(box_id=box_id, user_id=user_id)
        reward_id = f'reward_{uuid4().hex[:14]}'
        share_text = f"شنو طاح ليك فـ Ofertix Blind Box اليوم؟ أنا لقيت: {reward['title']} 📦🔥"

        item = {
            'id': reward_id,
            'box_id': box_id,
            'user_id': user_id,
            'reward_type': reward.get('reward_type', 'coins'),
            'title': reward.get('title', 'Ofertix Reward'),
            'description': reward.get('description', ''),
            'value_label': reward.get('value_label', ''),
            'coupon_code': reward.get('coupon_code', ''),
            'deal_url': reward.get('deal_url', ''),
            'product_id': reward.get('product_id'),
            'coins': int(reward.get('coins', 0) or 0),
            'cashback_boost': float(reward.get('cashback_boost', 0) or 0),
            'share_text': share_text,
            'claimed': False,
            'opened_at': now,
            'expires_at': (now_dt + timedelta(days=2)).date().isoformat(),
            'created_at': now,
            'updated_at': now,
        }

        self.rewards.document(reward_id).set(item)
        self.opens.document(self._open_id(user_id, day_key)).set({
            'id': self._open_id(user_id, day_key),
            'user_id': user_id,
            'box_id': box_id,
            'reward_id': reward_id,
            'unlock_method': unlock_method,
            'client_nonce': client_nonce,
            'opened_at': now,
            'created_at': now,
        })
        self._update_streak(user_id)
        return self._normalize_reward(item)

    def claim_reward(self, user_id: str, reward_id: str) -> dict | None:
        snap = self.rewards.document(reward_id).get()
        if not snap.exists:
            return None
        reward = snap.to_dict() or {}
        if reward.get('user_id') != user_id:
            return None
        if reward.get('claimed') is True:
            return {'ok': True, 'claimed': True, 'reward_id': reward_id, 'message': 'Reward already claimed'}
        self.rewards.document(reward_id).set({'claimed': True, 'updated_at': datetime.utcnow().isoformat()}, merge=True)
        return {'ok': True, 'claimed': True, 'reward_id': reward_id, 'message': 'Reward claimed successfully'}

    def history(self, user_id: str, limit: int = 30) -> list[dict]:
        docs = list(self.rewards.where('user_id', '==', user_id).limit(max(1, min(limit, 50))).stream())
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(self._normalize_reward(data))
        items.sort(key=lambda x: str(x.get('opened_at') or ''), reverse=True)
        return items

    def get_today_reward(self, user_id: str) -> dict | None:
        day_key = self.day_key()
        open_snap = self.opens.document(self._open_id(user_id, day_key)).get()
        if not open_snap.exists:
            return None
        reward_id = (open_snap.to_dict() or {}).get('reward_id')
        if not reward_id:
            return None
        reward_snap = self.rewards.document(reward_id).get()
        if not reward_snap.exists:
            return None
        data = reward_snap.to_dict() or {}
        data['id'] = data.get('id') or reward_id
        return self._normalize_reward(data)

    def get_streak(self, user_id: str) -> int:
        snap = self.streaks.document(user_id).get()
        if not snap.exists:
            return 0
        return int((snap.to_dict() or {}).get('mystery_box_streak', 0) or 0)

    def _update_streak(self, user_id: str) -> None:
        now = datetime.utcnow()
        today = now.date().isoformat()
        yesterday = (now - timedelta(days=1)).date().isoformat()
        ref = self.streaks.document(user_id)
        snap = ref.get()
        data = snap.to_dict() or {} if snap.exists else {}
        last = str(data.get('last_mystery_box_day') or '')
        current = int(data.get('mystery_box_streak', 0) or 0)
        if last == today:
            streak = current
        elif last == yesterday:
            streak = current + 1
        else:
            streak = 1
        ref.set({'user_id': user_id, 'mystery_box_streak': streak, 'last_mystery_box_day': today, 'updated_at': now.isoformat()}, merge=True)

    def _choose_reward(self, box_id: str, user_id: str) -> dict:
        snap = self.boxes.document(box_id).get()
        data = snap.to_dict() or {}
        pool = data.get('pool') or []
        if not pool:
            return {'reward_type': 'coins', 'title': '+20 Ofertix Coins', 'description': '', 'value_label': '+20 coins', 'coins': 20}
        index = abs(hash(f'{box_id}:{user_id}')) % len(pool)
        return dict(pool[index])

    def _open_id(self, user_id: str, day_key: str) -> str:
        return f'{user_id}_{day_key}'

    def _public_box(self, box: dict) -> dict:
        clean = {k: v for k, v in box.items() if k != 'pool'}
        for k in ['subtitle', 'reveal_hint', 'status']:
            clean[k] = str(clean.get(k) or '')
        return clean

    def _normalize_reward(self, item: dict) -> dict:
        item['description'] = str(item.get('description') or '')
        item['value_label'] = str(item.get('value_label') or '')
        item['coupon_code'] = str(item.get('coupon_code') or '')
        item['deal_url'] = str(item.get('deal_url') or '')
        item['coins'] = int(item.get('coins', 0) or 0)
        item['cashback_boost'] = float(item.get('cashback_boost', 0) or 0)
        item['share_text'] = str(item.get('share_text') or '')
        return item


mystery_box_repository = MysteryBoxRepository()
