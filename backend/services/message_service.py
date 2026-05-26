from repositories.message_repository import message_repository


class MessageService:
    def start_conversation(self, payload, current_user: dict):
        return message_repository.start_conversation(payload, current_user=current_user)

    def get_inbox(self, current_user: dict, limit: int = 50):
        return {'items': message_repository.get_inbox(current_user=current_user, limit=limit)}

    def get_conversation_messages(self, conversation_id: str, current_user: dict, limit: int = 80):
        return {
            'items': message_repository.list_messages(
                conversation_id=conversation_id,
                current_user=current_user,
                limit=limit,
            )
        }

    def send_message(self, conversation_id: str, payload, current_user: dict):
        sender_id = current_user['uid']
        sender_name = current_user.get('name') or current_user.get('email', '').split('@')[0] or 'Ofertix User'

        return message_repository.add_message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            sender_name=sender_name,
            text=payload.text,
        )

    def mark_read(self, conversation_id: str, current_user: dict):
        return message_repository.mark_read(conversation_id=conversation_id, current_user=current_user)


message_service = MessageService()
