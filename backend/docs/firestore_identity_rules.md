# Firestore Identity Rules Note

Batch 11 public identity uses safe denormalized fields on `users`, `smart_reels`,
`smart_reel_comments`, `conversations`, and `marketplace_items`.

Rules checklist:

- Public reads may expose profile fields such as display name, username, avatar,
  bio, country, city, creator/seller counters, verification flags, and ratings.
- Public reads must not expose email, auth provider metadata, phone numbers, FCM
  tokens, payment data, admin flags, or private moderation notes.
- Users may write only their own `users/{uid}` mutable profile fields:
  `display_name`, `username`, `username_lower`, `photo_url`, `avatar_url`, `bio`,
  `country`, `city`, `currency`, and `is_creator`.
- Marketplace item creation and edits must require auth and must keep
  `sellerId`, `ownerId`, `userId`, and `creatorId` equal to the authenticated uid.
- Follow, comment, conversation, favorite, report, and message writes must require
  auth and derive user ids from the verified request, not from client-provided ids.
