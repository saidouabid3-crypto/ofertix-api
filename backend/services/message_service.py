from repositories.message_repository import message_repository


class MessageService:
    def open_conversation(self, buyer_id: str, creator_id: str, reel_id: str = 'profile_contact', reel_title: str = 'Contacto desde Ofertix'):
        return message_repository.open_conversation(buyer_id=buyer_id, creator_id=creator_id, reel_id=reel_id, reel_title=reel_title)

    def send_message(self, conversation_id: str, sender_id: str, receiver_id: str, text: str):
        return message_repository.send_message(conversation_id=conversation_id, sender_id=sender_id, receiver_id=receiver_id, text=text)

    def list_messages(self, conversation_id: str, limit: int = 80):
        return {'items': message_repository.list_messages(conversation_id=conversation_id, limit=limit)}

    def list_user_conversations(self, user_id: str, limit: int = 50):
        return {'items': message_repository.list_user_conversations(user_id=user_id, limit=limit)}


message_service = MessageService()
