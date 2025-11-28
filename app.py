import os
import io
import csv
from datetime import datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Allow Frontend to talk to Backend
CORS(app) 

# --- RENDER DATABASE CONFIGURATION ---
# This automatically finds the Render Database. If running locally, falls back to sqlite.
database_url = os.environ.get('DATABASE_URL', 'sqlite:///campus_training.db')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'IdeaGenSecret2025')

db = SQLAlchemy(app)

# --- DATABASE MODELS ---
class SystemUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20))

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    student_id = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(100)) 
    department = db.Column(db.String(100))
    status = db.Column(db.String(20), default='active')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(50))
    date = db.Column(db.String(20))
    status = db.Column(db.String(20)) 

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50))
    roll_number = db.Column(db.String(50))
    date = db.Column(db.String(20))
    overall_rating = db.Column(db.Integer)
    session_content = db.Column(db.Integer)
    practical_applicability = db.Column(db.Integer)
    trainer_interaction = db.Column(db.Integer)
    feedback_text = db.Column(db.Text)

# --- INIT FUNCTION ---
def init_db():
    with app.app_context():
        db.create_all()
        if not SystemUser.query.filter_by(username='CeoIdeagen').first():
            db.session.add(SystemUser(username='CeoIdeagen', password='SaisaiCeo@05', role='admin'))
        if not SystemUser.query.filter_by(username='SiriSvrmc').first():
            db.session.add(SystemUser(username='SiriSvrmc', password='Svrmc_Siri_2025@Trainer', role='trainer'))
        db.session.commit()

# --- API ROUTES ---

@app.route('/api/stats/dashboard', methods=['GET'])
def dashboard_stats():
    today = datetime.now().strftime('%Y-%m-%d')
    total_students = Student.query.filter_by(status='active').count()
    present_count = Attendance.query.filter_by(date=today, status='present').count()
    attendance_pct = round((present_count / total_students * 100), 1) if total_students > 0 else 0
    all_feedbacks = Feedback.query.all()
    avg_feedback = 0
    if len(all_feedbacks) > 0:
        total_score = sum([f.overall_rating for f in all_feedbacks])
        avg_feedback = round(total_score / len(all_feedbacks), 1)
    return jsonify({
        "total_students": total_students, "present_today": present_count,
        "attendance_pct": attendance_pct, "avg_feedback": avg_feedback, "feedback_count": len(all_feedbacks)
    })

@app.route('/api/system/login', methods=['POST'])
def system_login():
    data = request.json
    user = SystemUser.query.filter_by(username=data['username'], password=data['password']).first()
    if user: return jsonify({"success": True, "user": {"username": user.username, "role": user.role}})
    return jsonify({"success": False, "message": "Invalid Credentials"}), 401

@app.route('/api/students/upload', methods=['POST'])
def upload_csv():
    if 'file' not in request.files: return jsonify({"success": False, "message": "No file"}), 400
    file = request.files['file']
    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        count = 0
        for row in csv_input:
            if not Student.query.filter_by(roll_number=row['RollNumber']).first():
                student_id = f"STU-{row['RollNumber']}"
                new_s = Student(name=row['Name'], roll_number=row['RollNumber'], student_id=student_id, password=row['Password'], department=row.get('Department', 'General'))
                db.session.add(new_s)
                count += 1
        db.session.commit()
        return jsonify({"success": True, "message": f"Imported {count} students"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/students', methods=['GET', 'POST'])
def handle_students():
    if request.method == 'POST':
        data = request.json
        if not data.get('student_id'): data['student_id'] = f"STU-{data['roll_number']}"
        if Student.query.filter((Student.roll_number==data['roll_number'])).first():
             return jsonify({"success": False, "message": "Student exists"}), 400
        new_s = Student(name=data['name'], roll_number=data['roll_number'], student_id=data['student_id'], password=data['password'], department=data.get('department',''))
        db.session.add(new_s)
        db.session.commit()
        return jsonify({"success": True})
    students = Student.query.order_by(Student.id.desc()).all()
    return jsonify([{"id": s.id, "name": s.name, "roll_number": s.roll_number, "student_id": s.student_id, "password": s.password} for s in students])

@app.route('/api/students/<int:id>', methods=['DELETE'])
def delete_student(id):
    Student.query.filter_by(id=id).delete()
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/student/login', methods=['POST'])
def student_login():
    data = request.json
    login_id = data.get('student_id', '').strip()
    password = data.get('password', '').strip()
    student = Student.query.filter(((Student.student_id == login_id) | (Student.roll_number == login_id)) & (Student.password == password)).first()
    if student: return jsonify({"success": True, "student": {"name": student.name, "roll_number": student.roll_number, "student_id": student.student_id}})
    return jsonify({"success": False, "message": "Invalid Credentials"}), 401

@app.route('/api/attendance', methods=['GET', 'POST'])
def handle_attendance():
    if request.method == 'POST':
        data = request.json
        if isinstance(data, list):
            if len(data) > 0: Attendance.query.filter_by(date=data[0]['date']).delete()
            for item in data: db.session.add(Attendance(roll_number=item['roll_number'], date=item['date'], status=item['status']))
        else: db.session.add(Attendance(**data))
        db.session.commit()
        return jsonify({"success": True})
    date = request.args.get('date')
    roll_number = request.args.get('roll_number')
    if roll_number:
        records = Attendance.query.filter_by(roll_number=roll_number).all()
        total = len(records)
        present = len([r for r in records if r.status == 'present'])
        pct = round((present/total*100), 1) if total > 0 else 0
        return jsonify({"history": [{"id": a.id, "date": a.date, "status": a.status} for a in records], "stats": {"total": total, "present": present, "percentage": pct}})
    if date: records = Attendance.query.filter_by(date=date).all()
    else: records = Attendance.query.all()
    return jsonify([{"id": a.id, "roll_number": a.roll_number, "status": a.status} for a in records])

@app.route('/api/feedback', methods=['GET', 'POST'])
def handle_feedback():
    if request.method == 'POST':
        data = request.json
        existing = Feedback.query.filter_by(student_id=data['student_id'], date=data['date']).first()
        if existing:
            for k, v in data.items(): setattr(existing, k, v)
        else:
            db.session.add(Feedback(student_id=data['student_id'], roll_number=data['roll_number'], date=data['date'], overall_rating=data['overall_rating'], session_content=data['session_content'], practical_applicability=data['practical_applicability'], trainer_interaction=data['trainer_interaction'], feedback_text=data.get('feedback_text', '')))
        db.session.commit()
        return jsonify({"success": True})
    feedbacks = Feedback.query.order_by(Feedback.id.desc()).all()
    return jsonify([{
        "id": f.id, "roll_number": f.roll_number, "overall_rating": f.overall_rating,
        "session_content": f.session_content, "practical_applicability": f.practical_applicability,
        "trainer_interaction": f.trainer_interaction, "feedback_text": f.feedback_text, "date": f.date
    } for f in feedbacks])

# --- AUTO-RUN DATABASE SETUP FOR RENDER ---
with app.app_context():
    db.create_all()
    init_db()

if __name__ == '__main__':
    app.run(debug=True)