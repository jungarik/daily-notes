def save(note_id):
    db.replace_chunks(note_id, [])
