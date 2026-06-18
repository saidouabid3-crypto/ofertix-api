"""
Canonical conversation migration — Batch 16F-D
================================================

Merges legacy per-listing / per-reel conversation documents into one canonical
conversation per user pair.

Background
----------
Prior to Batch 16F-D, _conversation_id() appended a context suffix, so a buyer
and a seller could accumulate multiple Firestore documents:

  conv_{a}_{b}_general
  conv_{a}_{b}_marketplace_{listing_id_1}
  conv_{a}_{b}_marketplace_{listing_id_2}
  conv_{a}_{b}_{reel_id}

After 16F-D the canonical ID is always conv_{a}_{b}.  This script:

  1. Detects all duplicate groups (same sorted participant pair, different IDs).
  2. Resolves / creates the canonical conversation document.
  3. Copies every message from legacy conversations into the canonical one.
  4. Stamps legacy documents status=merged + merged_into=<canonical_id>.
  5. Is idempotent — already-merged conversations are skipped.

Usage
-----
  # Dry run (inspect only, no writes)
  python scripts/migrate_conversations_canonical.py --dry-run

  # Apply the migration
  python scripts/migrate_conversations_canonical.py --apply

  # Limit to N pairs for a smoke test
  python scripts/migrate_conversations_canonical.py --apply --limit 5

Safety
------
  * Messages are COPIED, not deleted.  Legacy documents are only marked merged.
  * Run --dry-run first and inspect the report.
  * Run --apply twice — it is safe (idempotent).
  * Original message IDs and timestamps are preserved.
  * A migration marker (migration_16fd_done: true) is written to each canonical
    conversation so you can verify completion.
"""

import argparse
import os
import sys
import logging
from collections import defaultdict
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Bootstrap: add backend root to sys.path so Firebase initialises correctly
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, BACKEND_DIR)

from core.firebase import db  # noqa: E402 (must be after sys.path patch)

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('migrate_canonical')

CONVERSATIONS = 'conversations'
MESSAGES = 'chat_messages'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _canonical_id(participants: list[str]) -> str:
    a, b = sorted(participants)
    return f'conv_{a}_{b}'


def _sorted_pair(participants: list[str]) -> tuple[str, str]:
    a, b = sorted(participants)
    return (a, b)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Step 1: scan all conversations, group by canonical pair
# ---------------------------------------------------------------------------

def scan_conversations() -> dict[tuple[str, str], list[dict]]:
    """Return {(uid_a, uid_b): [conv_dict, ...]} for all pairs with ≥ 1 doc."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    total = 0

    for doc in db.collection(CONVERSATIONS).stream():
        data = doc.to_dict() or {}
        data['id'] = data.get('id') or doc.id
        participants = data.get('participants') or []

        if len(set(participants)) < 2:
            continue

        pair = _sorted_pair(participants[:2])
        groups[pair].append(data)
        total += 1

    logger.info('Scanned %d conversation documents across %d pairs.', total, len(groups))
    return dict(groups)


# ---------------------------------------------------------------------------
# Step 2: classify each pair
# ---------------------------------------------------------------------------

def classify(groups: dict) -> tuple[list, list]:
    """Return (pairs_needing_migration, pairs_already_ok)."""
    need_migration = []
    already_ok = []

    for pair, convs in groups.items():
        canonical_id = _canonical_id(list(pair))
        # Check for already-merged legacy docs
        active = [c for c in convs if c.get('status') != 'merged']
        if len(active) <= 1:
            already_ok.append((pair, convs))
            continue

        # More than one active conversation — needs merging
        need_migration.append((pair, convs))

    return need_migration, already_ok


# ---------------------------------------------------------------------------
# Dry run report
# ---------------------------------------------------------------------------

def dry_run(groups: dict) -> None:
    need, ok = classify(groups)
    total_legacy_msgs = 0

    print(f'\n{"="*60}')
    print('DRY RUN — no writes will be performed')
    print(f'{"="*60}')
    print(f'Total pairs:              {len(groups)}')
    print(f'Pairs already canonical:  {len(ok)}')
    print(f'Pairs needing migration:  {len(need)}')
    print()

    for pair, convs in need[:50]:  # cap output at 50 for readability
        canonical_id = _canonical_id(list(pair))
        active = [c for c in convs if c.get('status') != 'merged']
        legacy = [c for c in active if c['id'] != canonical_id]
        canonical_exists = any(c['id'] == canonical_id for c in active)

        msg_count = sum(
            len(list(db.collection(MESSAGES).where('conversation_id', '==', c['id']).stream()))
            for c in legacy
        )
        total_legacy_msgs += msg_count

        print(f'  Pair ({pair[0][:8]}… / {pair[1][:8]}…)')
        print(f'    Canonical ID  : {canonical_id}')
        print(f'    Canonical exists: {canonical_exists}')
        print(f'    Legacy convs  : {len(legacy)}')
        for c in legacy:
            ctx = c.get('listing_id') or c.get('reel_id') or 'direct'
            print(f'      - {c["id"]}  (context={ctx})')
        print(f'    Messages to move: {msg_count}')
        print()

    if len(need) > 50:
        print(f'  … and {len(need) - 50} more pairs (output truncated)')

    print(f'Total legacy messages to migrate: {total_legacy_msgs}')
    print()
    print('Run with --apply to execute.')


# ---------------------------------------------------------------------------
# Apply migration for one pair
# ---------------------------------------------------------------------------

def migrate_pair(pair: tuple[str, str], convs: list[dict], dry: bool = False) -> dict:
    uid_a, uid_b = pair
    canonical_id = _canonical_id([uid_a, uid_b])
    now = _now()

    active = [c for c in convs if c.get('status') != 'merged']
    canonical_conv = next((c for c in active if c['id'] == canonical_id), None)
    legacy_convs = [c for c in active if c['id'] != canonical_id]

    if not legacy_convs:
        return {'pair': pair, 'skipped': True, 'reason': 'no_legacy'}

    # ------ Resolve / create canonical document ------
    if canonical_conv is None:
        # Pick the richest legacy doc as the template for the canonical document
        # (prefer marketplace one because it has listing_id / buyer_id / seller_id)
        template = sorted(
            legacy_convs,
            key=lambda c: (
                1 if c.get('listing_id') else 0,
                str(c.get('last_message_at') or ''),
            ),
            reverse=True,
        )[0]

        canonical_data = dict(template)
        canonical_data['id'] = canonical_id
        canonical_data['updated_at'] = now
        canonical_data['migration_16fd_done'] = True

        if not dry:
            db.collection(CONVERSATIONS).document(canonical_id).set(
                canonical_data, merge=True
            )
        logger.info('[%s] Created canonical conversation.', canonical_id)
    else:
        if not dry:
            db.collection(CONVERSATIONS).document(canonical_id).set(
                {'migration_16fd_done': True, 'updated_at': now},
                merge=True,
            )

    # ------ Copy messages from each legacy doc to canonical ------
    messages_moved = 0
    seen_original_ids: set[str] = set()

    # First, collect IDs already in canonical to avoid duplicates
    if not dry:
        for msg_doc in db.collection(MESSAGES).where('conversation_id', '==', canonical_id).stream():
            md = msg_doc.to_dict() or {}
            orig_id = md.get('original_message_id') or md.get('id') or msg_doc.id
            seen_original_ids.add(orig_id)

    for legacy in legacy_convs:
        legacy_id = legacy['id']
        legacy_context = legacy.get('listing_id') or legacy.get('reel_id') or 'direct'

        # Derive context fields from the legacy conversation document for messages
        # that pre-date the per-message context schema
        legacy_context_type = ''
        legacy_context_id = ''
        legacy_context_title = ''
        legacy_context_thumbnail = ''
        legacy_context_price = None
        legacy_context_currency = ''

        if legacy.get('listing_id'):
            legacy_context_type = 'marketplace_listing'
            legacy_context_id = str(legacy['listing_id'])
            legacy_context_title = str(legacy.get('listing_title') or '')
            legacy_context_thumbnail = str(legacy.get('listing_image') or '')
            legacy_context_price = float(legacy.get('listing_price') or 0) or None
            legacy_context_currency = str(legacy.get('listing_currency') or '')
        elif legacy.get('reel_id'):
            legacy_context_type = 'reel'
            legacy_context_id = str(legacy['reel_id'])
            legacy_context_title = str(legacy.get('reel_title') or '')
            legacy_context_thumbnail = str(legacy.get('reel_thumbnail_url') or '')

        try:
            msg_docs = list(
                db.collection(MESSAGES)
                .where('conversation_id', '==', legacy_id)
                .stream()
            )
        except Exception as exc:
            logger.warning('[%s] Failed to list messages: %s', legacy_id, exc)
            msg_docs = []

        for msg_doc in msg_docs:
            md = msg_doc.to_dict() or {}
            original_msg_id = md.get('id') or msg_doc.id

            if original_msg_id in seen_original_ids:
                continue  # already migrated (idempotent)

            new_msg = dict(md)
            new_msg['id'] = original_msg_id
            new_msg['conversation_id'] = canonical_id
            new_msg['original_message_id'] = original_msg_id
            new_msg['source_conversation_id'] = legacy_id

            # Backfill context fields for messages that pre-date the context schema
            if not new_msg.get('context_type') and legacy_context_type:
                new_msg['context_type'] = legacy_context_type
                new_msg['context_id'] = legacy_context_id
                new_msg['context_title'] = legacy_context_title
                new_msg['context_thumbnail_url'] = legacy_context_thumbnail
                new_msg['context_price'] = legacy_context_price
                new_msg['context_currency'] = legacy_context_currency

            if not dry:
                db.collection(MESSAGES).document(original_msg_id).set(new_msg, merge=True)
            seen_original_ids.add(original_msg_id)
            messages_moved += 1

        logger.info(
            '[%s] Moved %d messages from legacy conv %s (context=%s)',
            canonical_id, messages_moved, legacy_id, legacy_context,
        )

        # Mark legacy as merged
        if not dry:
            db.collection(CONVERSATIONS).document(legacy_id).set(
                {
                    'status': 'merged',
                    'merged_into': canonical_id,
                    'merged_at': now,
                    'updated_at': now,
                },
                merge=True,
            )

    return {
        'pair': pair,
        'canonical_id': canonical_id,
        'legacy_count': len(legacy_convs),
        'messages_moved': messages_moved,
    }


# ---------------------------------------------------------------------------
# Apply all
# ---------------------------------------------------------------------------

def apply_migration(groups: dict, limit: int | None = None) -> None:
    need, ok = classify(groups)

    if limit:
        need = need[:limit]

    print(f'\nApplying migration for {len(need)} pairs ...\n')

    results = []
    for i, (pair, convs) in enumerate(need, 1):
        try:
            result = migrate_pair(pair, convs, dry=False)
            results.append(result)
            logger.info(
                '[%d/%d] %s — moved %d messages, merged %d legacy convs',
                i, len(need),
                result.get('canonical_id', '?'),
                result.get('messages_moved', 0),
                result.get('legacy_count', 0),
            )
        except Exception as exc:
            logger.error('[%d/%d] Failed for pair %s: %s', i, len(need), pair, exc)

    total_moved = sum(r.get('messages_moved', 0) for r in results)
    total_merged = sum(r.get('legacy_count', 0) for r in results)

    print(f'\n{"="*60}')
    print('Migration complete.')
    print(f'  Pairs processed   : {len(results)}')
    print(f'  Legacy convs merged: {total_merged}')
    print(f'  Messages migrated : {total_moved}')
    print(f'{"="*60}')
    print()
    print('To verify: re-run with --dry-run and confirm "Pairs needing migration: 0"')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description='Migrate conversations to canonical pair IDs')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true', help='Inspect only, no writes')
    group.add_argument('--apply', action='store_true', help='Apply the migration')
    parser.add_argument('--limit', type=int, default=None, help='Limit pairs processed (smoke test)')
    args = parser.parse_args()

    logger.info('Scanning Firestore conversations ...')
    groups = scan_conversations()

    if args.dry_run:
        dry_run(groups)
    else:
        apply_migration(groups, limit=args.limit)


if __name__ == '__main__':
    main()
