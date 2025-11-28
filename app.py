import os
import io
import csv
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson import ObjectId

app = Flask(_name_)
CORS(app)

# --- MONGODB CONNECTION ---
# Paste your connection string here for local testing, 
# BUT for Render, use the Environment Variable 'MONGO_URI'
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb+srv://YOUR_USER:YOUR_PASS@cluster.mongodb.net/?retryWrites=true&w=majority')

try:
    client = MongoClient(MONGO_URI)
    db = client.get_database('internship_portal') # Auto-creates db if missing
    print(">>> Connected to MongoDB")
except Exception as e:
    print(f">>> Failed to connect to MongoDB: {e}")

# --- HELPERS ---
def serialize_doc(doc):
    """Converts MongoDB document to JSON-friendly dict"""
    if not doc: return None
    doc['id'] = str(doc['_id']) # Convert ObjectId to string id
    del doc['_id']
    return doc

def init_db():
    """Create default admin/trainer if they don't exist"""
    users = db.users
    if not users.find_one({'username': 'CeoIdeagen'}):
        users.insert_one({'username': 'CeoIdeagen', 'password': 'SaisaiCeo@05', 'role': 'admin'})
        print(">>> Admin Created")
    if not users.find_one({'username': 'SiriSvrmc'}):
        users.insert_one({'username': 'SiriSvrmc', 'password': 'Svrmc_Siri_2025@Trainer', 'role': 'trainer'})
        print(">>> Trainer Created")

# --- API ROUTES ---

@app.route('/api/stats/dashboard', methods=['GET'])
def dashboard_stats():
    today = datetime.now().strftime('%Y-%m-%d')
    
    total_students = db.students.count_documents({'status': 'active'})
    present_today = db.attendance.count_documents({'date': today, 'status': 'present'})
    
    attendance_pct = round((present_today / total_students * 100), 1) if total_students > 0 else 0
    
    # Calculate Avg Feedback
    pipeline = [{"$group": {"_id": None, "avg_rating": {"$avg": "$overall_rating"}}}]
    feedback_agg = list(db.feedback.aggregate(pipeline))
    avg_feedback = round(feedback_agg[0]['avg_rating'], 1) if feedback_agg else 0
    
    return jsonify({
        "total_students": total_students,
        "present_today": present_today,
        "attendance_pct": attendance_pct,
        "avg_feedback": avg_feedback
    })

@app.route('/api/system/login', methods=['POST'])
def system_login():
    data = request.json
    user = db.users.find_one({'username': data['username'], 'password': data['password']})
    if user:
        return jsonify({"success": True, "user": {"username": user['username'], "role": user['role']}})
    return jsonify({"success": False, "message": "Invalid Credentials"}), 401

@app.route('/api/students/upload', methods=['POST'])
def upload_csv():
    if 'file' not in request.files: return jsonify({"success": False, "message": "No file"}), 400
    file = request.files['file']
    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        count = 0
        students_to_insert = []
        
        for row in csv_input:
            if not db.students.find_one({'roll_number': row['RollNumber']}):
                students_to_insert.append({
                    'name': row['Name'],
                    'roll_number': row['RollNumber'],
                    'student_id': f"STU-{row['RollNumber']}",
                    'password': row['Password'],
                    'department': row.get('Department', 'General'),
                    'status': 'active'
                })
                count += 1
        
        if students_to_insert:
            db.students.insert_many(students_to_insert)
            
        return jsonify({"success": True, "message": f"Imported {count} students"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/students', methods=['GET', 'POST'])
def handle_students():
    if request.method == 'POST':
        data = request.json
        if not data.get('student_id'): data['student_id'] = f"STU-{data['roll_number']}"
        
        if db.students.find_one({'roll_number': data['roll_number']}):
             return jsonify({"success": False, "message": "Student exists"}), 400
        
        data['status'] = 'active'
        result = db.students.insert_one(data)
        return jsonify({"success": True, "id": str(result.inserted_id)})
    
    # GET List
    students = list(db.students.find({}))
    return jsonify([serialize_doc(s) for s in students])

@app.route('/api/students/<string:id>', methods=['DELETE'])
def delete_student(id):
    db.students.delete_one({'_id': ObjectId(id)})
    return jsonify({"success": True})

@app.route('/api/student/login', methods=['POST'])
def student_login():
    data = request.json
    login_id = data.get('student_id', '').strip()
    password = data.get('password', '').strip()
    
    # Check student_id OR roll_number
    student = db.students.find_one({
        "$or": [{'student_id': login_id}, {'roll_number': login_id}],
        'password': password
    })
    
    if student:
        return jsonify({"success": True, "student": serialize_doc(student)})
    return jsonify({"success": False, "message": "Invalid Credentials"}), 401

@app.route('/api/attendance', methods=['GET', 'POST'])
def handle_attendance():
    if request.method == 'POST':
        data = request.json
        if isinstance(data, list): # Bulk Save
            if len(data) > 0:
                # Delete existing for that day to avoid dupes
                db.attendance.delete_many({'date': data[0]['date']})
                db.attendance.insert_many(data)
        else:
            db.attendance.insert_one(data)
        return jsonify({"success": True})

    date = request.args.get('date')
    roll_number = request.args.get('roll_number')
    
    query = {}
    if date: query['date'] = date
    if roll_number: query['roll_number'] = roll_number
    
    records = list(db.attendance.find(query))
    
    # Stats Calculation for Student View
    if roll_number:
        total = len(records)
        present = len([r for r in records if r['status'] == 'present'])
        pct = round((present/total*100), 1) if total > 0 else 0
        return jsonify({
            "history": [serialize_doc(r) for r in records],
            "stats": {"total": total, "present": present, "percentage": pct}
        })
        
    return jsonify([serialize_doc(r) for r in records])

@app.route('/api/feedback', methods=['GET', 'POST'])
def handle_feedback():
    if request.method == 'POST':
        data = request.json
        # Upsert (Update if exists, Insert if new)
        db.feedback.update_one(
            {'student_id': data['student_id'], 'date': data['date']},
            {'$set': data},
            upsert=True
        )
        return jsonify({"success": True})
    
    feedbacks = list(db.feedback.find({}).sort('_id', -1))
    return jsonify([serialize_doc(f) for f in feedbacks])

# Initialize DB on start
init_db()

if _name_ == '_main_':
    app.run(debug=True, port=5000)
