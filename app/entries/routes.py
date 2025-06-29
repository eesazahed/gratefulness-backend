from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from .. import db
from ..models import GratitudeEntry, User
from ..helpers.utils import require_auth, format_timestamp, convert_utc_to_local
from ..config import Config
import pytz
from cryptography.fernet import Fernet

entries_bp = Blueprint('entries', __name__)


def get_cipher():
    return Fernet(Config.ENCRYPTION_KEY)


def encrypt(text):
    return get_cipher().encrypt(text.encode()).decode()


def decrypt(token):
    return get_cipher().decrypt(token.encode()).decode()


# GETS ENTRIES WITH PAGINATION
@entries_bp.route('', methods=['GET'])
@require_auth
def get_entries():
    limit = int(request.args.get('limit', 10))
    offset = int(request.args.get('offset', 0))

    total_entries = GratitudeEntry.query.filter_by(
        user_id=request.user_id).count()
    query = GratitudeEntry.query.filter_by(
        user_id=request.user_id).order_by(GratitudeEntry.timestamp.desc())
    entries = query.offset(offset).limit(limit).all()
    next_offset = offset + limit if offset + limit < total_entries else None

    return jsonify({
        'message': 'Entries retrieved successfully',
        'data': [{
            'id': e.id,
            'entry1': decrypt(e.entry1),
            'entry2': decrypt(e.entry2),
            'entry3': decrypt(e.entry3),
            'user_prompt': decrypt(e.user_prompt),
            'user_prompt_response': decrypt(e.user_prompt_response),
            'timestamp': format_timestamp(e.timestamp)
        } for e in entries],
        'nextOffset': next_offset
    })


# SUBMIT ENTRY
@entries_bp.route('', methods=['POST'])
@require_auth
def submit_entry():
    user = User.query.filter_by(user_id=request.user_id).first()
    if not user or not user.account_active:
        return jsonify({'message': 'Please login to your account', 'errorCode': 'submission'}), 403

    data = request.get_json()

    def is_invalid_field(value, min_length, max_length):
        if not value or not value.strip():
            return True
        length = len(value.strip())
        return length < min_length or length > max_length

    validation_rules = {
        'entry1': (100, 'entry1'),
        'entry2': (100, 'entry2'),
        'entry3': (100, 'entry3'),
        'user_prompt': (200, 'submission'),
        'user_prompt_response': (200, 'promptResponse')
    }

    min_length = 5

    for field, (max_len, error_code) in validation_rules.items():
        value = data.get(field, '')
        if is_invalid_field(value, min_length, max_len):
            return jsonify({'message': f'Must be between {min_length} to {max_len} characters', 'errorCode': error_code}), 403

    try:
        now_local = convert_utc_to_local(
            datetime.now(timezone.utc), user.user_timezone)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400

    start_of_today_local = now_local.replace(
        hour=0, minute=0, second=0, microsecond=0)
    start_of_today_utc = start_of_today_local.astimezone(pytz.utc)

    existing_entry = GratitudeEntry.query.filter(
        GratitudeEntry.user_id == request.user_id,
        GratitudeEntry.timestamp >= start_of_today_utc
    ).first()

    if existing_entry:
        return jsonify({'message': 'Already submitted today', 'errorCode': 'submission'}), 400

    entry = GratitudeEntry(
        user_id=request.user_id,
        entry1=encrypt(data['entry1']),
        entry2=encrypt(data['entry2']),
        entry3=encrypt(data['entry3']),
        user_prompt=encrypt(data['user_prompt']),
        user_prompt_response=encrypt(data['user_prompt_response'])
    )
    db.session.add(entry)
    db.session.commit()

    return jsonify({'message': 'Entry saved', 'data': {
        'id': entry.id,
        'timestamp': format_timestamp(entry.timestamp)
    }}), 201


# GETS ALL THE DAYS THAT A USER HAS CREATED AN ENTRY
@entries_bp.route('/days', methods=['GET'])
@require_auth
def get_entry_days():
    entries = db.session.query(
        GratitudeEntry.id,
        GratitudeEntry.timestamp
    ).filter_by(
        user_id=request.user_id
    ).distinct().all()

    return jsonify({
        'message': 'Entry days retrieved',
        'data': [
            {
                'id': entry.id,
                'timestamp': format_timestamp(entry.timestamp)
            } for entry in entries
        ]
    })


# COUNT THE DAYS A USER HAS POSTED THIS MONTH
@entries_bp.route('/user_month_days', methods=['GET'])
@require_auth
def user_month_days():
    user = db.session.query(User).filter_by(user_id=request.user_id).first()
    if not user or not user.user_timezone:
        return jsonify({'message': 'User or timezone not found'}), 404

    try:
        now_user_tz = convert_utc_to_local(
            datetime.now(timezone.utc), user.user_timezone)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400

    start_of_month_user = now_user_tz.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_of_month_user.month == 12:
        next_month = start_of_month_user.replace(
            year=start_of_month_user.year + 1, month=1)
    else:
        next_month = start_of_month_user.replace(
            month=start_of_month_user.month + 1)

    start_utc = start_of_month_user.astimezone(pytz.utc)
    end_utc = next_month.astimezone(pytz.utc)

    timestamps_utc = db.session.query(GratitudeEntry.timestamp).filter(
        GratitudeEntry.user_id == request.user_id,
        GratitudeEntry.timestamp >= start_utc,
        GratitudeEntry.timestamp < end_utc
    ).all()

    days = set()
    for (ts_utc,) in timestamps_utc:
        try:
            local_date = convert_utc_to_local(
                ts_utc, user.user_timezone).date()
        except ValueError as e:
            return jsonify({'message': str(e)}), 400
        days.add(local_date)

    return jsonify({'message': 'Count of days with entries this month', 'days_count': len(days)})


# GET A SPECIFIC ENTRY BY ID
@entries_bp.route('/<int:id>', methods=['GET'])
@require_auth
def get_entry(id):
    entry = GratitudeEntry.query.get_or_404(id)
    if entry.user_id != request.user_id:
        return jsonify({'message': 'Unauthorized access'}), 403
    return jsonify({'message': 'Entry retrieved', 'data': {
        'id': entry.id,
        'entry1': decrypt(entry.entry1),
        'entry2': decrypt(entry.entry2),
        'entry3': decrypt(entry.entry3),
        'user_prompt': decrypt(entry.user_prompt),
        'user_prompt_response': decrypt(entry.user_prompt_response),
        'timestamp': format_timestamp(entry.timestamp)
    }})


# DELETE A SPECIFIC ENTRY
@entries_bp.route('/<int:id>', methods=['DELETE'])
@require_auth
def delete_entry(id):
    entry = GratitudeEntry.query.get_or_404(id)

    user = User.query.filter_by(user_id=request.user_id).first()
    if not user or not user.user_timezone:
        return jsonify({'message': 'User or timezone not found'}), 404

    if entry.user_id != request.user_id:
        return jsonify({'message': 'Unauthorized'}), 403

    try:
        entry_local_date = convert_utc_to_local(
            entry.timestamp, user.user_timezone).date()
        now_local_date = convert_utc_to_local(
            datetime.now(timezone.utc), user.user_timezone).date()
    except ValueError as e:
        return jsonify({'message': str(e)}), 400

    if entry_local_date != now_local_date:
        return jsonify({'message': 'Can only delete today\'s entry'}), 400

    db.session.delete(entry)
    db.session.commit()
    return jsonify({'message': 'Entry deleted'})
