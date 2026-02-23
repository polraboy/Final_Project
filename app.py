from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_from_directory,
    send_file,
    make_response,
    g,
    jsonify
)
import re
import time
from markupsafe import Markup
import mysql.connector
import base64
import urllib.parse
import os
import urllib
from contextlib import contextmanager
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from io import BytesIO
from functools import wraps
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from math import ceil
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
from reportlab.lib.units import inch, cm
from flask_apscheduler import APScheduler
from reportlab.lib.utils import ImageReader
import logging
from reportlab.lib.utils import simpleSplit
from datetime import timedelta
import requests
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.secret_key = "your_secret_key"
app.static_folder = "static"

app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
# ตั้งค่าการบันทึกล็อก
logging.basicConfig(level=logging.INFO)

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ลงทะเบียนฟอนต์ไทย
pdfmetrics.registerFont(TTFont("THSarabunNew", "THSarabunNew.ttf"))


scheduler = APScheduler()

def init_scheduler(app):
    scheduler.init_app(app)
    scheduler.start()




@app.route("/home")
def index():
    return "Welcome to the Flask Google Form Integration App"



@contextmanager
def get_db_cursor(max_retries=5, retry_delay=1):
    db = None
    cursor = None
    
    try:
        # Try to connect to the database
        db = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="Finalproject",
            connection_timeout=60,
            use_pure=True,
            autocommit=False
        )
        cursor = db.cursor(buffered=True)
        yield db, cursor
        if db.is_connected():
            db.commit()
    except Exception as e:
        # Handle the exception
        if db and db.is_connected():
            db.rollback()
        raise e
    finally:
        # Always clean up resources
        if cursor:
            cursor.close()
        if db and db.is_connected():
            db.close()
            
def get_db_connection():
    conn = mysql.connector.connect(
        host="localhost", user="root", password="", database="Finalproject"
    )
    cursor = conn.cursor(dictionary=True)
    return conn, cursor
@app.route("/test_db")
def test_db():
    try:
        with get_db_cursor() as (db, cursor):
            cursor.execute("SELECT 1")
            return "Database connection successful!"
    except Exception as e:
        return f"Database connection failed: {str(e)}"
@app.before_request
def before_request():
    g.user = None
    if "user_type" in session:
        if session["user_type"] == "teacher":
            g.user = {
                "id": session.get("teacher_id"),
                "name": session.get("teacher_name"),
                "email": session.get("teacher_email"),
                "phone": session.get("teacher_phone"),
                "type": "teacher",
            }
        elif session["user_type"] == "admin":
            g.user = {
                "id": session.get("admin_id"),
                "name": session.get("admin_name"),
                "email": session.get("admin_email"),
                "type": "admin",
            }


# แก้ไข route home ใน app.py
@app.route("/")
def home():
    page = request.args.get("page", 1, type=int)
    per_page = 3

    with get_db_cursor() as (db, cursor):
        cursor.execute("SELECT COUNT(*) FROM constants")
        total_constants = cursor.fetchone()[0]

        total_pages = ceil(total_constants / per_page)
        page = max(1, min(page, total_pages))

        offset = (page - 1) * per_page
        query = "SELECT constants_headname, constants_detail, constants_image FROM constants ORDER BY constants_datetime DESC LIMIT %s OFFSET %s"
        cursor.execute(query, (per_page, offset))
        constants = cursor.fetchall()

        constants = [
            (c[0], c[1], base64.b64encode(c[2]).decode("utf-8")) for c in constants
        ]

        # แก้ไข: ใช้ approval table แทน project table สำหรับ project_statusStart
        active_projects_query = """
            SELECT p.project_id, p.project_name, p.project_dotime, p.project_endtime, 
                   p.project_address, a.project_statusStart, p.project_target, t.teacher_name,
                   (SELECT COUNT(*) FROM status_register sr WHERE sr.project_id = p.project_id AND sr.status_register = 1) as participant_count
            FROM project p
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN approval a ON p.project_id = a.project_id
            WHERE a.project_status = 2 AND (a.project_statusStart = 1 OR a.project_statusStart = 2)
            ORDER BY p.project_dotime ASC
            LIMIT 10
        """
        cursor.execute(active_projects_query)
        active_projects_raw = cursor.fetchall()
        
        active_projects = []
        for p in active_projects_raw:
            active_projects.append({
                'project_id': p[0],
                'project_name': p[1],
                'project_dotime': p[2],
                'project_endtime': p[3],
                'project_address': p[4],
                'project_statusStart': p[5],
                'project_target': int(p[6]) if p[6] else 0,
                'teacher_name': p[7],
                'participant_count': int(p[8]) if p[8] else 0
            })

    return render_template(
        "home.html", 
        constants=constants, 
        page=page, 
        total_pages=total_pages,
        active_projects=active_projects
    )

# แทนที่ส่วนการล็อกอินนักศึกษาใน app.py

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_type = request.form.get("login_type", "staff")
        
        if login_type == "staff":
            # ส่วนอาจารย์/แอดมิน เหมือนเดิม
            username = request.form["username"]
            password = request.form["password"]
            
            with get_db_cursor() as (db, cursor):
                query_teacher = "SELECT * FROM teacher WHERE teacher_username = %s"
                cursor.execute(query_teacher, (username,))
                teacher = cursor.fetchone()
                
                if teacher:
                    if check_password_hash(teacher[3], password) or teacher[3] == password:
                        session.clear()
                        session["teacher_id"] = teacher[0]
                        session["teacher_name"] = teacher[1]
                        session["teacher_email"] = teacher[5]
                        session["teacher_phone"] = teacher[4]
                        session["user_type"] = "teacher"
                        return redirect(url_for("teacher_home"))
                else:
                    query_admin = "SELECT * FROM admin WHERE admin_username = %s"
                    cursor.execute(query_admin, (username,))
                    admin = cursor.fetchone()
                    
                    if admin:
                        if check_password_hash(admin[3], password) or admin[3] == password:
                            session.clear()
                            session["admin_id"] = admin[0]
                            session["admin_name"] = admin[1]
                            session["admin_email"] = admin[4]
                            session["user_type"] = "admin"
                            return redirect(url_for("admin_home"))
                
                flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "danger")
        
        elif login_type == "student":
            # แก้ไข: เอา filter การอนุมัติออก - ให้เข้าสู่ระบบได้ทันทีหลังสมัคร
            student_id = request.form.get("student_id")  # รหัสบัตรนักศึกษา
            password = request.form.get("password")      # รหัสผ่าน
            
            if not student_id or not password:
                flash("กรุณากรอกข้อมูลให้ครบถ้วน", "danger")
                return render_template("login.html")
            
            with get_db_cursor() as (db, cursor):
                # แก้ไข: ตรวจสอบจากตาราง join โดยตรง ไม่ต้องผ่าน status_register
                query = """
                SELECT j.join_id, j.join_name, j.join_email, j.join_telephone, j.branch_id, 
                       b.branch_name, j.join_password
                FROM `join` j
                LEFT JOIN branch b ON j.branch_id = b.branch_id
                WHERE j.join_id = %s
                LIMIT 1
                """
                cursor.execute(query, (student_id,))
                student = cursor.fetchone()
                
                if not student:
                    flash("ไม่พบข้อมูลนักศึกษาในระบบ", "danger")
                    return render_template("login.html")
                
                # ตรวจสอบรหัสผ่าน
                stored_password = student[6]  # join_password
                password_valid = False
                
                if stored_password:
                    try:
                        # ลองตรวจสอบแบบ hash ก่อน
                        if stored_password.startswith(('pbkdf2:', 'scrypt:', 'argon2:', '$')):
                            password_valid = check_password_hash(stored_password, password)
                        else:
                            # เป็นรหัสผ่านแบบ plain text
                            password_valid = (stored_password == password)
                    except Exception as e:
                        # ถ้าเกิดข้อผิดพลาดในการตรวจสอบ hash ให้ลองเปรียบเทียบตรงๆ
                        password_valid = (stored_password == password)
                else:
                    # ถ้าไม่มีรหัสผ่าน ให้ใช้เบอร์โทรแทน (backward compatibility)
                    password_valid = (student[3] == password)  # join_telephone
                
                if not password_valid:
                    flash("รหัสนักศึกษาหรือรหัสผ่านไม่ถูกต้อง", "danger")
                    return render_template("login.html")
                
                session.clear()
                session["student_id"] = student[0]  # join_id
                session["student_name"] = student[1]
                session["student_email"] = student[2]
                session["student_phone"] = student[3]
                session["student_branch_id"] = student[4]
                session["student_branch"] = student[5] if student[5] else "ไม่ระบุสาขา"
                session["user_type"] = "student"
                
                flash(f"ยินดีต้อนรับ {student[1]}", "success")
                return redirect(url_for("student_dashboard"))

    return render_template("login.html")
# แก้ไข route student_dashboard ใน app.py
@app.route("/student_dashboard")
def student_dashboard():
    if "student_id" not in session or session.get("user_type") != "student":
        flash("กรุณาเข้าสู่ระบบก่อน", "danger")
        return redirect(url_for("login"))
    
    student_id = session.get("student_id")
    
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลโครงการที่ลงทะเบียน พร้อม register_id
        query = """
        SELECT sr.register_id, sr.status_register, p.project_id, p.project_name, p.project_dotime, 
               p.project_endtime, a.project_statusStart, p.project_address, t.teacher_name,
               (SELECT COUNT(*) FROM project_evaluation pe WHERE pe.join_id = sr.join_id AND pe.project_id = sr.project_id) as has_evaluated
        FROM status_register sr
        JOIN project p ON sr.project_id = p.project_id
        JOIN teacher t ON p.teacher_id = t.teacher_id
        JOIN approval a ON p.project_id = a.project_id
        WHERE sr.join_id = %s
        ORDER BY sr.register_time DESC
        """
        cursor.execute(query, (student_id,))
        registered_projects = cursor.fetchall()
        
        projects = []
        for p in registered_projects:
            projects.append({
                "register_id": p[0],  # เพิ่ม register_id
                "status_register": p[1],
                "project_id": p[2],
                "project_name": p[3],
                "project_dotime": p[4],
                "project_endtime": p[5],
                "project_statusStart": p[6],
                "project_address": p[7],
                "teacher_name": p[8],
                "has_evaluated": p[9] > 0
            })
        
        # ดึงข้อมูลโครงการที่เปิดรับสมัคร
        query = """
        SELECT p.project_id, p.project_name, p.project_dotime, p.project_endtime, 
               p.project_target, p.project_address, t.teacher_name,
               (SELECT COUNT(*) FROM status_register WHERE project_id = p.project_id) as current_count,
               (SELECT COUNT(*) FROM status_register WHERE project_id = p.project_id AND join_id = %s) as already_joined
        FROM project p
        JOIN teacher t ON p.teacher_id = t.teacher_id
        JOIN approval a ON p.project_id = a.project_id
        WHERE a.project_status = 2 AND a.project_statusStart = 1
        ORDER BY p.project_dotime ASC
        """
        cursor.execute(query, (student_id,))
        available_projects = cursor.fetchall()
        
        active_projects = []
        for p in available_projects:
            active_projects.append({
                "project_id": p[0],
                "project_name": p[1],
                "project_dotime": p[2],
                "project_endtime": p[3],
                "project_target": int(p[4]) if p[4] is not None else 0,
                "project_address": p[5],
                "teacher_name": p[6],
                "current_count": int(p[7]) if p[7] is not None else 0,
                "already_joined": p[8] > 0
            })
    
    return render_template(
        "student_dashboard.html", 
        projects=projects,
        active_projects=active_projects
    )
def generate_confirmation_token(join_id, email):
    # สร้างโทเค็นอย่างง่ายจาก join_id และ email
    import hashlib
    token = hashlib.md5(f"{join_id}:{email}:{app.secret_key}".encode()).hexdigest()
    print(f"สร้างโทเค็นสำหรับ join_id: {join_id}, email: {email}, token: {token}")
    return token

# เพิ่มเส้นทางใหม่สำหรับการยืนยันการเข้าร่วม
@app.route("/confirm_participation/<int:join_id>/<token>", methods=["GET"])
def confirm_participation(join_id, token):
    # ตรวจสอบความถูกต้องของโทเค็น
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลผู้สมัคร
        cursor.execute(
            """SELECT j.join_name, j.join_email, p.project_id, p.project_name 
               FROM `join` j 
               JOIN project p ON j.project_id = p.project_id 
               WHERE j.join_id = %s""", 
            (join_id,)
        )
        participant_info = cursor.fetchone()
        
        if not participant_info:
            flash("ไม่พบข้อมูลการลงทะเบียน", "error")
            return redirect(url_for("home"))
        
        print(f"ข้อมูลผู้ยืนยัน: {participant_info}")
        
        # สร้างโทเค็นเพื่อเปรียบเทียบ
        expected_token = generate_confirmation_token(join_id, participant_info[1])  # join_id และ email
        
        print(f"โทเค็นที่คาดหวัง: {expected_token}")
        print(f"โทเค็นที่ได้รับ: {token}")
        
        if token != expected_token:
            flash("ลิงก์ยืนยันไม่ถูกต้อง", "error")
            return redirect(url_for("home"))
        
        # อัปเดตสถานะเป็นอนุมัติแล้ว
        cursor.execute(
            "UPDATE `join` SET join_status = 1 WHERE join_id = %s",
            (join_id,)
        )
        db.commit()
        
        flash("การลงทะเบียนเข้าร่วมโครงการได้รับการยืนยันเรียบร้อยแล้ว", "success")
        return redirect(url_for("project_detail", project_id=participant_info[2]))

@app.route("/dashboard")
def dashboard():
    if "admin_id" in session:
        return f"Hello, Admin {session['admin_name']}! This is your dashboard."
    elif "teacher_id" in session:
        return f"Hello, Teacher {session['teacher_name']}! This is your dashboard."
    else:
        return redirect(url_for("login"))


@app.route("/logout")
def logout():
    user_type = session.get("user_type", "")
    
    # ล้างข้อมูล session ทั้งหมด
    session.clear()
    
    # แสดงข้อความแจ้งเตือนตามประเภทผู้ใช้
    if user_type == "teacher":
        flash("อาจารย์ออกจากระบบเรียบร้อยแล้ว", "success")
    elif user_type == "admin":
        flash("ผู้ดูแลระบบออกจากระบบเรียบร้อยแล้ว", "success")
    elif user_type == "student":
        flash("นักศึกษาออกจากระบบเรียบร้อยแล้ว", "success")
    else:
        flash("ออกจากระบบเรียบร้อยแล้ว", "success")
        
    return redirect(url_for("home"))



def login_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapped_function(*args, **kwargs):
            if not g.user or g.user["type"] not in allowed_roles:
                flash("คุณไม่มีสิทธิ์เข้าถึงหน้านี้", "error")
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapped_function
    return decorator

@app.route("/admin_home", methods=["GET", "POST"])
@login_required("admin")
def admin_home():
    if not g.user or g.user["type"] != "admin":
        return redirect(url_for("login"))

    page = request.args.get('page', 1, type=int)
    per_page = 3  # กลับไปแสดง 3 รายการต่อหน้าเหมือนเดิม
    search_query = request.args.get('search', '')

    if request.method == "POST":
        if "constant_headname" in request.form:
            constant_headname = request.form["constant_headname"]
            constant_detail = request.form["constant_detail"]
            constant_image = request.files["constant_image"]

            try:
                # ปรับขนาดรูปภาพและแปลงเป็น RGB
                img = Image.open(constant_image)
                img = img.convert("RGB")  # แปลง RGBA เป็น RGB
                img.thumbnail((800, 600))  # ปรับขนาดให้พอดีกับ 800x600 โดยรักษาสัดส่วน

                # แปลงรูปภาพเป็น binary
                img_io = BytesIO()
                img.save(img_io, "JPEG", quality=85)
                image_binary = img_io.getvalue()

                # บันทึกลงฐานข้อมูล (พร้อมกับ datetime ปัจจุบัน)
                with get_db_cursor() as (db, cursor):
                    query = "INSERT INTO constants (constants_headname, constants_detail, constants_image, constants_datetime) VALUES (%s, %s, %s, NOW())"
                    cursor.execute(
                        query, (constant_headname, constant_detail, image_binary)
                    )
                    db.commit()

                flash("เพิ่มข้อมูลข่าวสารเรียบร้อยแล้ว!", "success")
            except Exception as err:
                flash(f"เกิดข้อผิดพลาด: {err}", "danger")

            return redirect(url_for("admin_home"))

        elif "delete_constant_headname" in request.form:
            constant_headname = request.form["delete_constant_headname"]
            try:
                with get_db_cursor() as (db, cursor):
                    query = "DELETE FROM constants WHERE constants_headname = %s"
                    cursor.execute(query, (constant_headname,))
                    db.commit()

                flash("ลบข้อมูลข่าวสารเรียบร้อยแล้ว!", "success")
            except mysql.connector.Error as err:
                flash(f"เกิดข้อผิดพลาด: {err}", "danger")

            return redirect(url_for("admin_home"))

    # ดึงข้อมูล constants สำหรับการแสดงผล - เพิ่ม constants_datetime
    try:
        with get_db_cursor() as (db, cursor):
            count_query = "SELECT COUNT(*) FROM constants"
            if search_query:
                count_query += " WHERE constants_headname LIKE %s"
                cursor.execute(count_query, (f"%{search_query}%",))
            else:
                cursor.execute(count_query)
            total_constants = cursor.fetchone()[0]

            total_pages = ceil(total_constants / per_page)
            
            # ป้องกันการเข้าถึงหน้าที่ไม่มีอยู่
            if page > total_pages and total_pages > 0:
                page = total_pages
                
            offset = (page - 1) * per_page

            # แก้ไข: เพิ่ม constants_datetime ในการ SELECT
            query = "SELECT constants_headname, constants_detail, constants_image, constants_datetime FROM constants"
            if search_query:
                query += " WHERE constants_headname LIKE %s"
                query += " ORDER BY constants_datetime DESC LIMIT %s OFFSET %s"
                cursor.execute(query, (f"%{search_query}%", per_page, offset))
            else:
                query += " ORDER BY constants_datetime DESC LIMIT %s OFFSET %s"
                cursor.execute(query, (per_page, offset))
                
            constants = cursor.fetchall()

        # แปลงรูปภาพเป็น base64 และจัดรูปแบบวันที่
        formatted_constants = []
        for c in constants:
            # แปลงรูปภาพ
            image_base64 = base64.b64encode(c[2]).decode("utf-8")
            
            # จัดรูปแบบวันที่
            if c[3]:  # ถ้ามี constants_datetime
                if isinstance(c[3], datetime):
                    formatted_date = c[3].strftime('%d/%m/%Y %H:%M')
                else:
                    formatted_date = str(c[3])
            else:
                formatted_date = 'ไม่ระบุวันที่'
            
            formatted_constants.append((c[0], c[1], image_base64, formatted_date))
            
    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {err}", "danger")
        formatted_constants = []
        total_pages = 1

    return render_template(
        "admin_home.html", 
        constants=formatted_constants, 
        page=page, 
        total_pages=total_pages, 
        search_query=search_query
    )
@app.route("/approve_project", methods=["GET", "POST"])
@login_required("admin")
def approve_project():
    if not g.user or g.user["type"] != "admin":
        return redirect(url_for("login"))

    if request.method == "POST":
        project_id = request.form.get("project_id")
        action = request.form.get("action")
        admin_id = g.user["id"]
        
        with get_db_cursor() as (db, cursor):
            if action == "approve":
                cursor.execute("""
                    UPDATE approval 
                    SET project_status = 2, project_approve_date = NOW(), admin_id = %s
                    WHERE project_id = %s
                """, (admin_id, project_id))
                flash('โครงการได้รับการอนุมัติแล้ว', 'success')
            elif action == "reject":
                reason = request.form.get("reason", "")
                cursor.execute("""
                    UPDATE approval 
                    SET project_status = 3, project_reject_date = NOW(), 
                        project_reject = %s, admin_id = %s
                    WHERE project_id = %s
                """, (reason, admin_id, project_id))
                flash('โครงการได้รับการตีกลับแล้ว', 'success')
            
            db.commit()
        return redirect(url_for("approve_project"))

    page = request.args.get("page", 1, type=int)
    per_page = 6
    search_query = request.args.get("search", "")
    approval_filter = request.args.get("approval", "all")

    with get_db_cursor() as (db, cursor):
        base_query = """
            SELECT p.project_id, p.project_name, a.project_status, 
                   CASE WHEN a.project_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_pdf,
                   a.project_submit_date, a.project_approve_date, a.project_reject_date,
                   ad.admin_name as approver_name
            FROM project p
            JOIN approval a ON p.project_id = a.project_id
            LEFT JOIN admin ad ON a.admin_id = ad.admin_id
        """
        
        count_query = """
            SELECT COUNT(*) 
            FROM project p
            JOIN approval a ON p.project_id = a.project_id
        """
        
        where_clauses = []
        query_params = []

        if approval_filter == "approved":
            where_clauses.append("a.project_status = 2")
        elif approval_filter == "pending":
            where_clauses.append("a.project_status = 1")
        elif approval_filter == "unapproved":
            where_clauses.append("a.project_status = 0")

        if search_query:
            where_clauses.append("p.project_name LIKE %s")
            query_params.append(f"%{search_query}%")

        if where_clauses:
            where_clause = " WHERE " + " AND ".join(where_clauses)
            base_query += where_clause
            count_query += where_clause

        # Count total projects
        cursor.execute(count_query, query_params)
        total_projects = cursor.fetchone()[0]

        # Calculate total pages
        total_pages = ceil(total_projects / per_page)

        # Get projects for current page
        base_query += """ ORDER BY 
            CASE 
                WHEN a.project_submit_date IS NOT NULL THEN a.project_submit_date
                WHEN a.project_approve_date IS NOT NULL THEN a.project_approve_date  
                WHEN a.project_reject_date IS NOT NULL THEN a.project_reject_date
                ELSE p.project_id
            END DESC,
            p.project_id DESC
            LIMIT %s OFFSET %s"""
        query_params.extend([per_page, (page - 1) * per_page])

        cursor.execute(base_query, query_params)
        projects = cursor.fetchall()
        
        # ดึงข้อมูลเหตุผลการตีกลับ
        project_prev_reject = {}
        pending_project_ids = [p[0] for p in projects if p[2] == 1]
        
        if pending_project_ids:
            placeholders = ', '.join(['%s'] * len(pending_project_ids))
            cursor.execute(
                f"""
                SELECT a.project_id, a.project_reject 
                FROM approval a
                WHERE a.project_id IN ({placeholders})
                AND a.project_reject IS NOT NULL AND a.project_reject != ''
                """,
                pending_project_ids
            )
            for proj_id, reject_reason in cursor.fetchall():
                project_prev_reject[proj_id] = reject_reason

    return render_template(
        "approve_project.html",
        projects=projects,
        approval_filter=approval_filter,
        page=page,
        total_pages=total_pages,
        search_query=search_query,
        per_page=per_page,
        project_prev_reject=project_prev_reject
    )

def get_projects():
    with get_db_cursor() as (db, cursor):
        query = "SELECT project_id, project_name, project_status, project_statusStart FROM project"
        cursor.execute(query)
        projects = cursor.fetchall()
    return projects


def get_status(status_code):
    if status_code == 0:
        return "ยังไม่ยื่นอนุมัติ"
    elif status_code == 1:
        return "รออนุมัติ"
    elif status_code == 2:
        return "อนุมัติแล้ว"
    else:
        return "ไม่มีข้อมูล"
    # เพิ่มฟังก์ชันสำหรับแสดงประวัติของนักศึกษา (ใช้หน้าเดียวกับ student_history ที่มีอยู่)
@app.route("/student_history/<string:student_id>")
def student_history(student_id):
    if session.get("user_type") == "student":
        if student_id != session.get("student_id"):
            flash("คุณไม่มีสิทธิ์ดูข้อมูลของนักศึกษาคนอื่น", "danger")
            return redirect(url_for("student_dashboard"))
    
    search_done = True
    projects = []
    student_info = None
    
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลนักศึกษา
        cursor.execute("""
            SELECT join_name, join_email, join_telephone, branch_id, 
                   (SELECT branch_name FROM branch WHERE branch_id = j.branch_id) as branch_name
            FROM `join` j
            WHERE join_id = %s
        """, (student_id,))
        student_info = cursor.fetchone()
        
        # แก้ไข: ใช้ approval table สำหรับ project_statusStart
        cursor.execute("""
            SELECT sr.status_register, sr.register_time, 
                   p.project_id, p.project_name, p.project_dotime, p.project_endtime,
                   a.project_statusStart
            FROM status_register sr
            JOIN project p ON sr.project_id = p.project_id
            JOIN approval a ON p.project_id = a.project_id
            WHERE sr.join_id = %s
            ORDER BY sr.register_time DESC
        """, (student_id,))
        projects = cursor.fetchall()
    
    return render_template(
        "student_history.html",
        student_id=student_id,
        student_info=student_info,
        projects=projects,
        search_done=search_done
    )

    # เพิ่มฟังก์ชันเพื่อปรับปรุง project_evaluation ให้รองรับการประเมินจากนักศึกษาที่ล็อกอิน

@app.route("/project/<int:project_id>/join", methods=["GET", "POST"])
def join_project(project_id):
    try:
        with get_db_cursor() as (db, cursor):
            cursor.execute(
                "SELECT project_name, project_target FROM project WHERE project_id = %s",
                (project_id,),
            )
            project = cursor.fetchone()

            if not project:
                flash("โครงการไม่พบ", "error")
                return redirect(url_for("active_projects"))

            cursor.execute(
                "SELECT COUNT(*) FROM status_register WHERE project_id = %s",
                (project_id,),
            )
            current_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT branch_id, branch_name FROM branch ORDER BY branch_name")
            branches = cursor.fetchall()

            if request.method == "POST":
                registration_type = request.form.get("registrationType")
                student_id = request.form.get("student_id")
                
                # ตรวจสอบการลงทะเบียนซ้ำ
                cursor.execute(
                    "SELECT register_id FROM status_register WHERE project_id = %s AND join_id = %s",
                    (project_id, student_id)
                )
                existing_register = cursor.fetchone()
                
                if existing_register:
                    flash(f"รหัสบัตรนักศึกษา {student_id} ได้ลงทะเบียนเข้าร่วมโครงการนี้แล้ว", "error")
                    return render_template(
                        "join_project.html",
                        project=project,
                        project_id=project_id,
                        current_count=current_count,
                        branches=branches
                    )
                
                if registration_type == "returning":
                    # ดึงข้อมูลจากตาราง join
                    cursor.execute(
                        "SELECT join_name, join_email, join_telephone, branch_id FROM `join` WHERE join_id = %s", 
                        (student_id,)
                    )
                    student = cursor.fetchone()
                    
                    if not student:
                        flash("ไม่พบข้อมูลนักศึกษา กรุณาลงทะเบียนแบบนักศึกษาใหม่", "error")
                        return render_template(
                            "join_project.html",
                            project=project,
                            project_id=project_id,
                            current_count=current_count,
                            branches=branches
                        )
                    
                    # บันทึกลง status_register (register_id จะเป็น AUTO_INCREMENT)
                    cursor.execute(
                        "INSERT INTO status_register (join_id, project_id, status_register, register_time) VALUES (%s, %s, 0, NOW())",
                        (student_id, project_id)
                    )
                    
                else:
                    # นักศึกษาใหม่
                    join_name = request.form["join_name"]
                    join_telephone = request.form["join_telephone"]
                    join_email = request.form["join_email"]
                    branch_id = request.form.get("branch_id")
                    join_password = request.form.get("join_password", "")

                    # เข้ารหัสรหัสผ่าน
                    hashed_password = ""
                    if join_password:
                        hashed_password = generate_password_hash(join_password)

                    # บันทึกข้อมูลนักศึกษาใหม่
                    cursor.execute(
                        """
                        INSERT INTO `join` (join_id, join_name, join_telephone, join_email, branch_id, join_password)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE 
                        join_name = VALUES(join_name),
                        join_telephone = VALUES(join_telephone),
                        join_email = VALUES(join_email),
                        branch_id = VALUES(branch_id),
                        join_password = VALUES(join_password)
                        """,
                        (student_id, join_name, join_telephone, join_email, branch_id, hashed_password)
                    )
                    
                    # บันทึกลง status_register
                    cursor.execute(
                        "INSERT INTO status_register (join_id, project_id, status_register, register_time) VALUES (%s, %s, 0, NOW())",
                        (student_id, project_id)
                    )
                
                db.commit()
                flash("คุณได้ลงทะเบียนเข้าร่วมโครงการเรียบร้อยแล้ว", "success")
                return redirect(url_for("project_detail", project_id=project_id))

            return render_template(
                "join_project.html",
                project=project,
                project_id=project_id,
                current_count=current_count,
                branches=branches
            )
            
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        return redirect(url_for("project_detail", project_id=project_id))


    
@app.route('/check_student_id_column')
def check_student_id_column():
    with get_db_cursor() as (db, cursor):
        try:
            cursor.execute("SHOW COLUMNS FROM `join` LIKE 'join_student_id'")
            has_column = cursor.fetchone() is not None
        except:
            has_column = False
        
        return jsonify({'has_column': has_column})

def is_super_admin(username):
    """ตรวจสอบว่าเป็น Super Admin (admin00) หรือไม่"""
    return username == 'admin00'

def can_edit_user(current_user_id, current_username, target_user_id, target_username, current_user_role, target_user_role):
    """ตรวจสอบว่าสามารถแก้ไขข้อมูลผู้ใช้ได้หรือไม่"""
    
    # ทุกคนแก้ไขตัวเองได้
    if current_user_id == target_user_id:
        return True
    
    # admin00 แก้ไขได้ทุกคน
    if is_super_admin(current_username):
        return True
    
    # เจ้าหน้าที่ (admin อื่นๆ) 
    if current_user_role == 'admin':
        # ไม่สามารถแก้ไขเจ้าหน้าที่คนอื่นได้ (รวมถึง admin00)
        if target_user_role == 'admin':
            return False
        # แก้ไขอาจารย์, นักศึกษา, สาขาได้
        return target_user_role in ['teacher', 'student', 'department']
    
    # Role อื่นๆ แก้ไขได้เฉพาะตัวเอง
    return False

def can_delete_user(current_user_id, current_username, target_user_id, target_username, current_user_role, target_user_role):
    """ตรวจสอบว่าสามารถลบผู้ใช้ได้หรือไม่"""
    
    # ไม่สามารถลบตัวเองได้
    if current_user_id == target_user_id:
        return False
    
    # ไม่สามารถลบ admin00 ได้
    if is_super_admin(target_username):
        return False
    
    # admin00 สามารถลบได้ทุกคน (ยกเว้นตัวเอง)
    if is_super_admin(current_username):
        return True
    
    # เจ้าหน้าที่ (admin อื่นๆ) ไม่สามารถลบเจ้าหน้าที่คนอื่นได้
    if current_user_role == 'admin' and target_user_role == 'admin':
        return False
    
    # เจ้าหน้าที่สามารถลบอาจารย์, นักศึกษา, สาขาได้
    if current_user_role == 'admin':
        return target_user_role in ['teacher', 'student', 'department']
    
    return False
def get_user_permissions():
    """ส่งข้อมูลสิทธิ์ไปยัง template"""
    current_username = session.get('admin_name', '')
    return {
        'is_super_admin': is_super_admin(current_username),
        'current_username': current_username
    }
@app.route("/update_join_status", methods=["POST"])
@login_required("teacher", "admin")
def update_join_status():
    try:
        join_id = request.form.get('join_id')
        project_id = request.form.get('project_id')
        join_status = int(request.form.get('join_status', 0))
        
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลผู้เข้าร่วมและโครงการ
            cursor.execute("""
                SELECT sr.register_id, sr.status_register, j.join_name, p.project_target, p.teacher_id, 
                       p.project_name, p.project_dotime, p.project_endtime,
                       (SELECT COUNT(*) FROM status_register WHERE project_id = sr.project_id AND status_register = 1) as current_approved
                FROM status_register sr
                JOIN `join` j ON sr.join_id = j.join_id
                JOIN project p ON sr.project_id = p.project_id
                WHERE sr.join_id = %s AND sr.project_id = %s
            """, (join_id, project_id))
            participant_info = cursor.fetchone()
            
            if not participant_info:
                flash("ไม่พบข้อมูลผู้เข้าร่วม", "error")
                return redirect(url_for("admin_home"))
                
            register_id = participant_info[0]  # ใช้ register_id แทน composite key
            old_status = participant_info[1]
            student_name = participant_info[2]
            project_target = int(participant_info[3]) if participant_info[3] else 0
            project_teacher_id = participant_info[4]
            project_name = participant_info[5]
            project_dotime = participant_info[6]
            project_endtime = participant_info[7]
            current_approved = int(participant_info[8]) if participant_info[8] else 0
            
            # ตรวจสอบสิทธิ์
            user_type = session.get("user_type", "")
            logged_in_teacher_id = session.get("teacher_id") if user_type == "teacher" else None
            
            is_project_owner = logged_in_teacher_id and str(logged_in_teacher_id) == str(project_teacher_id)
            is_admin = user_type == "admin"
            
            if not (is_project_owner or is_admin):
                flash("คุณไม่มีสิทธิ์ในการอนุมัติผู้เข้าร่วมโครงการนี้", "error")
                return redirect(url_for("project_participants", project_id=project_id))
            
            # ตรวจสอบจำนวนที่นั่ง
            if join_status == 1 and old_status != 1:
                if current_approved >= project_target:
                    flash(f"ไม่สามารถอนุมัติได้ เนื่องจากโครงการเต็มแล้ว ({current_approved}/{project_target})", "error")
                    return redirect(url_for("project_participants", project_id=project_id))
            
            # ตรวจสอบและปฏิเสธโครงการที่ทับซ้อนอัตโนมัติ
            auto_rejected_projects = []
            if join_status == 1 and old_status != 1:
                # หาโครงการอื่นที่ทับซ้อน
                cursor.execute("""
                    SELECT sr.register_id, sr.project_id, p.project_name, p.project_dotime, p.project_endtime, 
                           sr.status_register, t.teacher_name
                    FROM status_register sr
                    JOIN project p ON sr.project_id = p.project_id
                    JOIN teacher t ON p.teacher_id = t.teacher_id
                    WHERE sr.join_id = %s 
                    AND sr.project_id != %s
                    AND sr.status_register IN (0, 1)
                    AND (
                        (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                        (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                        (p.project_dotime >= %s AND p.project_endtime <= %s)
                    )
                """, (join_id, project_id,
                     project_endtime, project_dotime, 
                     project_dotime, project_dotime, 
                     project_dotime, project_endtime))
                
                conflicting_projects = cursor.fetchall()
                
                # ปฏิเสธโครงการที่ทับซ้อนอัตโนมัติ
                for conflict in conflicting_projects:
                    conflict_register_id = conflict[0]
                    conflict_project_name = conflict[2]
                    conflict_status = conflict[5]
                    teacher_name = conflict[6]
                    
                    # เปลี่ยนสถานะเป็น 2 = ไม่อนุมัติ โดยใช้ register_id
                    cursor.execute("""
                        UPDATE status_register 
                        SET status_register = 2 
                        WHERE register_id = %s
                    """, (conflict_register_id,))
                    
                    auto_rejected_projects.append({
                        'name': conflict_project_name,
                        'teacher': teacher_name,
                        'old_status': conflict_status
                    })
            
            # อัปเดตสถานะโครงการหลัก โดยใช้ register_id
            cursor.execute(
                "UPDATE status_register SET status_register = %s WHERE register_id = %s",
                (join_status, register_id)
            )
            
            db.commit()
            
            # แสดงข้อความแจ้งผลลัพธ์
            status_text = {0: "รอการอนุมัติ", 1: "อนุมัติแล้ว", 2: "ไม่อนุมัติ"}.get(join_status, "ไม่ทราบสถานะ")
            main_message = f"อัปเดตสถานะ '{student_name}' เป็น '{status_text}' ในโครงการ '{project_name}' เรียบร้อยแล้ว"
            
            # แจ้งเกี่ยวกับโครงการที่ถูกปฏิเสธอัตโนมัติ
            if auto_rejected_projects:
                rejected_list = []
                for rejected in auto_rejected_projects:
                    status_desc = "ที่รออนุมัติ" if rejected['old_status'] == 0 else "ที่อนุมัติแล้ว"
                    rejected_list.append(f"• {rejected['name']} (อ.{rejected['teacher']}) - {status_desc}")
                
                rejection_message = f"\n\n🚫 ปฏิเสธโครงการที่ทับซ้อนอัตโนมัติ ({len(auto_rejected_projects)} โครงการ):\n" + "\n".join(rejected_list)
                main_message += rejection_message
                flash(main_message, "warning")
            else:
                flash(main_message, "success")
                
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        print(f"Error in update_join_status: {e}")
        
    return redirect(url_for("project_participants", project_id=project_id))




@app.route("/project/<int:project_id>/approve_all", methods=["POST"])
@login_required("teacher", "admin")
def approve_all_participants(project_id):
    try:
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลโครงการ
            cursor.execute(
                "SELECT project_target, teacher_id, project_name, project_dotime, project_endtime FROM project WHERE project_id = %s",
                (project_id,)
            )
            project = cursor.fetchone()
            
            if not project:
                flash("ไม่พบข้อมูลโครงการ", "error")
                return redirect(url_for("project_participants", project_id=project_id))
            
            max_participants = int(project[0]) if project[0] else 0
            project_teacher_id = project[1]
            project_name = project[2]
            project_dotime = project[3]
            project_endtime = project[4]
            
            # ตรวจสอบสิทธิ์
            user_type = session.get("user_type", "")
            logged_in_teacher_id = session.get("teacher_id") if user_type == "teacher" else None
            
            is_project_owner = logged_in_teacher_id and str(logged_in_teacher_id) == str(project_teacher_id)
            is_admin = user_type == "admin"
            
            if not (is_project_owner or is_admin):
                flash("คุณไม่มีสิทธิ์ในการอนุมัติผู้เข้าร่วมโครงการนี้", "error")
                return redirect(url_for("project_participants", project_id=project_id))
            
            # นับจำนวนที่อนุมัติแล้ว
            cursor.execute(
                "SELECT COUNT(*) FROM status_register WHERE project_id = %s AND status_register = 1",
                (project_id,)
            )
            current_approved = cursor.fetchone()[0] or 0
            
            # ดึงรายชื่อผู้รออนุมัติ
            cursor.execute("""
                SELECT sr.register_id, sr.join_id, j.join_name, sr.register_time 
                FROM status_register sr
                JOIN `join` j ON sr.join_id = j.join_id
                WHERE sr.project_id = %s AND sr.status_register = 0
                ORDER BY sr.register_time ASC
            """, (project_id,))
            waiting_participants = cursor.fetchall()
            
            if not waiting_participants:
                flash("ไม่มีผู้เข้าร่วมที่รออนุมัติ", "info")
                return redirect(url_for("project_participants", project_id=project_id))
            
            # คำนวณที่นั่งที่เหลือ
            remaining_slots = max(0, max_participants - current_approved)
            approved_count = 0
            total_auto_rejected = 0
            
            # อนุมัติผู้เข้าร่วมตามลำดับการลงทะเบียน
            for i, participant in enumerate(waiting_participants):
                register_id = participant[0]
                join_id = participant[1]
                student_name = participant[2]
                
                if approved_count < remaining_slots:
                    # ตรวจสอบและปฏิเสธโครงการที่ทับซ้อน
                    cursor.execute("""
                        SELECT sr.register_id, p.project_name
                        FROM status_register sr
                        JOIN project p ON sr.project_id = p.project_id
                        WHERE sr.join_id = %s 
                        AND sr.project_id != %s
                        AND sr.status_register IN (0, 1)
                        AND (
                            (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                            (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                            (p.project_dotime >= %s AND p.project_endtime <= %s)
                        )
                    """, (join_id, project_id,
                         project_endtime, project_dotime, 
                         project_dotime, project_dotime, 
                         project_dotime, project_endtime))
                    
                    conflicting_projects = cursor.fetchall()
                    
                    # ปฏิเสธโครงการที่ทับซ้อนอัตโนมัติ
                    for conflict in conflicting_projects:
                        conflict_register_id = conflict[0]
                        cursor.execute("""
                            UPDATE status_register 
                            SET status_register = 2 
                            WHERE register_id = %s
                        """, (conflict_register_id,))
                        total_auto_rejected += 1
                    
                    # อนุมัติโครงการหลัก
                    cursor.execute(
                        "UPDATE status_register SET status_register = 1 WHERE register_id = %s",
                        (register_id,)
                    )
                    approved_count += 1
                else:
                    # ไม่อนุมัติ (เต็มแล้ว)
                    cursor.execute(
                        "UPDATE status_register SET status_register = 2 WHERE register_id = %s",
                        (register_id,)
                    )
            
            db.commit()
            
            # แสดงข้อความผลลัพธ์
            messages = []
            if approved_count > 0:
                messages.append(f"อนุมัติผู้เข้าร่วม {approved_count} คน เรียบร้อยแล้ว")
                if approved_count < len(waiting_participants):
                    rejected_count = len(waiting_participants) - approved_count
                    messages.append(f"ไม่อนุมัติ {rejected_count} คน เนื่องจากโครงการเต็มแล้ว")
            else:
                messages.append("โครงการเต็มแล้ว ไม่สามารถอนุมัติผู้เข้าร่วมเพิ่มได้")
            
            if total_auto_rejected > 0:
                messages.append(f"🚫 ปฏิเสธโครงการที่ทับซ้อนอัตโนมัติ {total_auto_rejected} โครงการ")
            
            flash(" | ".join(messages), "success" if approved_count > 0 else "warning")
                
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        print(f"Error in approve_all_participants: {e}")
        
    return redirect(url_for("project_participants", project_id=project_id))


@app.template_filter('has_schedule_conflict')
def has_schedule_conflict(student_id, project_start, project_end, current_project_id):
    """ตรวจสอบว่านักศึกษามีโครงการที่อนุมัติแล้วซ้อนกันหรือไม่"""
    try:
        with get_db_cursor() as (db, cursor):
            cursor.execute(
                """
                SELECT COUNT(*) 
                FROM `join` j
                JOIN project p ON j.project_id = p.project_id
                WHERE j.join_student_id = %s 
                AND j.join_status = 1
                AND j.project_id != %s
                AND (
                    (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                    (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                    (p.project_dotime >= %s AND p.project_endtime <= %s)
                )
                """,
                (student_id, current_project_id,
                 project_end, project_start,
                 project_start, project_start,
                 project_start, project_end)
            )
            count = cursor.fetchone()[0]
            return count > 0
    except:
        return False

# ลงทะเบียนฟิลเตอร์
app.jinja_env.filters['has_schedule_conflict'] = has_schedule_conflict
# ฟังก์ชันแสดงรายชื่อผู้เข้าร่วม
def check_student_schedule_conflict(student_id, project_dotime, project_endtime, current_project_id=None):
    """ตรวจสอบว่านักศึกษามีโครงการที่ทับซ้อนกันหรือไม่"""
    with get_db_cursor() as (db, cursor):
        query = """
            SELECT p.project_name, p.project_dotime, p.project_endtime, j.join_status
            FROM `join` j
            JOIN project p ON j.project_id = p.project_id
            WHERE j.join_student_id = %s 
            AND j.join_status IN (0, 1)  -- รออนุมัติหรืออนุมัติแล้ว
            AND (
                (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                (p.project_dotime >= %s AND p.project_endtime <= %s)
            )
        """
        
        params = [student_id, project_endtime, project_dotime, 
                 project_dotime, project_dotime, project_dotime, project_endtime]
        
        if current_project_id:
            query += " AND p.project_id != %s"
            params.append(current_project_id)
            
        cursor.execute(query, params)
        conflicts = cursor.fetchall()
        
        return conflicts
@app.route('/check_schedule_conflict', methods=['POST'])
def check_schedule_conflict():
    student_id = request.form.get('student_id')
    project_id = request.form.get('project_id')
    
    if not student_id or not project_id:
        return jsonify({'has_conflict': False})
    
    with get_db_cursor() as (db, cursor):
        cursor.execute(
            "SELECT project_dotime, project_endtime FROM project WHERE project_id = %s",
            (project_id,)
        )
        current_project = cursor.fetchone()
        
        if not current_project:
            return jsonify({'has_conflict': False})
        
        # ใช้ register_id ในการ JOIN
        query = """
            SELECT p.project_name, p.project_dotime, p.project_endtime, sr.status_register
            FROM status_register sr
            JOIN project p ON sr.project_id = p.project_id
            WHERE sr.join_id = %s 
            AND sr.status_register IN (0, 1)
            AND sr.project_id != %s
            AND (
                (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                (p.project_dotime <= %s AND p.project_endtime >= %s) OR
                (p.project_dotime >= %s AND p.project_endtime <= %s)
            )
        """
        
        params = [student_id, project_id,
                 current_project[1], current_project[0], 
                 current_project[0], current_project[0], 
                 current_project[0], current_project[1]]
            
        cursor.execute(query, params)
        conflicts = cursor.fetchall()
        
        if conflicts:
            conflict_list = []
            for conflict in conflicts:
                status_text = "รออนุมัติ" if conflict[3] == 0 else "อนุมัติแล้ว"
                conflict_list.append({
                    'name': conflict[0],
                    'start_date': conflict[1].strftime('%d/%m/%Y'),
                    'end_date': conflict[2].strftime('%d/%m/%Y'),
                    'status': status_text
                })
            
            return jsonify({
                'has_conflict': True,
                'conflicts': conflict_list
            })
        
        return jsonify({'has_conflict': False})

    
@app.route("/project/<int:project_id>/participants")
def project_participants(project_id):
    try:
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลโครงการพื้นฐาน
            cursor.execute("""
                SELECT p.project_id, p.project_name, p.project_style, p.project_dotime, p.project_endtime, 
                       p.project_target, p.project_detail, p.project_budgettype, p.project_year,
                       p.teacher_id, a.project_status, a.project_statusStart
                FROM project p
                JOIN approval a ON p.project_id = a.project_id
                WHERE p.project_id = %s
            """, (project_id,))
            project_data = cursor.fetchone()
            
            if not project_data:
                flash("ไม่พบข้อมูลโครงการ", "error")
                return redirect(url_for("home"))
            
            # นับจำนวนผู้เข้าร่วมที่อนุมัติแล้ว
            cursor.execute(
                "SELECT COUNT(*) FROM status_register WHERE project_id = %s AND status_register = 1",
                (project_id,)
            )
            approved_count = cursor.fetchone()[0] or 0
            
            # ดึงข้อมูลอาจารย์ผู้รับผิดชอบ
            cursor.execute("""
                SELECT t.teacher_id, t.teacher_name, t.teacher_email, t.teacher_phone, b.branch_name
                FROM project p
                JOIN teacher t ON p.teacher_id = t.teacher_id
                LEFT JOIN branch b ON t.branch_id = b.branch_id
                WHERE p.project_id = %s
            """, (project_id,))
            teacher_data = cursor.fetchone()
            
            # ดึงรายชื่อผู้เข้าร่วมทั้งหมด พร้อม register_id (ถ้ามี)
            try:
                # ลองใช้ query ที่มี register_id ก่อน
                cursor.execute("""
                    SELECT sr.register_id, j.join_id, j.join_name, j.join_email, j.join_telephone, 
                           sr.status_register, j.branch_id, b.branch_name, sr.register_time
                    FROM status_register sr
                    JOIN `join` j ON sr.join_id = j.join_id
                    LEFT JOIN branch b ON j.branch_id = b.branch_id
                    WHERE sr.project_id = %s
                    ORDER BY sr.status_register ASC, sr.register_time ASC
                """, (project_id,))
                participants_raw = cursor.fetchall()
                has_register_id = True
                
            except Exception as e:
                # ถ้า register_id ยังไม่มี ให้ใช้ query แบบเก่า
                print(f"Using fallback query without register_id: {e}")
                cursor.execute("""
                    SELECT NULL as register_id, j.join_id, j.join_name, j.join_email, j.join_telephone, 
                           sr.status_register, j.branch_id, b.branch_name, sr.register_time
                    FROM status_register sr
                    JOIN `join` j ON sr.join_id = j.join_id
                    LEFT JOIN branch b ON j.branch_id = b.branch_id
                    WHERE sr.project_id = %s
                    ORDER BY sr.status_register ASC, sr.register_time ASC
                """, (project_id,))
                participants_raw = cursor.fetchall()
                has_register_id = False
            
            # จัดรูปแบบข้อมูลผู้เข้าร่วม
            participants = []
            waiting_count = 0
            
            if participants_raw:
                for i, p in enumerate(participants_raw):
                    participant = {
                        'register_id': p[0] if has_register_id and p[0] is not None else None,
                        'join_id': p[1], 
                        'join_name': p[2] or 'ไม่ระบุชื่อ',
                        'join_email': p[3] or 'ไม่ระบุอีเมล',
                        'join_telephone': p[4] or 'ไม่ระบุเบอร์',
                        'status_register': p[5],
                        'branch_id': p[6],
                        'branch_name': p[7] if p[7] else "ไม่ระบุสาขา",
                        'register_time': p[8],
                        'join_role': 'student'
                    }
                    participants.append(participant)
                    
                    if p[5] == 0:  # status_register = 0 (รออนุมัติ)
                        waiting_count += 1
            
            # จัดรูปแบบข้อมูลโครงการ
            project = {
                'project_id': project_data[0],
                'project_name': project_data[1],
                'project_style': project_data[2],
                'project_dotime': project_data[3],
                'project_endtime': project_data[4],
                'project_target': int(project_data[5]) if project_data[5] else 0,
                'project_detail': project_data[6],
                'project_budgettype': project_data[7],
                'project_year': project_data[8],
                'teacher_id': project_data[9],
                'project_status': project_data[10],
                'project_statusStart': project_data[11]
            }
            
            # จัดรูปแบบข้อมูลอาจารย์
            teacher = None
            if teacher_data:
                teacher = {
                    'teacher_id': teacher_data[0],
                    'teacher_name': teacher_data[1],
                    'teacher_email': teacher_data[2],
                    'teacher_phone': teacher_data[3],
                    'branch_name': teacher_data[4] or 'ไม่ระบุสาขา'
                }

            # ตรวจสอบสิทธิ์ผู้ใช้
            is_logged_in = "user_type" in session
            user_type = session.get("user_type", "")
            logged_in_teacher_id = session.get("teacher_id") if user_type == "teacher" else None
            
            is_project_owner = logged_in_teacher_id and str(logged_in_teacher_id) == str(project['teacher_id'])
            is_admin = user_type == "admin"
            can_approve = is_admin or is_project_owner
            
            # คำนวณที่นั่งที่เหลือ
            available_slots = max(0, project['project_target'] - approved_count)
            
            # ข้อมูลสำหรับส่งไปยัง template
            template_data = {
                "project_id": project_id,
                "project": project,
                "teacher": teacher,
                "participants": participants,
                "is_logged_in": is_logged_in,
                "user_type": user_type,
                "is_project_owner": is_project_owner,
                "is_admin": is_admin,
                "can_approve": can_approve,
                "current_approved": approved_count,
                "available_slots": available_slots,
                "total_participants": len(participants),
                "waiting_count": waiting_count,
                "has_register_id": has_register_id
            }
            
            # Debug information
            print(f"Project participants data:")
            print(f"- Project ID: {project_id}")
            print(f"- Total participants: {len(participants)}")
            print(f"- Waiting count: {waiting_count}")
            print(f"- Current approved: {approved_count}")
            print(f"- Has register_id: {has_register_id}")
            print(f"- Can approve: {can_approve}")
            
            return render_template("project_participants.html", **template_data)
            
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error in project_participants: {e}")
        print(f"Error detail: {error_detail}")
        
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        return redirect(url_for("project_detail", project_id=project_id))

            
    
        
@app.route("/uploads/<filename>")
@login_required("teacher")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


def get_teachers_from_database():
    with get_db_cursor() as (db, cursor):
        query = """SELECT t.teacher_id, t.teacher_name, t.teacher_username, 
                   t.teacher_password, t.teacher_phone, t.teacher_email, 
                   b.branch_name, t.branch_id
                   FROM teacher t
                   JOIN branch b ON t.branch_id = b.branch_id"""
        cursor.execute(query)
        teachers = cursor.fetchall()
    return teachers

def create_project_summary_pdf(project_data):
    try:
        # ลงทะเบียนฟอนต์ไทย
        try:
            pdfmetrics.registerFont(TTFont("THSarabunNew", font_path))
            pdfmetrics.registerFont(TTFont("THSarabunNew-Bold", bold_font_path))
        except Exception as e:
            print(f"Error registering fonts: {e}")
            
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=30,
            leftMargin=30,
            topMargin=70,
            bottomMargin=30,
        )

        # สร้างสไตล์
        normal_style = ParagraphStyle(
            'Normal',
            fontName='THSarabunNew',
            fontSize=14,
            leading=18,
            spaceBefore=4,
            spaceAfter=4
        )
        
        heading_style = ParagraphStyle(
            'Heading',
            fontName='THSarabunNew-Bold',
            fontSize=16,
            leading=20,
            alignment=1,  # center
            spaceAfter=8
        )
        
        title_style = ParagraphStyle(
            'Title',
            fontName='THSarabunNew-Bold',
            fontSize=18,
            alignment=1,  # center
            spaceAfter=8
        )
        
        # สไตล์ที่ปรับปรุงสำหรับตาราง
        table_header_style = ParagraphStyle(
            'TableHeader',
            fontName='THSarabunNew-Bold',
            fontSize=14,
            alignment=1,  # center alignment
            spaceBefore=4,
            spaceAfter=4
        )
        
        table_item_style = ParagraphStyle(
            'TableItem',
            fontName='THSarabunNew',
            fontSize=14,
            spaceBefore=4,
            spaceAfter=4,
            alignment=1  # center alignment by default
        )
        
        table_item_left_style = ParagraphStyle(
            'TableItemLeft',
            fontName='THSarabunNew',
            fontSize=14,
            spaceBefore=4,
            spaceAfter=4,
            alignment=0  # left alignment
        )

        def header(canvas, doc):
            canvas.saveState()
            # วันที่พิมพ์
            canvas.setFont('THSarabunNew', 12)
            today = datetime.now().strftime("%d/%m/%Y")
            canvas.drawRightString(doc.pagesize[0] - 40, doc.pagesize[1] - 40, f"พิมพ์เมื่อ: {today}")
            
            # หมายเลขหน้า
            canvas.setFont('THSarabunNew', 12)
            canvas.drawRightString(doc.pagesize[0] - 40, 30, f"หน้า {canvas.getPageNumber()}")
            
            # โลโก้และหัวกระดาษเฉพาะหน้าแรก
            if canvas.getPageNumber() == 1:  # เฉพาะหน้าแรก
                # โลโก้มหาวิทยาลัย (ที่นี่เป็นแค่ตัวอย่าง คุณต้องระบุเส้นทางไฟล์โลโก้ที่ถูกต้อง)
                try:
                    logo_path = "logo.png"  # แทนที่ด้วยเส้นทางโลโก้ของคุณ
                    if os.path.exists(logo_path):
                        img = ImageReader(logo_path)
                        logo_width = 1 * inch
                        logo_height = 1 * inch
                        page_width = doc.pagesize[0]
                        page_center = page_width / 2
                        
                        canvas.drawImage(
                            img,
                            page_center - (logo_width/2),
                            doc.pagesize[1] - 130,
                            width=logo_width,
                            height=logo_height
                        )
                except Exception as e:
                    print(f"Error loading logo: {e}")
                
                # หัวเรื่องโปรไฟล์
                canvas.setFont('THSarabunNew-Bold', 20)
                canvas.drawCentredString(
                    page_center,
                    doc.pagesize[1] - 175,
                    "บันทึกข้อความ"
                )
            
            canvas.restoreState()

        def footer(canvas, doc):
            canvas.saveState()
            # เส้นคั่นด้านล่าง
            canvas.setLineWidth(1)
            canvas.line(40, 50, doc.pagesize[0] - 40, 50)
            canvas.setFont('THSarabunNew', 12)
            canvas.drawCentredString(
                doc.pagesize[0] / 2,
                35,
                "มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น"
            )
            canvas.restoreState()

        content = []
        
        # สร้างหัวกระดาษ - บันทึกข้อความ
        content.append(Spacer(1, 120))  # เพิ่มระยะห่างด้านบนให้มากขึ้น
        
        # ดึงข้อมูลจาก project_data
        branch_name = project_data.get('branch_name', 'ไม่ระบุสาขา')
        project_name = project_data.get('project_name', 'ไม่ระบุชื่อโครงการ')
        project_year = project_data.get('project_year', 'ไม่ระบุปีงบประมาณ')
        project_budget = float(project_data.get('project_budget', 0))
        project_dotime = project_data.get('project_dotime', '')
        project_endtime = project_data.get('project_endtime', '')
        project_address = project_data.get('project_address', 'ไม่ระบุสถานที่')
        project_target = int(project_data.get('project_target', 0))
        teacher_name = project_data.get('teacher_name', 'ไม่ระบุชื่อผู้รับผิดชอบ')
        participant_count = int(project_data.get('participant_count', 0))
        average_score = float(project_data.get('average_score', 0))
        
        # คำนวณประสิทธิผลโครงการ
        target_percentage = (participant_count / project_target) * 100 if project_target > 0 else 0
        satisfaction_percentage = average_score * 20  # แปลงคะแนนจาก 0-5 เป็น 0-100
        
        # ปัญหาและแนวทางแก้ไข (ฟิลด์ที่ต้องการเพิ่ม)
        project_problems = project_data.get('project_problems', '')
        project_solutions = project_data.get('project_solutions', '')
        
        # ส่วนงานภายใน
        content.append(Paragraph(f"<b>ส่วนงานภายใน</b> สาขา/แผนก{branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ โทร. (IP) ................", normal_style))
        
        # สร้าง format วันที่
        today = datetime.now()
        thai_month = [
            "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
            "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
        ]
        thai_year = today.year + 543
        thai_date = f"{today.day} {thai_month[today.month-1]} {thai_year}"
        
        content.append(Paragraph(f"<b>ที่</b> มทร.อีสาน 34............/ <b>วันที่</b> {today.day} {thai_month[today.month-1]} {thai_year}", normal_style))
        
        # เรื่องและเรียน
        content.append(Paragraph("<b>เรื่อง</b> ขอส่งรายงานผลการดำเนินโครงการ", normal_style))
        content.append(Paragraph("<b>เรียน</b> คณบดีคณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ", normal_style))
        
        # เว้นระยะห่างจากเส้นแบ่ง
        content.append(Spacer(1, 15))  # เพิ่มระยะห่างหลังจากส่วนหัว
        
        # เนื้อหา
        content.append(Spacer(1, 6))
        
        # แปลงวันที่ให้อยู่ในรูปแบบที่ต้องการ
        project_date_format = ""
        try:
            if isinstance(project_dotime, str):
                if 'T' in project_dotime:  # ISO format
                    project_dotime = datetime.fromisoformat(project_dotime.replace('Z', '+00:00')).strftime('%d/%m/%Y')
                    project_endtime = datetime.fromisoformat(project_endtime.replace('Z', '+00:00')).strftime('%d/%m/%Y')
            else:
                project_dotime = project_dotime.strftime('%d/%m/%Y')
                project_endtime = project_endtime.strftime('%d/%m/%Y')
            project_date_format = f"{project_dotime} ถึง {project_endtime}"
        except Exception as e:
            project_date_format = f"{project_dotime} ถึง {project_endtime}"
            print(f"Error formatting dates: {e}")
        
        main_text = f"""        ตามที่ สาขา/แผนก{branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ ได้ดำเนินโครงการ{project_name} งบประมาณ{project_name} (ในแผน) ประจำปีงบประมาณ พ.ศ. {project_year} จำนวนเงิน {'{:,.2f}'.format(project_budget)} บาท ({thai_money_text(project_budget)}) วันที่{project_date_format} ณ {project_address}
        
        ในการนี้ สาขา/แผนก{branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ ได้ดำเนินโครงการเสร็จเป็นที่เรียบร้อยแล้ว จึงขอนำส่งรายงานสรุปผลประเมินความสำเร็จตามวัตถุประสงค์ของแผนการจัดกิจกรรมตามผลผลิต โดยมีรายละเอียดดังเอกสารแนบ"""
        content.append(Paragraph(main_text, normal_style))
        
        # สร้างตารางสรุป
        target_percent = '{:.1f}'.format(target_percentage)
        data = [
            [Paragraph("<b>ตัวชี้วัด</b>", table_header_style), 
             Paragraph("<b>หน่วยนับ</b>", table_header_style), 
             Paragraph("<b>แผน</b>", table_header_style), 
             Paragraph("<b>ผลดำเนินงาน</b>", table_header_style),
             Paragraph("<b>สรุปผล</b>", table_header_style)],
             
            [Paragraph("<b>เชิงปริมาณ</b>", table_header_style), "", "", "", ""],
            
            [Paragraph(f"ผู้เข้าร่วมโครงการจำนวน {project_target} คน", table_item_left_style),
             Paragraph("คน", table_item_style),
             Paragraph(f"{project_target}", table_item_style),
             Paragraph(f"{participant_count}", table_item_style),
             Paragraph("บรรลุ" if target_percentage >= 75 else "ไม่บรรลุ", table_item_style)],
             
            [Paragraph(f"จำนวนผู้เข้าร่วมโครงการไม่ต่ำกว่าร้อยละ 75", table_item_left_style),
             Paragraph("ร้อยละ", table_item_style),
             Paragraph("75", table_item_style),
             Paragraph(f"{target_percent}", table_item_style),
             Paragraph("บรรลุ" if target_percentage >= 75 else "ไม่บรรลุ", table_item_style)],
             
            [Paragraph("<b>เชิงคุณภาพ</b>", table_header_style), "", "", "", ""],
            
            [Paragraph(f"ผู้เข้าร่วมโครงการมีความพึงพอใจไม่ต่ำกว่าร้อยละ 70", table_item_left_style),
             Paragraph("ร้อยละ", table_item_style),
             Paragraph("70", table_item_style),
             Paragraph(f"{satisfaction_percentage:.1f}", table_item_style),
             Paragraph("บรรลุ" if average_score >= 3.5 else "ไม่บรรลุ", table_item_style)],
             
            [Paragraph("รายงานผลการดำเนินโครงการ 1 ชุด", table_item_left_style),
             Paragraph("ชุด", table_item_style),
             Paragraph("1", table_item_style),
             Paragraph("1", table_item_style),
             Paragraph("บรรลุ", table_item_style)],
             
            [Paragraph("<b>เชิงเวลา</b>", table_header_style), "", "", "", ""],
            
            [Paragraph("โครงการแล้วเสร็จตามระยะเวลาที่กำหนด ไม่ต่ำกว่าร้อยละ 100", table_item_left_style),
             Paragraph("ร้อยละ", table_item_style),
             Paragraph("100", table_item_style),
             Paragraph("100", table_item_style),
             Paragraph("บรรลุ", table_item_style)],
             
            [Paragraph("<b>เชิงค่าใช้จ่าย</b>", table_header_style), "", "", "", ""],
            
            [Paragraph(f"งบประมาณที่ใช้ดำเนินโครงการ {'{:,.2f}'.format(project_budget)} บาท", table_item_left_style),
             Paragraph("บาท", table_item_style),
             Paragraph(f"{'{:,.2f}'.format(project_budget)}", table_item_style),
             Paragraph(f"{'{:,.2f}'.format(project_budget)}", table_item_style),
             Paragraph("บรรลุ", table_item_style)]
        ]
        
        col_widths = [200, 70, 70, 100, 70]  # กำหนดความกว้างคอลัมน์
        summary_table = Table(data, colWidths=col_widths)
        
        # ปรับแต่งตาราง
        summary_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),  # Center align all cells except first column
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),   # Center align header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('BACKGROUND', (0, 1), (0, 1), colors.lightgrey),
            ('BACKGROUND', (0, 4), (0, 4), colors.lightgrey),
            ('BACKGROUND', (0, 7), (0, 7), colors.lightgrey),
            ('BACKGROUND', (0, 9), (0, 9), colors.lightgrey),
            ('SPAN', (1, 1), (4, 1)),  # ช่วงเชิงปริมาณ
            ('SPAN', (1, 4), (4, 4)),  # ช่วงเชิงคุณภาพ
            ('SPAN', (1, 7), (4, 7)),  # ช่วงเชิงเวลา
            ('SPAN', (1, 9), (4, 9)),  # ช่วงเชิงค่าใช้จ่าย
            ('LEFTPADDING', (0, 0), (-1, -1), 8),   # เพิ่ม padding ซ้าย
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),  # เพิ่ม padding ขวา
            ('TOPPADDING', (0, 0), (-1, -1), 4),    # เพิ่ม padding บน
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4), # เพิ่ม padding ล่าง
        ]))
        
        content.append(Spacer(1, 6))
        content.append(summary_table)
        content.append(Spacer(1, 6))
        
        # ลงชื่อ
        content.append(Paragraph("จึงเรียนมาเพื่อโปรดพิจารณา", normal_style))
        content.append(Spacer(1, 15))
        content.append(Paragraph(f"({teacher_name})", normal_style))
        content.append(Paragraph("ผู้รับผิดชอบโครงการ", normal_style))
        
        # สร้างหน้าใหม่สำหรับส่วนรายงานสรุปผล
        content.append(PageBreak())
        
        # หัวรายงานสรุปผล
        content.append(Paragraph(f"<b>ชื่อโครงการ :</b> {project_name}", normal_style))
        content.append(Paragraph(f"<b>สาขา :</b> {branch_name} <b>งบประมาณเงินรายได้</b> (ในแผน) ประจำปีงบประมาณ {project_year}", normal_style))
        content.append(Paragraph(f"<b>ระยะเวลา</b> วันที่{project_date_format} <b>สถานที่</b> ณ {project_address}", normal_style))
        content.append(Paragraph(f"<b>ผู้รับผิดชอบ</b> ชื่อ{teacher_name}", normal_style))
        content.append(Spacer(1, 12))
        
        # เพิ่มตารางปัญหาและแนวทางแก้ไข
        problem_data = [
            [Paragraph("<b>ปัญหา :</b>", normal_style), ""],
            [Paragraph(project_problems, normal_style), ""],
            [Paragraph("<b>แนวทางแก้ไข :</b>", normal_style), ""],
            [Paragraph(project_solutions, normal_style), ""]
        ]
        
        problem_table = Table(problem_data, colWidths=[520, 30])
        problem_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('SPAN', (0, 0), (1, 0)),  # ปัญหา
            ('SPAN', (0, 1), (1, 1)),  # รายละเอียดปัญหา
            ('SPAN', (0, 2), (1, 2)),  # แนวทางแก้ไข
            ('SPAN', (0, 3), (1, 3)),  # รายละเอียดแนวทางแก้ไข
        ]))
        
        content.append(Paragraph("<b>ปัญหาและแนวทางแก้ไข</b>", heading_style))
        content.append(problem_table)
        content.append(Spacer(1, 12))
        
        # สรุปข้อมูลเพิ่มเติม (ถ้ามี)
        summary_text = project_data.get('summary_text', '')
        if summary_text:
            content.append(Paragraph("<b>สรุปผลการดำเนินโครงการ</b>", heading_style))
            content.append(Spacer(1, 10))
            
            # แยกข้อความเป็นย่อหน้า
            paragraphs = summary_text.split('\n')
            for para in paragraphs:
                if para.strip():
                    content.append(Paragraph(para, normal_style))
        
        # สร้าง PDF
        try:
            doc.build(content, onFirstPage=header, onLaterPages=header)
            buffer.seek(0)
            return buffer
        except Exception as e:
            print(f"Error building PDF: {e}")
            return None
    
    except Exception as e:
        print(f"Error creating PDF: {e}")
        return None
@app.route("/download_project_pdf/<int:project_id>")
@login_required("teacher", "admin")
def download_project_pdf(project_id):
    user_type = g.user["type"]

    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูล PDF จากตาราง approval
        if user_type == "teacher":
            query = """
                SELECT p.project_name, a.project_pdf 
                FROM project p
                JOIN approval a ON p.project_id = a.project_id
                WHERE p.project_id = %s AND p.teacher_id = %s
            """
            cursor.execute(query, (project_id, g.user["id"]))
        else:  # admin
            query = """
                SELECT p.project_name, a.project_pdf 
                FROM project p
                JOIN approval a ON p.project_id = a.project_id
                WHERE p.project_id = %s
            """
            cursor.execute(query, (project_id,))

        result = cursor.fetchone()

        if result and result[1]:  # มี PDF ในฐานข้อมูล
            pdf_content = result[1]
            project_name = result[0]
            
            if verify_pdf(pdf_content):
                return send_file(
                    BytesIO(pdf_content),
                    as_attachment=True,
                    download_name=f"{project_name}.pdf",
                    mimetype="application/pdf",
                )
            else:
                flash("ไฟล์ PDF เสียหาย", "error")
        else:
            flash("ไม่พบไฟล์ PDF สำหรับโครงการนี้", "error")
            
        return redirect(url_for("teacher_projects" if user_type == "teacher" else "approve_project"))


def prepare_logo(logo_path):
    with Image.open(logo_path) as img:
        img = img.convert("RGBA")

        # สร้างภาพใหม่ด้วยพื้นหลังสีขาว
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))

        # วางภาพโลโก้บนพื้นหลังสีขาว
        composite = Image.alpha_composite(background, img)

        # แปลงกลับเป็น RGB
        final_img = composite.convert("RGB")

        img_buffer = BytesIO()
        final_img.save(img_buffer, format="PNG")
        img_buffer.seek(0)

        return img_buffer


def remove_yellow_background(image_path):
    img = Image.open(image_path)
    img = img.convert("RGBA")
    data = img.getdata()

    new_data = []
    for item in data:
        # ปรับค่าสีตามความเหมาะสม
        if item[0] > 200 and item[1] > 200 and item[2] < 100:  # ถ้าเป็นสีเหลือง
            new_data.append((255, 255, 255, 0))  # ทำให้โปร่งใส
        else:
            new_data.append(item)

    img.putdata(new_data)
    return img


def create_project_pdf(project_data):
    try:
        # เพิ่ม logging เพื่อตรวจสอบข้อมูลที่ได้รับ
        logging.info(f"Creating PDF for project: {project_data.get('project_name')}")
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=36,
            leftMargin=36,
            topMargin=70,
            bottomMargin=30,
        )

        # ลงทะเบียนฟอนต์ไทย
        font_path = os.path.join(os.path.dirname(__file__), "THSarabunNew.ttf")
        bold_font_path = os.path.join(
            os.path.dirname(__file__), "THSarabunNew-Bold.ttf"
        )

        pdfmetrics.registerFont(TTFont("THSarabunNew", font_path))
        if os.path.exists(bold_font_path):
            pdfmetrics.registerFont(TTFont("THSarabunNew-Bold", bold_font_path))
        else:
            logging.warning(
                "THSarabunNew-Bold font not found, using regular font for bold text"
            )
            pdfmetrics.registerFont(TTFont("THSarabunNew-Bold", font_path))

        # สร้างสไตล์
        styles = getSampleStyleSheet()
        styles["Normal"].fontName = "THSarabunNew"
        styles["Normal"].fontSize = 14
        styles["Heading1"].fontName = "THSarabunNew-Bold"
        styles["Heading1"].fontSize = 16
        styles["Heading1"].alignment = 1  # center
        styles["Heading2"].fontName = "THSarabunNew-Bold"
        styles["Heading2"].fontSize = 14
        styles["Heading3"].fontName = "THSarabunNew"
        styles["Heading3"].fontSize = 14

        # สร้างสไตล์เพิ่มเติม
        header_style = ParagraphStyle(
            name='Header',
            fontName='THSarabunNew-Bold',
            fontSize=16,
            alignment=1,
            spaceAfter=10
        )
        
        title_style = ParagraphStyle(
            name='Title',
            fontName='THSarabunNew-Bold',
            fontSize=14,
            alignment=0
        )
        
        normal_style = ParagraphStyle(
            name='NormalIndent',
            fontName='THSarabunNew',
            fontSize=14,
            leftIndent=20
        )

        def header(canvas, doc):
            canvas.saveState()
            page_width = doc.pagesize[0]
            page_height = doc.pagesize[1]

            if canvas.getPageNumber() == 1:  # เฉพาะหน้าแรก
                # ตำแหน่งข้อความด้านบน
                text_y = page_height - 30
                
                # เพิ่มข้อความ "แบบฟอร์มการเขียนโครงการ (ง.8)" ด้านบนขวา
                canvas.setFont("THSarabunNew-Bold", 12)
                form_text = "แบบฟอร์มการเขียนโครงการ (ง.8)"
                form_width = canvas.stringWidth(form_text, "THSarabunNew-Bold", 12)
                canvas.drawString(page_width - form_width - 36, text_y, form_text)
                
                # ลงข้อความส่วนหัว
                text_y -= 30  # เลื่อนลงมา
                
                logo_path = os.path.join(app.static_folder, "2.png")
                if os.path.exists(logo_path):
                    try:
                        img = Image.open(logo_path)
                        img = img.convert("RGB")
                        img_width = 50
                        img_height = 50
                        img_buffer = BytesIO()
                        img.save(img_buffer, format="PNG")
                        img_buffer.seek(0)

                        # วาดโลโก้ตรงกลาง
                        canvas.drawImage(
                            ImageReader(img_buffer),
                            page_width/2 - img_width/2,
                            text_y - 10,
                            width=img_width,
                            height=img_height,
                        )
                    except Exception as e:
                        logging.error(f"Error loading logo: {e}")
                
                # เพิ่มข้อความส่วนหัว
                text_y -= 70  # เลื่อนลงอีกหลังจากโลโก้
                
                canvas.setFont("THSarabunNew-Bold", 16)
                canvas.drawCentredString(
                    page_width / 2, text_y, "มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน"
                )
                
                text_y -= 20
                canvas.setFont("THSarabunNew", 14)
                # กำหนดค่าเริ่มต้นสำหรับข้อมูลวิทยาเขต
                canvas.drawCentredString(
                    page_width / 2, text_y, "วิทยาเขต ขอนแก่น"
                )
                
                text_y -= 20
                # กำหนดค่าเริ่มต้นสำหรับข้อมูลหน่วยงาน
                unit_text = f"หน่วยงาน {project_data.get('branch_name', 'ไม่ระบุสาขา')}"
                canvas.drawCentredString(
                    page_width / 2, text_y, unit_text
                )
                
                text_y -= 20
                # กำหนดค่าเริ่มต้นสำหรับข้อมูลงบประมาณ
                project_budgettype = project_data.get('project_budgettype', 'ไม่ระบุ')
                project_year = project_data.get('project_year', 'ไม่ระบุ')
                budget_text = f"งบประมาณ{project_budgettype} ประจำปีงบประมาณ พ.ศ. {project_year}"
                canvas.drawCentredString(
                    page_width / 2, text_y, budget_text
                )
                
                text_y -= 20
                
            
            canvas.restoreState()

        content = []
        content.append(Spacer(1, 2 * inch))  # เพิ่มระยะห่างด้านบน เพื่อเว้นที่สำหรับส่วนหัว
        
        # ชื่อโครงการ
        project_name = project_data.get('project_name', 'ไม่ระบุชื่อโครงการ')
        content.append(
            Paragraph(f"1. ชื่อโครงการ: {project_name}", title_style)
        )
        content.append(Spacer(1, 6))
        
        # ลักษณะโครงการ
        # ลักษณะโครงการ - ปรับปรุงให้ใช้สัญลักษณ์ที่ฟอนต์ไทยรองรับ
        project_style = project_data.get('project_style', 'ไม่ระบุลักษณะโครงการ')
        style_text = f"2. ลักษณะโครงการ: "

        if "จัดฝึกอบรม" in project_style:
            style_text += "( / ) จัดฝึกอบรม (.......) จัดงาน (.......) จัดตามภารกิจปกติ"
        elif "จัดงาน" in project_style:
            style_text += "(.......) จัดฝึกอบรม ( / ) จัดงาน (.......) จัดตามภารกิจปกติ"
        elif "จัดตามภารกิจปกติ" in project_style:
            style_text += "(.......) จัดฝึกอบรม (.......) จัดงาน ( / ) จัดตามภารกิจปกติ"
        else:
            style_text += f"({project_style})"

        content.append(Paragraph(style_text, title_style))
        content.append(Spacer(1, 6))
        
        # โครงการนี้สอดคล้องกับนโยบายชาติ และผลผลิต
        content.append(
            Paragraph("3. โครงการนี้สอดคล้องกับนโยบายชาติ และผลผลิต", title_style)
        )
        
        # ดึงค่านโยบายและตรวจสอบให้แน่ใจว่ามีค่า
        policy_text = project_data.get('policy', '')
        if not policy_text and 'project_policy' in project_data:
            policy_text = project_data.get('project_policy', '')

        content.append(
            Paragraph(f"นโยบายที่: {policy_text}", normal_style)
        )
        
        # ตรวจสอบและใช้ฟิลด์ output หรือ project_output
        output_text = project_data.get('project_output', '')
        if not output_text and 'output' in project_data:
            output_text = project_data.get('output', '')
        content.append(
            Paragraph(f"ผลผลิต: {output_text}", normal_style)
        )
        content.append(Spacer(1, 6))
        
        # ความสอดคล้องประเด็นยุทธศาสตร์ และตัวชี้วัด
        content.append(
            Paragraph("4. ความสอดคล้องประเด็นยุทธศาสตร์ และตัวชี้วัด", title_style)
        )
        
        # ตรวจสอบและใช้ฟิลด์ strategy หรือ project_strategy
        strategy_text = project_data.get('project_strategy', '')
        if not strategy_text and 'strategy' in project_data:
            strategy_text = project_data.get('strategy', '')
        content.append(
            Paragraph(f"ประเด็นยุทธศาสตร์ที่: {strategy_text}", normal_style)
        )
        
        # ตรวจสอบและใช้ฟิลด์ indicator หรือ project_indicator
        indicator_text = project_data.get('project_indicator', '')
        if not indicator_text and 'indicator' in project_data:
            indicator_text = project_data.get('indicator', '')
        content.append(
            Paragraph(f"ตัวชี้วัดที่: {indicator_text}", normal_style)
        )
        content.append(Spacer(1, 6))
        
        # ความสอดคล้องกับ Cluster / Commonality / Physical grouping
        content.append(
            Paragraph("5. ความสอดคล้องกับ Cluster / Commonality / Physical grouping", title_style)
        )
        
        # ตรวจสอบและใช้ฟิลด์ cluster หรือ project_cluster
        cluster_text = project_data.get('project_cluster', '')
        if not cluster_text and 'cluster' in project_data:
            cluster_text = project_data.get('cluster', '')
        content.append(
            Paragraph(f"Cluster: {cluster_text}", normal_style)
        )
        
        # ตรวจสอบและใช้ฟิลด์ commonality หรือ project_commonality
        commonality_text = project_data.get('project_commonality', '')
        if not commonality_text and 'commonality' in project_data:
            commonality_text = project_data.get('commonality', '')
        content.append(
            Paragraph(f"Commonality: {commonality_text}", normal_style)
        )
        
        # ตรวจสอบและใช้ฟิลด์ physical_grouping หรือ project_physical_grouping
        physical_grouping_text = project_data.get('project_physical_grouping', '')
        if not physical_grouping_text and 'physical_grouping' in project_data:
            physical_grouping_text = project_data.get('physical_grouping', '')
        content.append(
            Paragraph(f"Physical grouping: {physical_grouping_text}", normal_style)
        )
        content.append(Spacer(1, 6))
        
        # หน่วยงานที่รับผิดชอบ 
        teacher_name = project_data.get('teacher_name', 'ไม่ระบุ')
        branch_name = project_data.get('branch_name', 'ไม่ระบุ')
        content.append(
            Paragraph(f"6. หน่วยงานที่รับผิดชอบ {branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ", title_style)
        )
        content.append(
            Paragraph("วิทยาเขตขอนแก่น มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน", normal_style)
        )
        content.append(Spacer(1, 6))
        
        # สถานที่ดำเนินงาน
        project_address = project_data.get('project_address', 'ไม่ระบุสถานที่')
        content.append(
            Paragraph(f"7. สถานที่ดำเนินงาน: {project_address}", title_style)
        )
        content.append(Spacer(1, 6))
        
        # ระยะเวลาดำเนินการ
        project_dotime = project_data.get('project_dotime', 'ไม่ระบุวันเริ่มต้น')
        project_endtime = project_data.get('project_endtime', 'ไม่ระบุวันสิ้นสุด')
        
        # ถ้าเป็น datetime object ให้แปลงเป็น string
        if isinstance(project_dotime, datetime):
            project_dotime = project_dotime.strftime('%Y-%m-%d')
        if isinstance(project_endtime, datetime):
            project_endtime = project_endtime.strftime('%Y-%m-%d')
        
        content.append(
            Paragraph(f"8. ระยะเวลาดำเนินการ: {project_dotime} ถึง {project_endtime}", title_style)
        )
        content.append(Spacer(1, 6))
        
        # หลักการและเหตุผล
        content.append(Paragraph("9. หลักการและเหตุผล", title_style))
        
        # ตรวจสอบและใช้ฟิลด์ rationale หรือ project_rationale
        rationale_text = project_data.get('project_rationale', '')
        if not rationale_text and 'rationale' in project_data:
            rationale_text = project_data.get('rationale', '')
        
        # แบ่งย่อหน้าเพื่อให้อ่านง่ายขึ้น
        rationale_paragraphs = rationale_text.split('\n')
        for paragraph in rationale_paragraphs:
            if paragraph.strip():  # ข้าม paragraph ว่าง
                content.append(Paragraph(paragraph, normal_style))
        content.append(Spacer(1, 6))
        
        # วัตถุประสงค์
        content.append(Paragraph("10. วัตถุประสงค์", title_style))
        
        # ตรวจสอบและใช้ฟิลด์ objectives หรือ project_objectives
        objectives_text = project_data.get('project_objectives', '')
        if not objectives_text and 'objectives' in project_data:
            objectives_text = project_data.get('objectives', '')
            
        # แบ่งรายการวัตถุประสงค์
        objectives_paragraphs = objectives_text.split('\n')
        for paragraph in objectives_paragraphs:
            if paragraph.strip():  # ข้าม paragraph ว่าง
                content.append(Paragraph(paragraph, normal_style))
        content.append(Spacer(1, 6))
        
        # เป้าหมาย
        content.append(Paragraph("11. เป้าหมาย", title_style))
        
        # ตรวจสอบและใช้ฟิลด์ goals หรือ project_goals
        goals_text = project_data.get('project_goals', '')
        if not goals_text and 'goals' in project_data:
            goals_text = project_data.get('goals', '')
            
        # แบ่งรายการเป้าหมาย
        goals_paragraphs = goals_text.split('\n')
        for paragraph in goals_paragraphs:
            if paragraph.strip():  # ข้าม paragraph ว่าง
                content.append(Paragraph(paragraph, normal_style))
        
        # ตรวจสอบและใช้ฟิลด์ output_target หรือ project_output_target
        output_target_text = project_data.get('project_output_target', '')
        if not output_target_text and 'output_target' in project_data:
            output_target_text = project_data.get('output_target', '')
        content.append(
            Paragraph(f"11.1 เป้าหมายเชิงผลผลิต (Output): {output_target_text}", normal_style)
        )
        
        # ตรวจสอบและใช้ฟิลด์ outcome_target หรือ project_outcome_target
        outcome_target_text = project_data.get('project_outcome_target', '')
        if not outcome_target_text and 'outcome_target' in project_data:
            outcome_target_text = project_data.get('outcome_target', '')
        content.append(
            Paragraph(f"11.2 เป้าหมายเชิงผลลัพธ์ (Outcome): {outcome_target_text}", normal_style)
        )
        content.append(Spacer(1, 6))
        
        # กิจกรรมดำเนินงาน
        content.append(Paragraph("12. กิจกรรมดำเนินงาน", title_style))
        
        # ตรวจสอบและใช้ฟิลด์ project_activity
        project_activity_text = project_data.get('project_activity', '')
        # แบ่งรายการกิจกรรม
        activity_paragraphs = project_activity_text.split('\n')
        for paragraph in activity_paragraphs:
            if paragraph.strip():  # ข้าม paragraph ว่าง
                content.append(Paragraph(paragraph, normal_style))
        content.append(Spacer(1, 6))
        
        # กลุ่มเป้าหมายผู้เข้าร่วมโครงการ
        content.append(Paragraph("13. กลุ่มเป้าหมายผู้เข้าร่วมโครงการ", title_style))
        
        # ตรวจสอบและกำหนดค่าเริ่มต้นสำหรับ project_target
        project_target = project_data.get('project_target', '0')
        content.append(Paragraph(f"จำนวนผู้เข้าร่วมโครงการ: {str(project_target)} คน", normal_style))
        content.append(Spacer(1, 6))
        
        # งบประมาณ
        content.append(Paragraph("14. งบประมาณ", title_style))
        
        # ตรวจสอบและกำหนดค่าเริ่มต้นสำหรับ project_budget
        project_budget = project_data.get('project_budget', '0')
        content.append(
            Paragraph(f"งบประมาณโครงการ: {project_budget} บาท", normal_style)
        )
        
        # ตรวจสอบว่ามีข้อมูล compensation หรือไม่
        compensation_items = []
        if "compensation" in project_data and project_data["compensation"]:
            compensation_items = project_data["compensation"]
        elif "project_compensation_json" in project_data and project_data["project_compensation_json"]:
            try:
                compensation_items = json.loads(project_data["project_compensation_json"])
            except (json.JSONDecodeError, TypeError):
                compensation_items = []
                
        if compensation_items:
            content.append(Paragraph("14.1 ค่าตอบแทน", normal_style))
            for item in compensation_items:
                content.append(
                    Paragraph(f"- {item['description']}: {item['amount']} บาท", normal_style)
                )
            
            total_compensation = sum(item["amount"] for item in compensation_items)
            content.append(
                Paragraph(f"รวมค่าตอบแทน: {total_compensation} บาท", normal_style)
            )
        
        # ตรวจสอบว่ามีข้อมูล expenses หรือไม่
        expense_items = []
        if "expenses" in project_data and project_data["expenses"]:
            expense_items = project_data["expenses"]
        elif "project_expenses_json" in project_data and project_data["project_expenses_json"]:
            try:
                expense_items = json.loads(project_data["project_expenses_json"])
            except (json.JSONDecodeError, TypeError):
                expense_items = []
                
        if expense_items:
            content.append(Paragraph("14.2 ค่าใช้สอย", normal_style))
            for item in expense_items:
                content.append(
                    Paragraph(f"- {item['description']}: {item['amount']} บาท", normal_style)
                )
            
            total_expenses = sum(item["amount"] for item in expense_items)
            content.append(
                Paragraph(f"รวมค่าใช้สอย: {total_expenses} บาท", normal_style)
            )
        
        if compensation_items or expense_items:
            grand_total = 0
            if compensation_items:
                grand_total += sum(item["amount"] for item in compensation_items)
            if expense_items:
                grand_total += sum(item["amount"] for item in expense_items)
                
            content.append(
                Paragraph(f"รวมค่าใช้จ่ายทั้งสิ้น: {grand_total} บาท", normal_style)
            )
        
        content.append(Paragraph("หมายเหตุ: ค่าใช้จ่ายขอถัวเฉลี่ยตามที่จ่ายจริงทุกรายการ", normal_style))
        content.append(Spacer(1, 6))

        
        content.append(Paragraph("15. แผนปฏิบัติงาน (แผนงาน) แผนการใช้จ่ายงบประมาณ (แผนเงิน) และตัวชี้วัดเป้าหมายผลผลิต", styles['Heading1']))
        content.append(Spacer(1, 10))

        # ดึงข้อมูลกิจกรรม
        activities = []
        if "activities" in project_data and project_data["activities"]:
            activities = project_data["activities"]
        elif "project_activities_json" in project_data and project_data["project_activities_json"]:
            try:
                import json
                activities = json.loads(project_data["project_activities_json"])
            except:
                activities = []

        # ถ้าไม่มีกิจกรรม ให้เพิ่มแถวว่าง
        if not activities:
            # ตัวอย่างกิจกรรม
            activities = [
                {"activity": "dasdasdasd", "months": ["ธ.ค.", "ม.ค."]},
                {"activity": "dasdsd", "months": ["พ.ย.", "ธ.ค."]}
            ]

        # สร้างข้อมูลตารางกิจกรรม
        thai_months = ['ต.ค.', 'พ.ย.', 'ธ.ค.', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.']
        
        # กำหนดปีงบประมาณให้ชัดเจน
        fiscal_year_first = "2567"  # ปีแรก (ต.ค.-ธ.ค.)
        fiscal_year_second = "2568"  # ปีที่สอง (ม.ค.-ก.ย.)
        
        activity_data = []

        # แถวแรก: หัวตาราง - แสดงปีงบประมาณ
        header_row = ['กิจกรรมดำเนินงาน', f'ปี พ.ศ. {fiscal_year_first}', f'ปี พ.ศ. {fiscal_year_second}']
        activity_data.append(header_row)
        
        # Log สำหรับตรวจสอบ
        print(f"Header row: {header_row}")

        # แถวที่สอง: เดือนต่างๆ
        month_row = [''] + thai_months
        activity_data.append(month_row)
        
        # Log สำหรับตรวจสอบ
        print(f"Month row: {month_row}")

        # เพิ่มกิจกรรม
        for activity_item in activities:
            activity_name = activity_item.get('activity', '')
            activity_months = activity_item.get('months', [])
            
            activity_row = [activity_name]
            for month in thai_months:
                if month in activity_months:
                    activity_row.append('X')
                else:
                    activity_row.append('')
            
            activity_data.append(activity_row)

        # สร้างตารางกิจกรรม
        doc_width = doc.width
        first_column_width = 200  # คอลัมน์แรก (กิจกรรมดำเนินงาน)
        month_width = (doc_width - first_column_width) / 12  # ความกว้างของแต่ละเดือน

        # กำหนดความกว้างของแต่ละคอลัมน์
        col_widths = [first_column_width] + [month_width] * 12
        activity_table = Table(activity_data, colWidths=col_widths)

        # กำหนดสไตล์ตารางกิจกรรม
        activity_style = TableStyle([
            # กรอบตาราง
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            
            # การจัดตำแหน่งข้อความ
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),     # คอลัมน์แรกชิดซ้าย
            ('ALIGN', (1, 0), (-1, 0), 'CENTER'),   # หัวตารางกึ่งกลาง
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),  # คอลัมน์เดือนกึ่งกลาง
            
            # การรวมเซลล์ในแถวแรก (ปีงบประมาณ)
            ('SPAN', (1, 0), (3, 0)),  # รวมเซลล์ 3 เดือนแรก (ต.ค.-ธ.ค. 2567)
            ('SPAN', (4, 0), (-1, 0)),  # รวมเซลล์เดือนที่เหลือ (ม.ค.-ก.ย. 2568)
            
            # สีพื้นหลัง - ส่วนหัวตาราง
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),  # แถวแรก (ปีงบประมาณ)
            ('BACKGROUND', (0, 1), (-1, 1), colors.lightgrey),  # แถวที่สอง (ชื่อเดือน)
            
            # ฟอนต์
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
        ])

        activity_table.setStyle(activity_style)
        content.append(activity_table)
        content.append(Spacer(1, 5))  # ระยะห่างระหว่างตาราง

        # ดึงข้อมูลตัวชี้วัดจาก project_data
        quantity_indicator = project_data.get('project_quantity_indicator', '15')
        if not quantity_indicator and 'quantity_indicator' in project_data:
            quantity_indicator = project_data.get('quantity_indicator', '15')

        quality_indicator = project_data.get('project_quality_indicator', 'ผู้เข้าร่วมโครงการมีความพึงพอใจ ไม่ต่ำกว่าร้อยละ 75')
        if not quality_indicator and 'quality_indicator' in project_data:
            quality_indicator = project_data.get('quality_indicator', 'ผู้เข้าร่วมโครงการมีความพึงพอใจ ไม่ต่ำกว่าร้อยละ 75')

        time_indicator = project_data.get('project_time_indicator', 'ร้อยละของโครงการแล้วเสร็จตามระยะเวลาที่กำหนด ไม่ต่ำกว่าร้อยละ 70')
        if not time_indicator and 'time_indicator' in project_data:
            time_indicator = project_data.get('time_indicator', 'ร้อยละของโครงการแล้วเสร็จตามระยะเวลาที่กำหนด ไม่ต่ำกว่าร้อยละ 70')

        cost_indicator = project_data.get('project_cost_indicator', '25000')
        if not cost_indicator and 'cost_indicator' in project_data:
            cost_indicator = project_data.get('cost_indicator', '25000')

        # สร้างตารางตัวชี้วัดแบบ 2 คอลัมน์ (ขนาด 1/3 และ 2/3)
        kpi_data = [
            ['ตัวชี้วัดเป้าหมายผลผลิต', ''],
            ['เชิงปริมาณ', quantity_indicator],
            ['เชิงคุณภาพ', quality_indicator],
            ['เชิงเวลา', time_indicator],
            ['เชิงค่าใช้จ่าย', cost_indicator]
        ]

        # กำหนดความกว้างของตารางตัวชี้วัดให้เท่ากับตารางกิจกรรม
        total_table_width = doc_width
        left_col_width = 200  # เท่ากับคอลัมน์แรกของตารางกิจกรรม
        right_col_width = total_table_width - left_col_width
        kpi_table = Table(kpi_data, colWidths=[left_col_width, right_col_width])

        # กำหนดสไตล์ตารางตัวชี้วัด
        kpi_style = TableStyle([
            # กรอบตารางภายนอก
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            
            # เส้นแนวนอนระหว่างแถว
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.black),
            
            # เส้นแนวตั้ง
            ('LINEAFTER', (0, 0), (0, -1), 0.5, colors.black),  # เส้นหลังคอลัมน์แรก
            
            # การจัดตำแหน่งข้อความ
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # คอลัมน์แรกชิดซ้าย
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),  # หัวตารางคอลัมน์ขวากึ่งกลาง
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),  # คอลัมน์ค่าตัวชี้วัดชิดขวา
            
            # การรวมเซลล์และสีพื้นหลัง
            ('SPAN', (0, 0), (-1, 0)),  # รวมเซลล์หัวข้อตัวชี้วัด
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),  # สีพื้นหลังหัวข้อตัวชี้วัด
            ('BACKGROUND', (0, 1), (0, -1), colors.lightgrey),  # คอลัมน์แรกของตัวชี้วัด
            
            # ระยะห่างภายในเซลล์
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            
            # ฟอนต์
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            
            # ทำให้ข้อความที่ยาวสามารถขึ้นบรรทัดใหม่ได้อัตโนมัติ
            ('WORDWRAP', (1, 1), (1, -1), True),
        ])

        kpi_table.setStyle(kpi_style)
        content.append(kpi_table)
        content.append(Spacer(1, 10))

        # เพิ่มส่วน "ผลที่คาดว่าจะเกิด (Impact)"
        content.append(Paragraph("16. ผลที่คาดว่าจะเกิด (Impact)", title_style))
        
        # ตรวจสอบและใช้ฟิลด์ expected_results หรือ project_expected_results
        expected_results = project_data.get('project_expected_results', '')
        if not expected_results and 'expected_results' in project_data:
            expected_results = project_data.get('expected_results', '')
            
        if expected_results:
            result_paragraphs = expected_results.split('\n')
            for paragraph in result_paragraphs:
                if paragraph.strip():  # ข้าม paragraph ว่าง
                    content.append(Paragraph(paragraph, normal_style))
        else:
            content.append(Paragraph("ไม่มีข้อมูล", normal_style))
            
        # เพิ่มส่วนลงชื่อผู้รับผิดชอบโครงการ
        content.append(Spacer(1, 30))
        
        signature_style = ParagraphStyle(
            name='Signature',
            fontName='THSarabunNew',
            fontSize=14,
            alignment=1  # center
        )
        
        content.append(Paragraph(f"ลงชื่อ ................{teacher_name}........................ ผู้รับผิดชอบโครงการ", signature_style))
        content.append(Paragraph(f"({teacher_name})", signature_style))
      
        content.append(Paragraph(datetime.now().strftime('%d/%m/%Y'), signature_style))
        
        # เพิ่มส่วนความคิดเห็นของผู้บังคับบัญชา
        content.append(Spacer(1, 20))
        content.append(Paragraph("ความคิดเห็นของผู้บังคับบัญชา............จึงเรียนมาเพื่อโปรดพิจารณา...................................", normal_style))
       
        try:
            doc.build(content, onFirstPage=header, onLaterPages=header)
            buffer.seek(0)
            return buffer
        except Exception as e:
            logging.error(f"Error building PDF: {e}", exc_info=True)
            return None

    except Exception as e:
        logging.error(f"Error creating PDF: {e}", exc_info=True)
        return None
@app.route("/project_reports")
@login_required("admin", "teacher")
def project_reports():
    # ดึงข้อมูลสำหรับตัวกรอง
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลสาขา
        cursor.execute("SELECT branch_id, branch_name FROM branch ORDER BY branch_name")
        branches = cursor.fetchall()
        
        # ดึงปีงบประมาณทั้งหมด
        cursor.execute("SELECT DISTINCT project_year FROM project ORDER BY project_year DESC")
        years = [year[0] for year in cursor.fetchall()]
        
        # ดึงประเภทงบประมาณ
        cursor.execute("SELECT DISTINCT project_budgettype FROM project ORDER BY project_budgettype")
        budget_types = [type[0] for type in cursor.fetchall()]
        
        # ดึงข้อมูลนโยบาย
        cursor.execute("SELECT DISTINCT project_policy FROM project WHERE project_policy IS NOT NULL ORDER BY project_policy")
        policies = [policy[0] for policy in cursor.fetchall()]
        
        # รับพารามิเตอร์กรองจาก URL
        branch_id = request.args.get("branch", "all")
        year = request.args.get("year", "all")
        budget_type = request.args.get("budget_type", "all")
        policy = request.args.get("policy", "all")
        
        # แก้ไข: สร้าง query พื้นฐาน - ใช้ summary table และ approval table
        base_query = """
            SELECT p.project_id, p.project_name, p.project_year, p.project_budgettype,
                   p.project_dotime, p.project_endtime, s.project_close_date,
                   p.project_budget, p.project_policy, t.teacher_name, b.branch_name,
                   a.admin_id, ad.admin_name as approver_name
            FROM project p
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN branch b ON t.branch_id = b.branch_id
            JOIN approval a ON p.project_id = a.project_id
            LEFT JOIN summary s ON p.project_id = s.project_id
            LEFT JOIN admin ad ON a.admin_id = ad.admin_id
            WHERE a.project_statusStart = 2
        """
        
        # เพิ่มเงื่อนไขการกรอง
        params = []
        
        if branch_id != "all":
            base_query += " AND t.branch_id = %s"
            params.append(branch_id)
            
        if year != "all":
            base_query += " AND p.project_year = %s"
            params.append(year)
            
        if budget_type != "all":
            base_query += " AND p.project_budgettype = %s"
            params.append(budget_type)
            
        if policy != "all":
            base_query += " AND p.project_policy = %s"
            params.append(policy)
        
        # เพิ่มการเรียงลำดับ
        base_query += " ORDER BY COALESCE(s.project_close_date, p.project_endtime) DESC"
        
        # ดึงข้อมูลโครงการ
        cursor.execute(base_query, params)
        projects = cursor.fetchall()
        
        # คำนวณสรุปข้อมูล
        total_projects = len(projects)
        total_budget = sum(float(p[7]) for p in projects if p[7] is not None)
        
        # จัดกลุ่มข้อมูลตามสาขา
        branch_stats = {}
        for p in projects:
            branch_name = p[10]
            if branch_name not in branch_stats:
                branch_stats[branch_name] = {
                    "count": 0,
                    "budget": 0
                }
            branch_stats[branch_name]["count"] += 1
            branch_stats[branch_name]["budget"] += float(p[7]) if p[7] is not None else 0
        
        # จัดกลุ่มข้อมูลตามนโยบาย
        policy_stats = {}
        for p in projects:
            policy_name = p[8] if p[8] is not None else "ไม่ระบุ"
            if policy_name not in policy_stats:
                policy_stats[policy_name] = {
                    "count": 0,
                    "budget": 0
                }
            policy_stats[policy_name]["count"] += 1
            policy_stats[policy_name]["budget"] += float(p[7]) if p[7] is not None else 0
        
        # จัดกลุ่มข้อมูลตามผู้อนุมัติ
        approver_stats = {}
        for p in projects:
            approver_name = p[12] if p[12] is not None else "ไม่ระบุผู้อนุมัติ"
            if approver_name not in approver_stats:
                approver_stats[approver_name] = {
                    "count": 0,
                    "budget": 0
                }
            approver_stats[approver_name]["count"] += 1
            approver_stats[approver_name]["budget"] += float(p[7]) if p[7] is not None else 0
    
    return render_template(
        "project_reports.html",
        projects=projects,
        branches=branches,
        years=years,
        budget_types=budget_types,
        policies=policies,
        branch_id=branch_id,
        year=year,
        budget_type=budget_type,
        policy=policy,
        total_projects=total_projects,
        total_budget=total_budget,
        branch_stats=branch_stats,
        policy_stats=policy_stats,
        approver_stats=approver_stats
    )
@app.route("/close_project/<int:project_id>", methods=["POST"])
@login_required("teacher")
def close_project(project_id):
    if "teacher_id" not in session:
        return redirect(url_for("login"))

    teacher_id = session["teacher_id"]
    
    with get_db_cursor() as (db, cursor):
        # ตรวจสอบว่าโปรเจ็คนี้เป็นของอาจารย์ท่านนี้จริงหรือไม่
        cursor.execute(
            "SELECT project_id FROM project WHERE project_id = %s AND teacher_id = %s",
            (project_id, teacher_id)
        )
        project = cursor.fetchone()
        
        if not project:
            flash("คุณไม่มีสิทธิ์ในการดำเนินการนี้", "error")
            return redirect(url_for("teacher_projects"))
        
        # อัปเดตสถานะโปรเจ็คเป็นปิดโครงการ
        cursor.execute(
            "UPDATE approval SET project_statusStart = 2 WHERE project_id = %s",
            (project_id,)
        )
        
        # สร้างหรืออัปเดตระเบียนใน summary table
        cursor.execute("""
            INSERT INTO summary (project_id, project_close_date)
            VALUES (%s, NOW())
            ON DUPLICATE KEY UPDATE project_close_date = NOW()
        """, (project_id,))
        
        db.commit()
        
        flash("ปิดโครงการเรียบร้อยแล้ว", "success")
        
    return redirect(url_for("teacher_projects"))
def get_success_level(score):
    """คำนวณระดับความสำเร็จจากคะแนน"""
    if score >= 90:
        return "ดีเยี่ยม"
    elif score >= 80:
        return "ดีมาก"
    elif score >= 70:
        return "ดี"
    elif score >= 60:
        return "พอใช้"
    elif score >= 50:
        return "ต้องปรับปรุง"
    else:
        return "ต้องปรับปรุงเร่งด่วน"
import json
@app.template_filter('from_json')
def from_json(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []

@app.template_filter('enumerate')
def _enumerate(seq):
    """เพิ่ม filter สำหรับ enumerate ใน template"""
    return enumerate(seq)
app.jinja_env.filters['enumerate'] = _enumerate

# ลงทะเบียนฟิลเตอร์หลังจากนิยามฟังก์ชันแล้ว
app.jinja_env.filters['from_json'] = from_json
@app.route("/edit_project/<int:project_id>", methods=["GET", "POST"])
@login_required("teacher")
def edit_project(project_id):
    if "teacher_id" not in session:
        return redirect(url_for("login"))

    teacher_id = session["teacher_id"]

    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลโครงการเดิม (ลบ project_status ออกเพราะอยู่ในตาราง approval)
        query = """SELECT project_id, project_budgettype, project_year, project_name, 
                   project_style, project_address, project_dotime, project_endtime, 
                   project_target, project_budget, project_detail,
                   project_output, project_strategy, project_indicator, project_cluster,
                   project_commonality, project_physical_grouping, project_rationale,
                   project_objectives, project_goals, project_output_target, project_outcome_target,
                   project_activity, project_activities_json, project_quantity_indicator,
                   project_quality_indicator, project_time_indicator, project_cost_indicator,
                   project_expected_results, project_compensation_json, project_expenses_json,
                   project_policy
                   FROM project WHERE project_id = %s AND teacher_id = %s"""
        cursor.execute(query, (project_id, teacher_id))
        project = cursor.fetchone()

        if not project:
            flash("ไม่พบโครงการหรือคุณไม่มีสิทธิ์แก้ไขโครงการนี้", "error")
            return redirect(url_for("teacher_projects"))

        # ดึงข้อมูลอาจารย์และสาขา
        query_teacher = """SELECT teacher_name, branch.branch_name 
                           FROM teacher 
                           JOIN branch ON teacher.branch_id = branch.branch_id 
                           WHERE teacher.teacher_id = %s"""
        cursor.execute(query_teacher, (teacher_id,))
        teacher_info = cursor.fetchone()

    # สร้าง project_data สำหรับ GET request
    # (index ปรับใหม่หลังจากลบ project_status ออก)
    project_data = {
        "project_id": project[0],
        "project_budgettype": project[1],
        "project_year": project[2],
        "project_name": project[3],
        "project_style": project[4],
        "project_address": project[5],
        "project_dotime": project[6],
        "project_endtime": project[7],
        "project_target": project[8],
        # project_status ถูกลบออก (เดิมคือ project[9]) เพราะอยู่ในตาราง approval
        "project_budget": project[9],
        "project_detail": project[10],
        "project_output": project[11],
        "project_strategy": project[12],
        "project_indicator": project[13],
        "project_cluster": project[14],
        "project_commonality": project[15],
        "project_physical_grouping": project[16],
        "project_rationale": project[17],
        "project_objectives": project[18],
        "project_goals": project[19],
        "project_output_target": project[20],
        "project_outcome_target": project[21],
        "project_activity": project[22],
        "project_activities_json": project[23],
        "project_quantity_indicator": project[24],
        "project_quality_indicator": project[25],
        "project_time_indicator": project[26],
        "project_cost_indicator": project[27],
        "project_expected_results": project[28],
        "project_compensation_json": project[29],
        "project_expenses_json": project[30],
        "project_policy": project[31] if len(project) > 31 else "",
        "policy": project[31] if len(project) > 31 else "",
        "teacher_name": teacher_info[0],
        "branch_name": teacher_info[1]
    }

    if request.method == "POST":
        # อัปเดต project_data ด้วยข้อมูลจากฟอร์ม
        project_data.update(
            {
                "project_budgettype": request.form["project_budgettype"],
                "project_year": request.form["project_year"],
                "project_name": request.form["project_name"],
                "project_style": request.form["project_style"],
                "project_address": request.form["project_address"],
                "project_dotime": request.form["project_dotime"],
                "project_endtime": request.form["project_endtime"],
                "project_target": request.form["project_target"],
                "project_budget": request.form["project_budget"],
                "project_detail": request.form["project_detail"],
                "project_output": request.form["output"],
                "output": request.form["output"],
                "project_strategy": request.form["strategy"],
                "strategy": request.form["strategy"],
                "project_indicator": request.form["indicator"],
                "indicator": request.form["indicator"],
                "project_cluster": request.form["cluster"],
                "cluster": request.form["cluster"],
                "project_commonality": request.form["commonality"],
                "commonality": request.form["commonality"],
                "project_physical_grouping": request.form["physical_grouping"],
                "physical_grouping": request.form["physical_grouping"],
                "project_rationale": request.form["rationale"],
                "rationale": request.form["rationale"],
                "project_objectives": request.form["objectives"],
                "objectives": request.form["objectives"],
                "project_goals": request.form["goals"],
                "goals": request.form["goals"],
                "project_output_target": request.form["output_target"],
                "output_target": request.form["output_target"],
                "project_outcome_target": request.form["outcome_target"],
                "outcome_target": request.form["outcome_target"],
                "project_activity": request.form["project_activity"],
                "project_quantity_indicator": request.form["quantity_indicator"],
                "quantity_indicator": request.form["quantity_indicator"],
                "project_quality_indicator": request.form["quality_indicator"],
                "quality_indicator": request.form["quality_indicator"],
                "project_time_indicator": request.form["time_indicator"],
                "time_indicator": request.form["time_indicator"],
                "project_cost_indicator": request.form["cost_indicator"],
                "cost_indicator": request.form["cost_indicator"],
                "project_expected_results": request.form.get("expected_results", ""),
                "expected_results": request.form.get("expected_results", ""),
                "project_policy": request.form.get("policy", ""),
                "policy": request.form.get("policy", ""),
            }
        )

        error_messages = []

        # ตรวจสอบชื่อโครงการซ้ำ
        if project_data["project_name"] != project[3]:
            if is_project_name_duplicate(project_data["project_name"], project_id):
                error_messages.append("ไม่สามารถแก้ไขโครงการได้เนื่องจากชื่อโครงการ '{}' มีอยู่แล้ว กรุณาใช้ชื่อโครงการอื่น".format(project_data["project_name"]))

        # ตรวจสอบวันที่ซ้ำสำหรับครูคนเดียวกัน
        if is_date_overlap_for_teacher(teacher_id, project_data["project_dotime"], project_data["project_endtime"], project_id):
            error_messages.append("ไม่สามารถแก้ไขโครงการได้เนื่องจากคุณมีโครงการอื่นในช่วงเวลา {} ถึง {} แล้ว กรุณาเลือกวันที่อื่น".format(project_data["project_dotime"], project_data["project_endtime"]))

        if error_messages:
            for message in error_messages:
                flash(message, "error")

            try:
                activities = json.loads(project_data.get("project_activities_json")) if project_data.get("project_activities_json") else []
                project_data["activities"] = activities
            except (json.JSONDecodeError, TypeError):
                project_data["activities"] = []

            try:
                compensation = json.loads(project_data.get("project_compensation_json")) if project_data.get("project_compensation_json") else []
                project_data["compensation"] = compensation
            except (json.JSONDecodeError, TypeError):
                project_data["compensation"] = []

            try:
                expenses = json.loads(project_data.get("project_expenses_json")) if project_data.get("project_expenses_json") else []
                project_data["expenses"] = expenses
            except (json.JSONDecodeError, TypeError):
                project_data["expenses"] = []

            return render_template("edit_project.html", project=project_data, teacher_info=teacher_info)

        # รับข้อมูลแผนปฏิบัติงาน
        activities = []
        activity_data = request.form.getlist("activity[]")
        for i, activity in enumerate(activity_data):
            if activity:
                selected_months = request.form.getlist(f"month[{i}][]")
                activities.append({"activity": activity, "months": selected_months})
        activities_json = json.dumps(activities, ensure_ascii=False)
        project_data["activities"] = activities

        # รับข้อมูลค่าตอบแทน
        compensation = []
        compensation_descriptions = request.form.getlist("compensation_description[]")
        compensation_amounts = request.form.getlist("compensation_amount[]")
        for desc, amount in zip(compensation_descriptions, compensation_amounts):
            if desc and amount:
                compensation.append({"description": desc, "amount": float(amount)})
        compensation_json = json.dumps(compensation, ensure_ascii=False)
        project_data["compensation"] = compensation

        # รับข้อมูลค่าใช้สอย
        expenses = []
        expense_descriptions = request.form.getlist("expense_description[]")
        expense_amounts = request.form.getlist("expense_amount[]")
        for desc, amount in zip(expense_descriptions, expense_amounts):
            if desc and amount:
                expenses.append({"description": desc, "amount": float(amount)})
        expenses_json = json.dumps(expenses, ensure_ascii=False)
        project_data["expenses"] = expenses

        # คำนวณยอดรวม
        total_compensation = sum(item["amount"] for item in compensation)
        total_expenses = sum(item["amount"] for item in expenses)
        grand_total = total_compensation + total_expenses

        # บันทึกข้อมูลโครงการลงฐานข้อมูล (ตาราง project)
        with get_db_cursor() as (db, cursor):
            query = """UPDATE project SET 
                       project_budgettype = %s, project_year = %s, project_name = %s, 
                       project_style = %s, project_address = %s, project_dotime = %s, 
                       project_endtime = %s, project_target = %s, project_budget = %s,
                       project_detail = %s, project_output = %s, project_strategy = %s,
                       project_indicator = %s, project_cluster = %s, project_commonality = %s,
                       project_physical_grouping = %s, project_rationale = %s, project_objectives = %s,
                       project_goals = %s, project_output_target = %s, project_outcome_target = %s,
                       project_activity = %s, project_activities_json = %s, project_quantity_indicator = %s,
                       project_quality_indicator = %s, project_time_indicator = %s, project_cost_indicator = %s,
                       project_expected_results = %s, project_compensation_json = %s, project_expenses_json = %s,
                       project_policy = %s
                       WHERE project_id = %s AND teacher_id = %s"""
            cursor.execute(
                query,
                (
                    project_data["project_budgettype"],
                    project_data["project_year"],
                    project_data["project_name"],
                    project_data["project_style"],
                    project_data["project_address"],
                    project_data["project_dotime"],
                    project_data["project_endtime"],
                    project_data["project_target"],
                    project_data["project_budget"],
                    project_data["project_detail"],
                    project_data["project_output"],
                    project_data["project_strategy"],
                    project_data["project_indicator"],
                    project_data["project_cluster"],
                    project_data["project_commonality"],
                    project_data["project_physical_grouping"],
                    project_data["project_rationale"],
                    project_data["project_objectives"],
                    project_data["project_goals"],
                    project_data["project_output_target"],
                    project_data["project_outcome_target"],
                    project_data["project_activity"],
                    activities_json,
                    project_data["project_quantity_indicator"],
                    project_data["project_quality_indicator"],
                    project_data["project_time_indicator"],
                    project_data["project_cost_indicator"],
                    project_data["project_expected_results"],
                    compensation_json,
                    expenses_json,
                    project_data["policy"],
                    project_id,
                    teacher_id
                ),
            )
            db.commit()

        # เพิ่มข้อมูลยอดรวมใน project_data สำหรับสร้าง PDF
        project_data["total_compensation"] = total_compensation
        project_data["total_expenses"] = total_expenses
        project_data["grand_total"] = grand_total

        # แปลงวันที่เป็น string ก่อนส่งไปสร้าง PDF
        if isinstance(project_data["project_dotime"], datetime):
            project_data["project_dotime"] = project_data["project_dotime"].strftime('%Y-%m-%d')
        if isinstance(project_data["project_endtime"], datetime):
            project_data["project_endtime"] = project_data["project_endtime"].strftime('%Y-%m-%d')

        logging.info(f"Creating PDF for project: {project_data['project_name']}")
        logging.info(f"Project data keys: {list(project_data.keys())}")
        logging.info(f"Project dates: {project_data['project_dotime']} to {project_data['project_endtime']}")
        logging.info(f"Project policy: {project_data['policy']}")

        # สร้าง PDF ใหม่
        pdf_buffer = create_project_pdf(project_data)
        if pdf_buffer:
            pdf_content = pdf_buffer.getvalue()

            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(BytesIO(pdf_content))
                page_count = len(reader.pages)
                logging.info(f"Generated PDF has {page_count} pages")
            except Exception as e:
                logging.error(f"Error checking PDF: {e}")

            # บันทึก PDF ลงตาราง approval (ไม่ใช่ตาราง project)
            with get_db_cursor() as (db, cursor):
                try:
                    # ตรวจสอบว่ามี record ใน approval สำหรับ project_id นี้หรือยัง
                    cursor.execute(
                        "SELECT approval_id FROM approval WHERE project_id = %s",
                        (project_id,)
                    )
                    approval_record = cursor.fetchone()

                    if approval_record:
                        # ถ้ามีอยู่แล้ว ให้ UPDATE
                        query = "UPDATE approval SET project_pdf = %s WHERE project_id = %s"
                        cursor.execute(query, (pdf_content, project_id))
                    else:
                        # ถ้ายังไม่มี ให้ INSERT ใหม่ (project_status = 0 = ยังไม่อนุมัติ)
                        query = "INSERT INTO approval (project_id, project_pdf, project_status) VALUES (%s, %s, 0)"
                        cursor.execute(query, (project_id, pdf_content))

                    db.commit()
                    logging.info(f"PDF uploaded for project_id: {project_id}")
                    flash("โครงการและ PDF ถูกบันทึกเรียบร้อยแล้ว", "success")
                except Exception as e:
                    logging.error(f"Error updating PDF in database: {e}")
                    db.rollback()
                    flash(f"เกิดข้อผิดพลาดในการบันทึก PDF: {e}", "error")
        else:
            logging.error("PDF buffer is None - check create_project_pdf function")
            flash("เกิดข้อผิดพลาดในการสร้าง PDF", "error")

        return redirect(url_for("teacher_projects"))

    # แปลง JSON strings กลับเป็น Python lists สำหรับแสดงผลในฟอร์ม (GET request)
    try:
        activities = json.loads(project_data.get("project_activities_json")) if project_data.get("project_activities_json") else []
        project_data["activities"] = activities
    except (json.JSONDecodeError, TypeError):
        project_data["activities"] = []

    try:
        compensation = json.loads(project_data.get("project_compensation_json")) if project_data.get("project_compensation_json") else []
        project_data["compensation"] = compensation
    except (json.JSONDecodeError, TypeError):
        project_data["compensation"] = []

    try:
        expenses = json.loads(project_data.get("project_expenses_json")) if project_data.get("project_expenses_json") else []
        project_data["expenses"] = expenses
    except (json.JSONDecodeError, TypeError):
        project_data["expenses"] = []

    return render_template(
        "edit_project.html", project=project_data, teacher_info=teacher_info
    )
def verify_pdf(pdf_content):
    """ตรวจสอบว่า PDF สร้างถูกต้องหรือไม่"""
    try:
        from PyPDF2 import PdfReader
        from io import BytesIO
        
        reader = PdfReader(BytesIO(pdf_content))
        page_count = len(reader.pages)
        if page_count > 0:
            # ลองดึงข้อความจากหน้าแรกเพื่อตรวจสอบว่ามีเนื้อหาหรือไม่
            text = reader.pages[0].extract_text()
            if text and len(text) > 100:  # ตรวจสอบว่ามีข้อความในหน้าแรก
                return True
        return False
    except Exception as e:
        logging.error(f"Error verifying PDF: {e}")
        return False
# แทนที่ฟังก์ชัน teacher_evaluation_project_updated ใน app.py

@app.route("/teacher_evaluation_project/<int:project_id>")
@login_required("teacher")
def teacher_evaluation_project(project_id):
    with get_db_cursor() as (db, cursor):
        cursor.execute("""
            SELECT project_name, teacher_id 
            FROM project 
            WHERE project_id = %s
        """, (project_id,))
        project_info = cursor.fetchone()
        
        if not project_info:
            flash('ไม่พบโครงการ', 'error')
            return redirect(url_for('teacher_projects'))
        
        project_name, project_teacher_id = project_info
        
        if project_teacher_id != session.get('teacher_id'):
            flash('คุณไม่มีสิทธิ์ดูข้อมูลโครงการนี้', 'error')
            return redirect(url_for('teacher_projects'))
        
        # นับจำนวนผู้เข้าร่วมที่อนุมัติแล้ว
        cursor.execute("""
            SELECT COUNT(*) as total_participants
            FROM status_register
            WHERE project_id = %s AND status_register = 1
        """, (project_id,))
        participants_count = cursor.fetchone()[0] or 0
        
        # ดึงข้อมูลการประเมิน - ลบ evaluation_score ออก
        query = """
        SELECT 
            pe.evaluation_id,
            j.join_name,
            j.join_email,
            pe.project_evaluation_content_score,
            pe.project_evaluation_organization_score,
            pe.project_evaluation_instructor_score,
            pe.project_evaluation_overall_score,
            pe.evaluation_comments,
            pe.evaluation_date,
            pe.project_evaluation_detailed_scores
        FROM 
            project_evaluation pe
        JOIN 
            `join` j ON pe.join_id = j.join_id
        WHERE 
            pe.project_id = %s
        ORDER BY 
            pe.evaluation_date DESC
        """
        cursor.execute(query, (project_id,))
        evaluations = cursor.fetchall()
        
        # สรุปผลการประเมิน - คำนวณค่าเฉลี่ยจากคอลัมน์ที่มีอยู่
        summary_query = """
        SELECT 
            COUNT(*) as total_evaluations,
            ROUND(AVG((COALESCE(project_evaluation_content_score, 0) + 
                      COALESCE(project_evaluation_organization_score, 0) + 
                      COALESCE(project_evaluation_instructor_score, 0) + 
                      COALESCE(project_evaluation_overall_score, 0)) / 4), 2) as average_score,
            ROUND(AVG(COALESCE(project_evaluation_content_score, 0)), 2) as avg_content,
            ROUND(AVG(COALESCE(project_evaluation_organization_score, 0)), 2) as avg_organization,
            ROUND(AVG(COALESCE(project_evaluation_instructor_score, 0)), 2) as avg_instructor,
            ROUND(AVG(COALESCE(project_evaluation_overall_score, 0)), 2) as avg_overall,
            MIN((COALESCE(project_evaluation_content_score, 0) + 
                COALESCE(project_evaluation_organization_score, 0) + 
                COALESCE(project_evaluation_instructor_score, 0) + 
                COALESCE(project_evaluation_overall_score, 0)) / 4) as min_score,
            MAX((COALESCE(project_evaluation_content_score, 0) + 
                COALESCE(project_evaluation_organization_score, 0) + 
                COALESCE(project_evaluation_instructor_score, 0) + 
                COALESCE(project_evaluation_overall_score, 0)) / 4) as max_score
        FROM 
            project_evaluation
        WHERE 
            project_id = %s
        """
        cursor.execute(summary_query, (project_id,))
        summary = cursor.fetchone()
        
        evaluation_list = []
        for row in evaluations:
            # คำนวณคะแนนเฉลี่ยรวมจากทั้ง 4 หมวด
            content_score = float(row[3] or 0)
            organization_score = float(row[4] or 0)
            instructor_score = float(row[5] or 0)
            overall_score = float(row[6] or 0)
            
            average_score = (content_score + organization_score + instructor_score + overall_score) / 4
            
            evaluation_list.append({
                'evaluation_id': row[0],
                'join_name': row[1] or 'ไม่ระบุชื่อ',
                'join_email': row[2] or 'ไม่ระบุอีเมล',
                'evaluation_score': average_score,  # คะแนนเฉลี่ยที่คำนวณใหม่
                'content_score': content_score,
                'organization_score': organization_score,
                'instructor_score': instructor_score,
                'overall_score': overall_score,
                'evaluation_comments': row[7] or '',
                'evaluation_date': row[8],
                'detailed_scores': row[9] or '{}'
            })
        
        if summary:
            summary_data = {
                'total_evaluations': int(summary[0]) if summary[0] else 0,
                'average_score': float(summary[1] or 0),
                'avg_content': float(summary[2] or 0),
                'avg_organization': float(summary[3] or 0),
                'avg_instructor': float(summary[4] or 0),
                'avg_overall': float(summary[5] or 0),
                'min_score': float(summary[6] or 0),
                'max_score': float(summary[7] or 0)
            }
        else:
            summary_data = {
                'total_evaluations': 0,
                'average_score': 0,
                'avg_content': 0,
                'avg_organization': 0,
                'avg_instructor': 0,
                'avg_overall': 0,
                'min_score': 0,
                'max_score': 0
            }
    
    return render_template(
        'teacher_evaluation_project_detail.html', 
        evaluations=evaluation_list,
        project_id=project_id,
        project_name=project_name,
        summary=summary_data,
        participants_count=participants_count
    )


@app.route("/cancel_submission", methods=["POST"])
@login_required("teacher")
def cancel_submission():
    if "teacher_id" not in session:
        return jsonify({"success": False, "message": "ไม่มีสิทธิ์ในการดำเนินการนี้"})

    data = request.json
    project_id = data.get("project_id")
    teacher_id = session["teacher_id"]
    
    try:
        with get_db_cursor() as (db, cursor):
            # ตรวจสอบสิทธิ์และสถานะ
            cursor.execute(
                """SELECT a.project_status 
                   FROM project p
                   JOIN approval a ON p.project_id = a.project_id
                   WHERE p.project_id = %s AND p.teacher_id = %s AND a.project_status = 1""",
                (project_id, teacher_id)
            )
            
            if not cursor.fetchone():
                return jsonify({"success": False, "message": "ไม่พบโครงการหรือไม่มีสิทธิ์ในการยกเลิก"})
            
            # อัปเดตสถานะกลับเป็น "ยังไม่ยื่นอนุมัติ"
            cursor.execute(
                "UPDATE approval SET project_status = 0, project_submit_date = NULL WHERE project_id = %s",
                (project_id,)
            )
            db.commit()
            
            return jsonify({"success": True})
    except Exception as e:
        logging.error(f"Error in cancel_submission: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

# แก้ไขฟังก์ชัน project_summary เพื่อดึงข้อมูลปัญหาและแนวทางแก้ไข
@app.route("/project_summary/<int:project_id>")
@login_required("teacher", "admin")
def project_summary(project_id):
    with get_db_cursor() as (db, cursor):
        # อัปเดต query ให้ใช้ summary table
        cursor.execute("""
            SELECT p.project_id, p.project_name, p.project_budgettype, p.project_year, 
                   p.project_style, p.project_address, p.project_dotime, p.project_endtime, 
                   p.project_target, a.project_status, a.project_statusStart, 
                   p.project_budget, a.project_submit_date, a.project_approve_date,
                   s.project_close_date, t.teacher_name, b.branch_name, s.summary_text,
                   s.project_problems, s.project_solutions
            FROM project p
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN branch b ON t.branch_id = b.branch_id
            JOIN approval a ON p.project_id = a.project_id
            LEFT JOIN summary s ON p.project_id = s.project_id
            WHERE p.project_id = %s
        """, (project_id,))
        project = cursor.fetchone()
        
        if not project:
            flash("ไม่พบข้อมูลโครงการ", "error")
            return redirect(url_for('home'))
        
        project_dict = {
            "project_id": project[0],
            "project_name": project[1],
            "project_budgettype": project[2],
            "project_year": project[3],
            "project_style": project[4],
            "project_address": project[5],
            "project_dotime": project[6],
            "project_endtime": project[7],
            "project_target": int(project[8]) if project[8] is not None else 0,
            "project_status": project[9],
            "project_statusStart": project[10],
            "project_budget": float(project[11]) if project[11] is not None else 0,
            "project_submit_date": project[12],
            "project_approve_date": project[13],
            "project_close_date": project[14],
            "teacher_name": project[15],
            "branch_name": project[16],
            "summary_text": project[17] if project[17] else "",
            "project_problems": project[18] if project[18] else "",
            "project_solutions": project[19] if project[19] else ""
        }
        
        # ดึงข้อมูลผู้เข้าร่วม - อัปเดตให้ใช้ status_register
        cursor.execute("""
            SELECT COUNT(*) as approved_count
            FROM status_register 
            WHERE project_id = %s AND status_register = 1
        """, (project_id,))
        participant_count = int(cursor.fetchone()[0])
        
        # ดึงข้อมูลการประเมิน - แก้ไขให้ไม่ใช้ evaluation_score
        cursor.execute("""
            SELECT 
                COUNT(*) as total_evaluations,
                ROUND(AVG((COALESCE(project_evaluation_content_score, 0) + 
                          COALESCE(project_evaluation_organization_score, 0) + 
                          COALESCE(project_evaluation_instructor_score, 0) + 
                          COALESCE(project_evaluation_overall_score, 0)) / 4), 2) as average_score,
                MIN((COALESCE(project_evaluation_content_score, 0) + 
                    COALESCE(project_evaluation_organization_score, 0) + 
                    COALESCE(project_evaluation_instructor_score, 0) + 
                    COALESCE(project_evaluation_overall_score, 0)) / 4) as min_score,
                MAX((COALESCE(project_evaluation_content_score, 0) + 
                    COALESCE(project_evaluation_organization_score, 0) + 
                    COALESCE(project_evaluation_instructor_score, 0) + 
                    COALESCE(project_evaluation_overall_score, 0)) / 4) as max_score
            FROM 
                project_evaluation
            WHERE 
                project_id = %s
        """, (project_id,))
        summary = cursor.fetchone()
        
        if summary:
            evaluation_dict = {
                "total_evaluations": int(summary[0]),
                "average_score": float(summary[1] or 0),
                "min_score": float(summary[2] or 0),
                "max_score": float(summary[3] or 0)
            }
        else:
            evaluation_dict = {
                "total_evaluations": 0,
                "average_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0
            }
        
        # ดึงความคิดเห็นการประเมิน
        evaluation_comments = []
        if evaluation_dict["total_evaluations"] > 0:
            cursor.execute("""
                SELECT evaluation_comments
                FROM project_evaluation
                WHERE project_id = %s AND evaluation_comments != ''
                ORDER BY evaluation_date DESC
            """, (project_id,))
            
            for row in cursor.fetchall():
                if row[0]:
                    evaluation_comments.append(row[0])
        
        # คำนวณความสำเร็จของโครงการ
        target_percentage = (participant_count / project_dict["project_target"]) * 100 if project_dict["project_target"] > 0 else 0
        satisfaction_percentage = evaluation_dict["average_score"] * 20  # แปลงจาก 0-5 เป็น 0-100
        
        project_success = {
            "score": round(satisfaction_percentage, 2),
            "level": get_success_level(satisfaction_percentage),
            "target_percentage": round(target_percentage, 2)
        }
        
    return render_template(
        "project_summary.html",
        project=project_dict,
        participant_count=participant_count,
        evaluation=evaluation_dict,
        evaluation_comments=evaluation_comments,
        project_success=project_success
    )

@app.route("/admin_project_history")
@login_required("admin")
def admin_project_history():
    if not g.user or g.user["type"] != "admin":
        return redirect(url_for("login"))

    page = request.args.get("page", 1, type=int)
    per_page = 6
    search_query = request.args.get("search", "")
    branch_filter = request.args.get("branch", "all")

    with get_db_cursor() as (db, cursor):
        # อัปเดต query ให้ใช้ summary table
        base_query = """
            SELECT p.project_id, p.project_name, p.project_year, p.project_budgettype,
                   p.project_dotime, p.project_endtime, s.project_close_date,
                   t.teacher_name, b.branch_name, 
                   CASE WHEN s.summary_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_summary,
                   ad.admin_name as approver_name
            FROM project p
            JOIN approval a ON p.project_id = a.project_id
            LEFT JOIN summary s ON p.project_id = s.project_id
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN branch b ON t.branch_id = b.branch_id
            LEFT JOIN admin ad ON a.admin_id = ad.admin_id
            WHERE a.project_statusStart = 2
        """
        
        count_query = """
            SELECT COUNT(*) 
            FROM project p
            JOIN approval a ON p.project_id = a.project_id
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN branch b ON t.branch_id = b.branch_id
            WHERE a.project_statusStart = 2
        """
        
        query_params = []
        
        if search_query:
            base_query += " AND (p.project_name LIKE %s OR t.teacher_name LIKE %s)"
            count_query += " AND (p.project_name LIKE %s OR t.teacher_name LIKE %s)"
            search_pattern = f"%{search_query}%"
            query_params.extend([search_pattern, search_pattern])
            
        if branch_filter != "all":
            base_query += " AND b.branch_id = %s"
            count_query += " AND b.branch_id = %s"
            query_params.append(branch_filter)
            
        # Count total projects
        cursor.execute(count_query, query_params)
        total_projects = cursor.fetchone()[0]
        
        # Calculate total pages
        total_pages = ceil(total_projects / per_page)
        
        # Get projects for current page
        base_query += " ORDER BY COALESCE(s.project_close_date, p.project_endtime) DESC LIMIT %s OFFSET %s"
        offset = (page - 1) * per_page
        query_params.extend([per_page, offset])
        
        cursor.execute(base_query, query_params)
        projects = cursor.fetchall()
        
        # ดึงข้อมูลสาขาทั้งหมดสำหรับตัวกรอง
        cursor.execute("SELECT branch_id, branch_name FROM branch ORDER BY branch_name")
        branches = cursor.fetchall()
        
    return render_template(
        "admin_project_history.html",
        projects=projects,
        page=page,
        total_pages=total_pages,
        search_query=search_query,
        branch_filter=branch_filter,
        branches=branches
    )


# ฟังก์ชันบันทึกข้อความสรุปโครงการ
@app.route("/save_project_summary/<int:project_id>", methods=["POST"])
@login_required("teacher")
def save_project_summary(project_id):
    if "teacher_id" not in session:
        flash("คุณไม่มีสิทธิ์ในการดำเนินการนี้", "error")
        return redirect(url_for("home"))

    teacher_id = session["teacher_id"]
    
    summary_text = request.form.get("summary_text", "")
    project_problems = request.form.get("project_problems", "")
    project_solutions = request.form.get("project_solutions", "")
    
    # ตรวจสอบรูปแบบข้อมูล
    if not isinstance(summary_text, str):
        summary_text = str(summary_text) if summary_text is not None else ""
    if not isinstance(project_problems, str):
        project_problems = str(project_problems) if project_problems is not None else ""
    if not isinstance(project_solutions, str):
        project_solutions = str(project_solutions) if project_solutions is not None else ""
    
    # ป้องกันการบันทึกข้อมูลไม่ถูกต้อง
    if any(timestamp in project_problems for timestamp in 
          ["2025-", "2024-", "2023-", "2022-", "2021-"]):
        project_problems = ""
    
    if any(timestamp in project_solutions for timestamp in 
          ["2025-", "2024-", "2023-", "2022-", "2021-"]):
        project_solutions = ""
    
    with get_db_cursor() as (db, cursor):
        # ตรวจสอบว่าเป็นโครงการของอาจารย์คนนี้หรือไม่
        cursor.execute(
            "SELECT project_id FROM project WHERE project_id = %s AND teacher_id = %s",
            (project_id, teacher_id),
        )
        project = cursor.fetchone()
        
        if not project:
            flash("คุณไม่มีสิทธิ์จัดการโครงการนี้", "error")
            return redirect(url_for("teacher_projects"))
        
        try:
            # ตรวจสอบว่ามีระเบียนใน summary หรือยัง
            cursor.execute("SELECT summary_id FROM summary WHERE project_id = %s", (project_id,))
            summary_exists = cursor.fetchone()
            
            if summary_exists:
                # อัปเดตข้อมูลที่มีอยู่
                cursor.execute(
                    """UPDATE summary 
                       SET summary_text = %s, project_problems = %s, project_solutions = %s
                       WHERE project_id = %s""",
                    (summary_text, project_problems, project_solutions, project_id)
                )
            else:
                # สร้างระเบียนใหม่
                cursor.execute(
                    """INSERT INTO summary (project_id, summary_text, project_problems, project_solutions, project_close_date)
                       VALUES (%s, %s, %s, %s, NOW())""",
                    (project_id, summary_text, project_problems, project_solutions)
                )
            
            db.commit()
            
            # สร้าง PDF ทันทีหลังจากบันทึกข้อความ
            pdf_created = generate_summary_pdf(project_id)
            
            if pdf_created:
                flash("บันทึกสรุปรายงานและสร้าง PDF เรียบร้อยแล้ว", "success")
                return redirect(url_for("download_summary_pdf", project_id=project_id))
            else:
                flash("บันทึกข้อความสรุปเรียบร้อยแล้ว แต่ไม่สามารถสร้าง PDF ได้", "warning")
                return redirect(url_for("project_summary", project_id=project_id))
        except Exception as err:
            flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {err}", "error")
            return redirect(url_for("project_summary", project_id=project_id))
def generate_summary_pdf(project_id):
    """สร้าง PDF สรุปผลการดำเนินโครงการ (รูปแบบใหม่ตามไฟล์ตัวอย่าง)"""
    try:
        from reportlab.platypus import PageBreak
        
        # ดึงข้อมูลโครงการจากตารางใหม่
        with get_db_cursor() as (db, cursor):
            cursor.execute("""
                SELECT p.project_id, p.project_name, p.project_budgettype, p.project_year, 
                       p.project_style, p.project_address, p.project_dotime, p.project_endtime, 
                       p.project_target, p.project_budget, p.project_detail,
                       t.teacher_name, b.branch_name,
                       a.project_status, a.project_statusStart, a.project_submit_date, 
                       a.project_approve_date, s.project_close_date, s.summary_text,
                       s.project_problems, s.project_solutions,
                       p.project_objectives, p.project_output_target, p.project_outcome_target
                FROM project p
                JOIN teacher t ON p.teacher_id = t.teacher_id
                JOIN branch b ON t.branch_id = b.branch_id
                JOIN approval a ON p.project_id = a.project_id
                LEFT JOIN summary s ON p.project_id = s.project_id
                WHERE p.project_id = %s
            """, (project_id,))
            
            project = cursor.fetchone()
            
            if not project:
                logging.error(f"ไม่พบข้อมูลโครงการ ID: {project_id}")
                return False
            
            # ดึงข้อมูลผู้เข้าร่วม
            cursor.execute("""
                SELECT COUNT(*) as approved_count
                FROM status_register 
                WHERE project_id = %s AND status_register = 1
            """, (project_id,))
            participant_count = int(cursor.fetchone()[0])
            
            # ดึงข้อมูลการประเมิน - แก้ไขให้ไม่ใช้ evaluation_score
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_evaluations,
                    ROUND(AVG((COALESCE(project_evaluation_content_score, 0) + 
                              COALESCE(project_evaluation_organization_score, 0) + 
                              COALESCE(project_evaluation_instructor_score, 0) + 
                              COALESCE(project_evaluation_overall_score, 0)) / 4), 2) as average_score
                FROM 
                    project_evaluation
                WHERE 
                    project_id = %s
            """, (project_id,))
            evaluation_summary = cursor.fetchone()
        
        # แยกข้อมูลจาก tuple
        project_name = project[1]
        project_budgettype = project[2]
        project_year = project[3]
        project_style = project[4]
        project_address = project[5]
        project_dotime = project[6]
        project_endtime = project[7]
        project_target = int(project[8]) if project[8] is not None else 0
        project_budget = float(project[9]) if project[9] is not None else 0
        teacher_name = project[11]
        branch_name = project[12]
        project_close_date = project[17]
        summary_text = project[18] if project[18] else ""
        project_problems = project[19] if project[19] else ""
        project_solutions = project[20] if project[20] else ""
        
        # ข้อมูลเพิ่มเติม
        project_objectives = project[21] if len(project) > 21 and project[21] else ""
        project_output_target = project[22] if len(project) > 22 and project[22] else ""
        project_outcome_target = project[23] if len(project) > 23 and project[23] else ""
        
        # ตรวจสอบความถูกต้องของชื่ออาจารย์และสาขา
        if (not teacher_name or 
            not isinstance(teacher_name, str) or 
            teacher_name.strip() == "" or
            teacher_name in ["dsadad", "test", "ไม่ระบุชื่อ"] or 
            len(teacher_name.strip()) < 2 or 
            teacher_name.isdigit()):
            
            with get_db_cursor() as (db, cursor):
                cursor.execute("SELECT teacher_name FROM teacher WHERE teacher_id = (SELECT teacher_id FROM project WHERE project_id = %s)", (project_id,))
                teacher_result = cursor.fetchone()
                if teacher_result and teacher_result[0] and teacher_result[0].strip():
                    teacher_name = teacher_result[0].strip()
                else:
                    teacher_name = "ผู้รับผิดชอบโครงการ"
        
        if not branch_name or not isinstance(branch_name, str) or branch_name.isdigit() or len(branch_name) < 2:
            with get_db_cursor() as (db, cursor):
                cursor.execute("""
                    SELECT b.branch_name 
                    FROM branch b 
                    JOIN teacher t ON b.branch_id = t.branch_id 
                    JOIN project p ON t.teacher_id = p.teacher_id
                    WHERE p.project_id = %s
                """, (project_id,))
                branch_result = cursor.fetchone()
                if branch_result and branch_result[0]:
                    branch_name = branch_result[0]
                else:
                    branch_name = "ไม่ระบุสาขา"
        
        # สร้าง PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=30,
            leftMargin=30,
            topMargin=70,
            bottomMargin=30,
        )

        # ลงทะเบียนฟอนต์ไทย
        font_path = os.path.join(os.path.dirname(__file__), "THSarabunNew.ttf")
        bold_font_path = os.path.join(os.path.dirname(__file__), "THSarabunNew-Bold.ttf")
        pdfmetrics.registerFont(TTFont("THSarabunNew", font_path))
        pdfmetrics.registerFont(TTFont("THSarabunNew-Bold", bold_font_path))

        # สร้างสไตล์
        normal_style = ParagraphStyle(
            'Normal',
            fontName='THSarabunNew',
            fontSize=14,
            leading=18,
            spaceBefore=4,
            spaceAfter=4
        )
        
        heading_style = ParagraphStyle(
            'Heading',
            fontName='THSarabunNew-Bold',
            fontSize=16,
            leading=20,
            alignment=1,
            spaceAfter=8
        )
        
        table_header_style = ParagraphStyle(
            'TableHeader',
            fontName='THSarabunNew-Bold',
            fontSize=14,
            alignment=1,
            spaceBefore=4,
            spaceAfter=4
        )
        
        table_item_style = ParagraphStyle(
            'TableItem',
            fontName='THSarabunNew',
            fontSize=14,
            spaceBefore=4,
            spaceAfter=4,
            alignment=1
        )
        
        table_item_left_style = ParagraphStyle(
            'TableItemLeft',
            fontName='THSarabunNew',
            fontSize=14,
            spaceBefore=4,
            spaceAfter=4,
            alignment=0
        )

        def header(canvas, doc):
            canvas.saveState()
            canvas.setFont('THSarabunNew', 12)
            today = datetime.now().strftime("%d/%m/%Y")
            canvas.drawRightString(doc.pagesize[0] - 40, doc.pagesize[1] - 40, f"พิมพ์เมื่อ: {today}")
            canvas.setFont('THSarabunNew', 12)
            canvas.drawRightString(doc.pagesize[0] - 40, 30, f"หน้า {canvas.getPageNumber()}")
            
            if canvas.getPageNumber() == 1:
                logo_path = os.path.join(app.static_folder, "2.png")
                if os.path.exists(logo_path):
                    try:
                        img = Image.open(logo_path)
                        img = img.convert("RGB")
                        img_buffer = BytesIO()
                        img.save(img_buffer, format="PNG")
                        img_buffer.seek(0)

                        logo_width = 1 * inch
                        logo_height = 1 * inch
                        page_width = doc.pagesize[0]
                        page_center = page_width / 2
                        
                        canvas.drawImage(
                            ImageReader(img_buffer),
                            page_center - (logo_width/2),
                            doc.pagesize[1] - 130,
                            width=logo_width,
                            height=logo_height,
                            mask='auto'
                        )
                    except Exception as e:
                        logging.error(f"Error loading logo: {e}")
                
                canvas.setFont('THSarabunNew-Bold', 20)
                canvas.drawCentredString(
                    page_center,
                    doc.pagesize[1] - 175,
                    "บันทึกข้อความ"
                )
            
            canvas.restoreState()

        content = []
        content.append(Spacer(1, 120))
        
        # สร้างเนื้อหา PDF - หน้าแรก
        project_date_format = ""
        try:
            if isinstance(project_dotime, datetime):
                project_dotime_str = project_dotime.strftime('%d/%m/%Y')
                project_endtime_str = project_endtime.strftime('%d/%m/%Y')
                project_date_format = f"{project_dotime_str} ถึง {project_endtime_str}"
            else:
                project_date_format = f"{project_dotime} ถึง {project_endtime}"
        except:
            project_date_format = "ไม่ระบุ"
        
        # ส่วนงานภายใน
        content.append(Paragraph(f"<b>ส่วนงานภายใน</b> สาขา/แผนก {branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ โทร. (IP) ................", normal_style))
        
        # วันที่
        today = datetime.now()
        thai_month = [
            "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
            "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
        ]
        thai_year = today.year + 543
        
        content.append(Paragraph(f"<b>ที่</b> มทร.อีสาน 34............/ <b>วันที่</b> {today.day} {thai_month[today.month-1]} {thai_year}", normal_style))
        content.append(Paragraph("<b>เรื่อง</b> ขอส่งรายงานผลการดำเนินโครงการ", normal_style))
        content.append(Paragraph("<b>เรียน</b> คณบดีคณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ", normal_style))
        content.append(Spacer(1, 15))
        
        # เนื้อหาหลัก
        main_text = f"""        ตามที่ สาขา/แผนก {branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ ได้ดำเนินโครงการ{project_name} งบประมาณ{project_budgettype} (ในแผน) ประจำปีงบประมาณ พ.ศ. {project_year} จำนวนเงิน {'{:,.2f}'.format(project_budget)} บาท ({thai_money_text(project_budget)}) วันที่{project_date_format} ณ {project_address}
        
        ในการนี้ สาขา/แผนก {branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ ได้ดำเนินโครงการเสร็จเป็นที่เรียบร้อยแล้ว จึงขอนำส่งรายงานสรุปผลประเมินความสำเร็จตามวัตถุประสงค์ของแผนการจัดกิจกรรมตามผลผลิต โดยมีรายละเอียดดังเอกสารแนบ"""
        content.append(Paragraph(main_text, normal_style))
        
        # คำนวณผลการดำเนินงาน
        target_percentage = (participant_count / project_target) * 100 if project_target > 0 else 0
        average_score = float(evaluation_summary[1] or 0) if evaluation_summary else 0
        satisfaction_percentage = average_score * 20
        
        # สร้างตารางสรุป
        target_percent = '{:.1f}'.format(target_percentage)
        satisfaction_percent = '{:.1f}'.format(satisfaction_percentage)
        
        data = [
            [Paragraph("<b>ตัวชี้วัด</b>", table_header_style), 
             Paragraph("<b>หน่วยนับ</b>", table_header_style), 
             Paragraph("<b>แผน</b>", table_header_style), 
             Paragraph("<b>ผลดำเนินงาน</b>", table_header_style),
             Paragraph("<b>สรุปผล</b>", table_header_style)],
             
            [Paragraph("<b>เชิงปริมาณ</b>", table_header_style), "", "", "", ""],
            
            [Paragraph(f"ผู้เข้าร่วมโครงการจำนวน {project_target} คน", table_item_left_style),
             Paragraph("คน", table_item_style),
             Paragraph(f"{project_target}", table_item_style),
             Paragraph(f"{participant_count}", table_item_style),
             Paragraph("บรรลุ" if target_percentage >= 80 else "ไม่บรรลุ", table_item_style)],
             
            [Paragraph(f"จำนวนผู้เข้าร่วมโครงการไม่ต่ำกว่าร้อยละ 80", table_item_left_style),
             Paragraph("ร้อยละ", table_item_style),
             Paragraph("80", table_item_style),
             Paragraph(f"{target_percent}", table_item_style),
             Paragraph("บรรลุ" if target_percentage >= 80 else "ไม่บรรลุ", table_item_style)],
             
            [Paragraph("<b>เชิงคุณภาพ</b>", table_header_style), "", "", "", ""],
            
            [Paragraph(f"ผู้เข้าร่วมโครงการมีความพึงพอใจไม่ต่ำกว่าร้อยละ 75%", table_item_left_style),
             Paragraph("ร้อยละ", table_item_style),
             Paragraph("75", table_item_style),
             Paragraph(f"{satisfaction_percent}", table_item_style),
             Paragraph("บรรลุ" if average_score >= 3.5 else "ไม่บรรลุ", table_item_style)],
             
            [Paragraph("รายงานผลการดำเนินโครงการ 1 ชุด", table_item_left_style),
             Paragraph("ชุด", table_item_style),
             Paragraph("1", table_item_style),
             Paragraph("1", table_item_style),
             Paragraph("บรรลุ", table_item_style)],
             
            [Paragraph("<b>เชิงเวลา</b>", table_header_style), "", "", "", ""],
            
            [Paragraph("โครงการแล้วเสร็จตามระยะเวลาที่กำหนด ไม่ต่ำกว่าร้อยละ 100", table_item_left_style),
             Paragraph("ร้อยละ", table_item_style),
             Paragraph("100", table_item_style),
             Paragraph("100", table_item_style),
             Paragraph("บรรลุ", table_item_style)],
             
            [Paragraph("<b>เชิงค่าใช้จ่าย</b>", table_header_style), "", "", "", ""],
            
            [Paragraph(f"งบประมาณที่ใช้ดำเนินโครงการ {'{:,.2f}'.format(project_budget)} บาท", table_item_left_style),
             Paragraph("บาท", table_item_style),
             Paragraph(f"{'{:,.2f}'.format(project_budget)}", table_item_style),
             Paragraph(f"{'{:,.2f}'.format(project_budget)}", table_item_style),
             Paragraph("บรรลุ", table_item_style)]
        ]
        
        col_widths = [200, 70, 70, 100, 70]
        summary_table = Table(data, colWidths=col_widths)
        
        summary_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('BACKGROUND', (0, 1), (0, 1), colors.lightgrey),
            ('BACKGROUND', (0, 4), (0, 4), colors.lightgrey),
            ('BACKGROUND', (0, 7), (0, 7), colors.lightgrey),
            ('BACKGROUND', (0, 9), (0, 9), colors.lightgrey),
            ('SPAN', (1, 1), (4, 1)),
            ('SPAN', (1, 4), (4, 4)),
            ('SPAN', (1, 7), (4, 7)),
            ('SPAN', (1, 9), (4, 9)),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        
        content.append(Spacer(1, 6))
        content.append(summary_table)
        content.append(Spacer(1, 6))
        
        # ลงชื่อ
        content.append(Paragraph("จึงเรียนมาเพื่อโปรดพิจารณา", normal_style))
        content.append(Spacer(1, 15))
        content.append(Paragraph(f"({teacher_name})", normal_style))
        content.append(Paragraph("ผู้รับผิดชอบโครงการ", normal_style))
        
        # หน้าใหม่สำหรับรายงานสรุปผล - รูปแบบใหม่
        content.append(PageBreak())
        
        # หัวรายงานสรุปผล
        content.append(Paragraph(f"<b>ชื่อโครงการ :</b> {project_name}", normal_style))
        content.append(Paragraph(f"<b>สาขา :</b> {branch_name} <b>งบประมาณ{project_budgettype}</b> ประจำปีงบประมาณ {project_year}", normal_style))
        content.append(Paragraph(f"<b>ระยะเวลา</b> วันที่{project_date_format} <b>สถานที่</b> ณ {project_address}", normal_style))
        content.append(Paragraph(f"<b>ผู้รับผิดชอบ</b> ชื่อ{teacher_name}", normal_style))
        content.append(Spacer(1, 12))
        
        # เพิ่มส่วนวัตถุประสงค์
        content.append(Paragraph(f"<b>วัตถุประสงค์ :</b> {project_objectives if project_objectives else 'ไม่มีข้อมูล'}", normal_style))
        content.append(Spacer(1, 6))
        
        # เพิ่มส่วนเป้าหมาย
        content.append(Paragraph(f"<b>เป้าหมายเชิงผลผลิต (Output) :</b> {project_output_target if project_output_target else 'ไม่มีข้อมูล'}", normal_style))
        content.append(Spacer(1, 6))
        content.append(Paragraph(f"<b>เป้าหมายเชิงผลลัพธ์ (Outcome) :</b> {project_outcome_target if project_outcome_target else 'ไม่มีข้อมูล'}", normal_style))
        content.append(Spacer(1, 12))
        
        # ตารางตัวบ่งชี้แบบใหม่ (ตามไฟล์ตัวอย่าง)
        indicator_data = [
            [Paragraph("<b>ตัวบ่งชี้</b>", table_header_style), 
             Paragraph("<b>ค่าเป้าหมาย</b>", table_header_style), 
             Paragraph("<b>บรรลุ (/ / X)</b>", table_header_style)],
             
            [Paragraph("<b>เชิงปริมาณ :</b>", table_item_left_style), 
             Paragraph(f"{project_target}", table_item_style),
             Paragraph("/" if target_percentage >= 80 else "X", table_item_style)],
             
            [Paragraph(f"- ผู้เข้าร่วมโครงการจำนวน {project_target} คน", table_item_left_style),
             Paragraph(f"{project_target}", table_item_style),
             Paragraph("/" if participant_count >= project_target else "X", table_item_style)],
             
            [Paragraph("- จำนวนโครงการที่ได้ดำเนินการ", table_item_left_style),
             Paragraph("1", table_item_style),
             Paragraph("/", table_item_style)],
             
            [Paragraph("<b>เชิงคุณภาพ :</b>", table_item_left_style), "", ""],
            
            [Paragraph("- ร้อยละของผู้เข้าร่วมโครงการ", table_item_left_style),
             Paragraph("75%", table_item_style),
             Paragraph("/" if satisfaction_percentage >= 75 else "X", table_item_style)],
             
            [Paragraph("- พึงพอใจของผู้เข้าร่วมโครงการ", table_item_left_style),
             Paragraph(f"{average_score:.1f}/5", table_item_style),
             Paragraph("/" if average_score >= 3.5 else "X", table_item_style)],
             
            [Paragraph("<b>เชิงเวลา :</b>", table_item_left_style), "", ""],
            
            [Paragraph("- โครงการแล้วเสร็จตามระยะเวลาที่กำหนด", table_item_left_style),
             Paragraph("100%", table_item_style),
             Paragraph("/", table_item_style)],
             
            [Paragraph(f"<b>เชิงค่าใช้จ่าย :</b> {'{:,.0f}'.format(project_budget)} บาท", table_item_left_style), 
             Paragraph("/", table_item_style), ""],
             
            [Paragraph(f"- งบประมาณที่ใช้ในการดำเนินโครงการ {'{:,.2f}'.format(project_budget)} บาท", table_item_left_style),
             "", ""]
        ]
        
        indicator_table = Table(indicator_data, colWidths=[300, 100, 100])
        indicator_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            # รวมเซลล์สำหรับแถวที่ 10 และ 11
            ('SPAN', (1, 9), (2, 9)),  # แถวเชิงค่าใช้จ่าย
            ('SPAN', (1, 10), (2, 10)),  # แถวรายละเอียดงบประมาณ
        ]))
        
        content.append(indicator_table)
        content.append(Spacer(1, 12))
        
        # ตารางปัญหาและแนวทางแก้ไข
        if project_problems and any(timestamp in project_problems for timestamp in 
                                  ["2025-", "2024-", "2023-", "2022-", "2021-"]):
            project_problems = "ไม่มีข้อมูล"
        
        if project_solutions and any(timestamp in project_solutions for timestamp in 
                                   ["2025-", "2024-", "2023-", "2022-", "2021-"]):
            project_solutions = "ไม่มีข้อมูล"
        
        if not project_problems:
            project_problems = "ไม่มีข้อมูล"
        if not project_solutions:
            project_solutions = "ไม่มีข้อมูล"
        
        problem_data = [
            [Paragraph("<b>ปัญหา :</b>", normal_style), ""],
            [Paragraph(project_problems, normal_style), ""],
            [Paragraph("<b>แนวทางแก้ไข :</b>", normal_style), ""],
            [Paragraph(project_solutions, normal_style), ""]
        ]
        
        problem_table = Table(problem_data, colWidths=[520, 30])
        problem_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('SPAN', (0, 0), (1, 0)),
            ('SPAN', (0, 1), (1, 1)),
            ('SPAN', (0, 2), (1, 2)),
            ('SPAN', (0, 3), (1, 3)),
        ]))
        
        content.append(Paragraph("<b>ปัญหาและแนวทางแก้ไข</b>", heading_style))
        content.append(problem_table)
        content.append(Spacer(1, 12))
        
        # สรุปข้อมูลจากผู้ใช้ (ถ้ามี)
        if summary_text:
            content.append(PageBreak())
            content.append(Paragraph("<b>สรุปผลการดำเนินโครงการ</b>", heading_style))
            content.append(Spacer(1, 10))
            
            paragraphs = summary_text.split('\n')
            for para in paragraphs:
                if para.strip():
                    content.append(Paragraph(para, normal_style))
        
        try:
            doc.build(content, onFirstPage=header, onLaterPages=header)
            buffer.seek(0)
            
            # บันทึก PDF ลงตาราง summary
            with get_db_cursor() as (db, cursor):
                # ตรวจสอบว่ามีระเบียนใน summary หรือยัง
                cursor.execute("SELECT summary_id FROM summary WHERE project_id = %s", (project_id,))
                summary_exists = cursor.fetchone()
                
                if summary_exists:
                    # อัปเดต PDF ที่มีอยู่
                    cursor.execute("""
                        UPDATE summary 
                        SET summary_pdf = %s
                        WHERE project_id = %s
                    """, (buffer.getvalue(), project_id))
                else:
                    # สร้างระเบียนใหม่พร้อม PDF
                    cursor.execute("""
                        INSERT INTO summary (project_id, summary_pdf, project_close_date)
                        VALUES (%s, %s, NOW())
                    """, (project_id, buffer.getvalue()))
                
                db.commit()
                
            return True
        except Exception as e:
            logging.error(f"Error building PDF: {e}", exc_info=True)
            return False
            
    except Exception as e:
        logging.error(f"Error creating summary PDF: {e}", exc_info=True)
        return False
def thai_money_text(amount):
    """แปลงตัวเลขเป็นคำอ่านจำนวนเงินภาษาไทย"""
    # ตัดทศนิยมให้เหลือ 2 ตำแหน่ง
    amount = round(amount, 2)
    
    # แยกจำนวนเต็มกับทศนิยม
    integer_part = int(amount)
    decimal_part = int(round((amount - integer_part) * 100))
    
    # ถ้าไม่มีทศนิยม
    if decimal_part == 0:
        return f"{num_to_thai_text(integer_part)}บาทถ้วน"
    else:
        return f"{num_to_thai_text(integer_part)}บาท{num_to_thai_text(decimal_part)}สตางค์"

def num_to_thai_text(number):
    """แปลงตัวเลขเป็นคำอ่านภาษาไทย"""
    # ตัวเลขเป็นคำอ่าน
    thai_numbers = ["", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
    thai_units = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน", "ล้าน"]
    
    if number == 0:
        return "ศูนย์"
    
    # แปลงเป็นข้อความ
    text = ""
    unit_count = 0
    
    while number > 0:
        digit = number % 10
        
        if digit == 1 and unit_count == 1:  # เลข 1 หลักสิบ อ่านว่า สิบ (ไม่ใช่ หนึ่งสิบ)
            text = "สิบ" + text
        elif digit == 2 and unit_count == 1:  # เลข 2 หลักสิบ อ่านว่า ยี่สิบ (ไม่ใช่ สองสิบ)
            text = "ยี่สิบ" + text
        elif digit != 0:  # ถ้าไม่ใช่เลข 0 ให้เติมคำอ่านและหน่วย
            text = thai_numbers[digit] + thai_units[unit_count] + text
        
        number //= 10
        unit_count += 1
        # รีเซ็ตหน่วยเมื่อถึงล้าน
        if unit_count == 7:
            unit_count = 1
    
    return text
@app.route('/cleanup_database')
@login_required("admin")
def cleanup_database():
    """
    ล้างข้อมูลที่ไม่ถูกต้องในฐานข้อมูล
    เฉพาะแอดมินเท่านั้นที่สามารถใช้ได้
    """
    result = {
        "status": "success",
        "messages": []
    }
    
    try:
        with get_db_cursor() as (db, cursor):
            # 1. แก้ไขข้อมูล project_problems ที่เป็น datetime
            cursor.execute("""
                SELECT project_id, project_problems 
                FROM project 
                WHERE project_problems IS NOT NULL
            """)
            
            for row in cursor.fetchall():
                project_id, problems = row
                if isinstance(problems, datetime):
                    # ล้างข้อมูลที่เป็น datetime
                    cursor.execute("""
                        UPDATE project 
                        SET project_problems = NULL 
                        WHERE project_id = %s
                    """, (project_id,))
                    result["messages"].append(f"ล้างข้อมูลปัญหาของโครงการ ID {project_id}")
                elif isinstance(problems, str):
                    # ตรวจสอบว่าเป็นรูปแบบ timestamp หรือไม่
                    if any(timestamp in problems for timestamp in 
                         ["2025-", "2024-", "2023-", "2022-", "2021-"]):
                        cursor.execute("""
                            UPDATE project 
                            SET project_problems = NULL 
                            WHERE project_id = %s
                        """, (project_id,))
                        result["messages"].append(f"ล้างข้อมูลปัญหาของโครงการ ID {project_id} (timestamp)")
            
            # 2. แก้ไขข้อมูล project_solutions ที่เป็น datetime
            cursor.execute("""
                SELECT project_id, project_solutions 
                FROM project 
                WHERE project_solutions IS NOT NULL
            """)
            
            for row in cursor.fetchall():
                project_id, solutions = row
                if isinstance(solutions, datetime):
                    # ล้างข้อมูลที่เป็น datetime
                    cursor.execute("""
                        UPDATE project 
                        SET project_solutions = NULL 
                        WHERE project_id = %s
                    """, (project_id,))
                    result["messages"].append(f"ล้างข้อมูลวิธีแก้ไขของโครงการ ID {project_id}")
                elif isinstance(solutions, str):
                    # ตรวจสอบว่าเป็นรูปแบบ timestamp หรือไม่
                    if any(timestamp in solutions for timestamp in 
                         ["2025-", "2024-", "2023-", "2022-", "2021-"]):
                        cursor.execute("""
                            UPDATE project 
                            SET project_solutions = NULL 
                            WHERE project_id = %s
                        """, (project_id,))
                        result["messages"].append(f"ล้างข้อมูลวิธีแก้ไขของโครงการ ID {project_id} (timestamp)")
            
            # 3. แก้ไขชื่ออาจารย์ไม่ถูกต้อง
            cursor.execute("""
                SELECT p.project_id, p.teacher_id, t.teacher_name
                FROM project p
                JOIN teacher t ON p.teacher_id = t.teacher_id
            """)
            
            for row in cursor.fetchall():
                project_id, teacher_id, teacher_name = row
                if teacher_name in ["dsadad", "test"] or len(teacher_name) < 3:
                    # ชื่ออาจารย์ไม่ถูกต้อง
                    result["messages"].append(f"พบชื่ออาจารย์ไม่ถูกต้อง: {teacher_name} (teacher_id: {teacher_id})")
            
            db.commit()
            result["messages"].append("การล้างข้อมูลเสร็จสมบูรณ์")
            
    except Exception as e:
        result["status"] = "error"
        result["messages"].append(f"เกิดข้อผิดพลาด: {str(e)}")
        
    return jsonify(result)
# Route สำหรับดาวน์โหลด PDF สรุปผลการดำเนินโครงการ
@app.route("/download_summary_pdf/<int:project_id>")
@login_required("teacher", "admin")
def download_summary_pdf(project_id):
    try:
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูล PDF จากตาราง summary
            if g.user["type"] == "teacher":
                query = """
                    SELECT p.project_name, s.summary_pdf 
                    FROM project p
                    JOIN summary s ON p.project_id = s.project_id
                    WHERE p.project_id = %s AND p.teacher_id = %s
                """
                cursor.execute(query, (project_id, g.user["id"]))
            else:  # admin
                query = """
                    SELECT p.project_name, s.summary_pdf 
                    FROM project p
                    JOIN summary s ON p.project_id = s.project_id
                    WHERE p.project_id = %s
                """
                cursor.execute(query, (project_id,))
                
            result = cursor.fetchone()
            
            if not result or not result[1]:  # ไม่พบข้อมูลหรือไม่มี PDF
                # พยายามสร้าง PDF ใหม่
                pdf_created = generate_summary_pdf(project_id)
                
                if pdf_created:
                    # ดึงข้อมูล PDF ที่เพิ่งสร้าง
                    cursor.execute(
                        "SELECT p.project_name, s.summary_pdf FROM project p JOIN summary s ON p.project_id = s.project_id WHERE p.project_id = %s",
                        (project_id,)
                    )
                    result = cursor.fetchone()
                
                if not result or not result[1]:
                    flash("ไม่พบไฟล์ PDF สรุปสำหรับโครงการนี้", "error")
                    return redirect(url_for("project_summary", project_id=project_id))
                    
            project_name, pdf_content = result
            
            safe_filename = f"project_summary_{project_id}.pdf"
            
            response = make_response(pdf_content)
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename="{safe_filename}"'
            return response
            
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการดาวน์โหลดไฟล์: {str(e)}", "error")
        return redirect(url_for("project_summary", project_id=project_id))
@app.route("/project_history")
@login_required("teacher")
def project_history():
    if "teacher_id" not in session:
        return redirect(url_for("login"))

    teacher_id = session["teacher_id"]
    page = request.args.get("page", 1, type=int)
    per_page = 6

    with get_db_cursor() as (db, cursor):
        # นับจำนวนโปรเจคที่ปิดแล้วทั้งหมด
        cursor.execute(
            """SELECT COUNT(*) 
               FROM project p
               JOIN approval a ON p.project_id = a.project_id
               WHERE p.teacher_id = %s AND a.project_statusStart = 2""", 
            (teacher_id,)
        )
        total_projects = cursor.fetchone()[0]

        # คำนวณจำนวนหน้าทั้งหมด
        total_pages = ceil(total_projects / per_page)

        # ดึงข้อมูลโปรเจคตามหน้าที่ต้องการ - อัปเดตให้ใช้ summary table
        offset = (page - 1) * per_page
        query = """
            SELECT p.project_id, p.project_name, a.project_status, a.project_statusStart, 
                   CASE WHEN s.summary_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_pdf,
                   p.project_dotime, p.project_endtime, s.project_close_date
            FROM project p
            JOIN approval a ON p.project_id = a.project_id
            LEFT JOIN summary s ON p.project_id = s.project_id
            WHERE p.teacher_id = %s AND a.project_statusStart = 2
            ORDER BY COALESCE(s.project_close_date, p.project_endtime) DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, (teacher_id, per_page, offset))
        completed_projects = cursor.fetchall()

    return render_template(
        "project_history.html",
        projects=completed_projects,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )
@app.route("/evaluate_project/<int:project_id>", methods=["GET", "POST"])
def evaluate_project(project_id):
    if 'user_type' not in session or session['user_type'] != 'student':
        flash('คุณต้องล็อกอินด้วยบัญชีนักศึกษาก่อน', 'error')
        return redirect(url_for('login'))
    
    student_id = session.get('student_id')  # รหัสบัตรนักศึกษา
    student_name = session.get('student_name')
    
    with get_db_cursor() as (db, cursor):
        # ตรวจสอบโครงการและสิทธิ์
        cursor.execute("""
            SELECT p.project_name, a.project_statusStart
            FROM project p 
            JOIN approval a ON p.project_id = a.project_id
            WHERE p.project_id = %s
        """, (project_id,))
        project = cursor.fetchone()
        
        if not project:
            flash('ไม่พบโครงการ', 'error')
            return redirect(url_for('student_dashboard'))
        
        project_name = project[0]
        project_status = project[1]
        
        if project_status != 2:
            flash('โครงการยังไม่เสร็จสิ้น ไม่สามารถประเมินได้', 'warning')
            return redirect(url_for('student_dashboard'))
        
        # ตรวจสอบสิทธิ์การประเมิน
        cursor.execute("""
            SELECT sr.join_id 
            FROM status_register sr
            WHERE sr.project_id = %s 
            AND sr.status_register = 1 
            AND sr.join_id = %s
        """, (project_id, student_id))
        participant = cursor.fetchone()
        
        if not participant:
            flash('คุณไม่มีสิทธิ์ประเมินโครงการนี้', 'error')
            return redirect(url_for('student_dashboard'))
        
        # ตรวจสอบว่าประเมินแล้วหรือยัง
        cursor.execute("""
            SELECT COUNT(*) FROM project_evaluation 
            WHERE project_id = %s AND join_id = %s
        """, (project_id, student_id))
        already_evaluated = cursor.fetchone()[0] > 0
        
        if already_evaluated:
            flash('คุณได้ประเมินโครงการนี้ไปแล้ว', 'warning')
            return redirect(url_for('student_dashboard'))
        
        if request.method == "POST":
            try:
                # รับคะแนนจากแต่ละคำถาม
                detailed_scores = {}
                category_scores = {
                    'content': [],
                    'organization': [],
                    'instructor': [],
                    'overall': []
                }
                
                # ดึงคำถามทั้งหมด
                cursor.execute("""
                    SELECT system_constants_id, system_constants_question_category
                    FROM system_constants
                    WHERE system_constants_is_active = TRUE
                    ORDER BY system_constants_question_order
                """)
                active_questions = cursor.fetchall()
                
                total_score = 0
                question_count = 0
                
                for question_id, category in active_questions:
                    score_key = f'question_{question_id}'
                    score = request.form.get(score_key)
                    
                    if score:
                        score = int(score)
                        detailed_scores[score_key] = score
                        category_scores[category].append(score)
                        total_score += score
                        question_count += 1
                
                # คำนวณคะแนนเฉลี่ยตามหมวดหมู่
                content_avg = sum(category_scores['content']) / len(category_scores['content']) if category_scores['content'] else 0
                organization_avg = sum(category_scores['organization']) / len(category_scores['organization']) if category_scores['organization'] else 0
                instructor_avg = sum(category_scores['instructor']) / len(category_scores['instructor']) if category_scores['instructor'] else 0
                overall_avg = sum(category_scores['overall']) / len(category_scores['overall']) if category_scores['overall'] else 0
                
                evaluation_comments = request.form.get('evaluation_comments', '')
                detailed_scores_json = json.dumps(detailed_scores)
                
                # บันทึกการประเมิน - ลบ evaluation_score ออก
                cursor.execute("""
                    INSERT INTO project_evaluation 
                    (project_id, join_id, evaluation_comments, 
                     project_evaluation_content_score, project_evaluation_organization_score,
                     project_evaluation_instructor_score, project_evaluation_overall_score,
                     project_evaluation_detailed_scores, evaluation_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (project_id, student_id, evaluation_comments,
                     content_avg, organization_avg, instructor_avg, overall_avg,
                     detailed_scores_json))
                db.commit()
                
                flash('ขอบคุณสำหรับการประเมินโครงการ', 'success')
                return redirect(url_for('student_dashboard'))
                
            except Exception as e:
                flash(f'เกิดข้อผิดพลาดในการบันทึกข้อมูล: {str(e)}', 'error')
        
        # ดึงคำถามสำหรับแสดงในฟอร์ม
        cursor.execute("""
            SELECT system_constants_id, system_constants_question_text, 
                   system_constants_question_category
            FROM system_constants
            WHERE system_constants_is_active = TRUE
            ORDER BY system_constants_question_order
        """)
        questions = cursor.fetchall()
        
        # จัดกลุ่มคำถามตามหมวดหมู่
        questions_by_category = {}
        for q in questions:
            category = q[2]
            if category not in questions_by_category:
                questions_by_category[category] = []
            questions_by_category[category].append({
                'id': q[0],
                'text': q[1]
            })
        
        return render_template('project_evaluation.html',
                             project_id=project_id,
                             project_name=project_name,
                             student_name=student_name,
                             questions_by_category=questions_by_category,
                             join_id=student_id)
def is_date_overlap_for_teacher(teacher_id, start_date, end_date, project_id=None):
    with get_db_cursor() as (db, cursor):
        if project_id:
            query = """
            SELECT COUNT(*) FROM project 
            WHERE teacher_id = %s 
            AND project_id != %s
            AND ((project_dotime <= %s AND project_endtime >= %s)
            OR (project_dotime <= %s AND project_endtime >= %s)
            OR (project_dotime >= %s AND project_endtime <= %s))
            """
            cursor.execute(query, (teacher_id, project_id, end_date, start_date, start_date, start_date, start_date, end_date))
        else:
            query = """
            SELECT COUNT(*) FROM project 
            WHERE teacher_id = %s 
            AND ((project_dotime <= %s AND project_endtime >= %s)
            OR (project_dotime <= %s AND project_endtime >= %s)
            OR (project_dotime >= %s AND project_endtime <= %s))
            """
            cursor.execute(query, (teacher_id, end_date, start_date, start_date, start_date, start_date, end_date))
        count = cursor.fetchone()[0]
    return count > 0
@app.route('/check_project_dates', methods=['POST'])
def check_project_dates():
    data = request.json
    teacher_id = session.get('teacher_id')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    
    overlap = is_date_overlap_for_teacher(teacher_id, start_date, end_date)
    
    return jsonify({'overlap': overlap})
@app.route('/check_project_name', methods=['POST'])
def check_project_name():
    try:
        # รับข้อมูลจาก form-data แทน JSON
        project_name = request.form.get('project_name', '')
        project_id_str = request.form.get('project_id', 'null')
        
        # แปลงค่า project_id
        if project_id_str and project_id_str != 'null' and project_id_str != 'undefined':
            try:
                project_id = int(project_id_str)
                is_duplicate = is_project_name_duplicate(project_name, project_id)
            except (ValueError, TypeError):
                is_duplicate = is_project_name_duplicate(project_name)
        else:
            is_duplicate = is_project_name_duplicate(project_name)
        
        return jsonify({'exists': bool(is_duplicate)})
    except Exception as e:
        print(f"Error in check_project_name: {e}")
        return jsonify({'exists': False, 'error': str(e)})
@app.route("/add_branch", methods=["GET", "POST"])
@login_required("admin")
def add_branch():
    if request.method == "GET":
        # ดึง branch_id ถัดไปอัตโนมัติ (รูปแบบ branch001, branch002)
        with get_db_cursor() as (db, cursor):
            try:
                # ดึง branch_id ที่มีรูปแบบ branchXXX
                cursor.execute("SELECT branch_id FROM branch WHERE branch_id LIKE 'branch%' ORDER BY branch_id DESC LIMIT 1")
                max_branch = cursor.fetchone()
                
                if max_branch:
                    # แยกเลขจาก branch001 -> 001 -> 1 -> 2 -> 002
                    current_num = int(max_branch[0].replace('branch', ''))
                    next_num = current_num + 1
                    next_id = f"branch{next_num:03d}"  # format เป็น branch001, branch002
                else:
                    next_id = "branch001"
            except:
                next_id = "branch001"
        
        return render_template("add_branch.html", next_branch_id=next_id)
    
    elif request.method == "POST":
        branch_id = request.form["branch_id"]
        branch_name = request.form["branch_name"]
        
        try:
            with get_db_cursor() as (db, cursor):
                # ตรวจสอบ branch_id ซ้ำ
                cursor.execute("SELECT COUNT(*) FROM branch WHERE branch_id = %s", (branch_id,))
                if cursor.fetchone()[0] > 0:
                    flash("รหัสสาขานี้มีอยู่แล้ว กรุณาใช้รหัสอื่น", "error")
                    return redirect(url_for("add_branch"))
                
                query = "INSERT INTO branch (branch_id, branch_name) VALUES (%s, %s)"
                cursor.execute(query, (branch_id, branch_name))
                db.commit()
                
            flash("เพิ่มข้อมูลสาขาเรียบร้อยแล้ว", "success")
            return redirect(url_for("edit_basic_info"))
            
        except Exception as e:
            flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
            return redirect(url_for("add_branch"))
# เพิ่มฟังก์ชันเหล่านี้ใน app.py

@app.route("/edit_basic_info", methods=["GET", "POST"])
@login_required("admin")
def edit_basic_info():
    try:
        if "admin_id" in session:
            # ดึงข้อมูลสาขา
            with get_db_cursor() as (db, cursor):
                try:
                    # ดึงข้อมูลสาขา - เรียงลำดับแบบง่าย
                    cursor.execute("SELECT branch_id, branch_name FROM branch ORDER BY branch_id")
                    branches = cursor.fetchall()
                    
                    # ดึงข้อมูลอาจารย์ - เรียงลำดับตาม teacher_id
                    cursor.execute("""
                        SELECT t.teacher_id, t.teacher_name, t.teacher_username, 
                               t.teacher_password, t.teacher_phone, t.teacher_email, 
                               b.branch_name, t.branch_id
                        FROM teacher t
                        LEFT JOIN branch b ON t.branch_id = b.branch_id
                        ORDER BY t.teacher_id
                    """)
                    teachers = cursor.fetchall()
                    
                    # ดึงข้อมูลแอดมิน - เรียงลำดับตาม admin_id
                    cursor.execute("""
                        SELECT admin_id, admin_name, admin_username, admin_password, 
                               admin_email FROM admin ORDER BY admin_id
                    """)
                    admins = cursor.fetchall()
                    
                    # ตรวจสอบข้อมูลเพื่อการ debug
                    print(f"Teachers: {len(teachers)}, Branches: {len(branches)}, Admins: {len(admins)}")
                    
                except Exception as e:
                    print(f"Error fetching data: {e}")
                    teachers = []
                    branches = []
                    admins = []
            
            return render_template(
                "edit_basic_info.html", 
                teachers=teachers, 
                branches=branches,
                admins=admins
            )
        else:
            return redirect(url_for("login"))
    except Exception as e:
        import traceback
        print(f"ERROR in edit_basic_info: {str(e)}")
        print(traceback.format_exc())
        flash(f"ไม่สามารถโหลดหน้าได้ เกิดข้อผิดพลาด: {str(e)}", "error")
        return redirect(url_for("admin_home"))
@app.route("/get_next_branch_id")
@login_required("admin")
def get_next_branch_id():
    """API สำหรับดึงรหัสสาขาถัดไป (รูปแบบ branchXXX)"""
    try:
        with get_db_cursor() as (db, cursor):
            # ดึง branch_id ที่มีรูปแบบ branchXXX
            cursor.execute("SELECT branch_id FROM branch WHERE branch_id LIKE 'branch%' ORDER BY branch_id DESC LIMIT 1")
            max_branch = cursor.fetchone()
            
            if max_branch:
                # แยกเลขจาก branch001 -> 001 -> 1 -> 2 -> 002
                current_num = int(max_branch[0].replace('branch', ''))
                next_num = current_num + 1
                next_id = f"branch{next_num:03d}"  # format เป็น branch001, branch002
            else:
                next_id = "branch001"
            
            return jsonify({
                "success": True,
                "next_id": next_id
            })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/check_branch_id", methods=["POST"])
@login_required("admin")
def check_branch_id():
    """API สำหรับตรวจสอบรหัสสาขาซ้ำ"""
    try:
        branch_id = request.form.get("branch_id")
        
        if not branch_id:
            return jsonify({"exists": False})
        
        with get_db_cursor() as (db, cursor):
            cursor.execute("SELECT COUNT(*) FROM branch WHERE branch_id = %s", (branch_id,))
            count = cursor.fetchone()[0]
            
            return jsonify({"exists": count > 0})
    except Exception as e:
        return jsonify({"exists": False, "error": str(e)}), 500
@app.route('/check_duplicate')
def check_duplicate():
    name = request.args.get('name', '')
    
    with get_db_cursor() as (db, cursor):
        query = "SELECT COUNT(*) FROM project WHERE project_name = %s"
        cursor.execute(query, (name,))
        count = cursor.fetchone()[0]
        
    return jsonify({'duplicate': count > 0})

@app.route("/add_project", methods=["GET", "POST"])
@login_required("teacher")
def add_project():
    if "teacher_id" not in session:
        return redirect(url_for("login"))
    
    teacher_id = session["teacher_id"]
    
    with get_db_cursor() as (db, cursor):
        query = """SELECT teacher.teacher_name, branch.branch_name 
                  FROM teacher 
                  JOIN branch ON teacher.branch_id = branch.branch_id 
                  WHERE teacher.teacher_id = %s"""
        cursor.execute(query, (teacher_id,))
        teacher_info = cursor.fetchone()
    
    if request.method == "POST":
        # รับข้อมูลจากฟอร์ม (เหมือนเดิม)
        project_budgettype = request.form["project_budgettype"]
        project_year = request.form["project_year"]
        project_name = request.form["project_name"]
        project_style = request.form["project_style"]
        project_address = request.form["project_address"]
        project_dotime = request.form["project_dotime"]
        project_endtime = request.form["project_endtime"]
        project_target = request.form["project_target"]
        project_budget = request.form["project_budget"]
        project_detail = request.form["project_detail"]
        project_policy = request.form["policy"]
        
        # รับข้อมูลอื่นๆ
        project_output = request.form["output"]
        project_strategy = request.form["strategy"]
        project_indicator = request.form["indicator"]
        project_cluster = request.form["cluster"]
        project_commonality = request.form["commonality"]
        project_physical_grouping = request.form["physical_grouping"]
        project_rationale = request.form["rationale"]
        project_objectives = request.form["objectives"]
        project_goals = request.form["goals"]
        project_output_target = request.form["output_target"]
        project_outcome_target = request.form["outcome_target"]
        project_activity_text = request.form["project_activity"]
        project_quantity_indicator = request.form["quantity_indicator"]
        project_quality_indicator = request.form["quality_indicator"]
        project_time_indicator = request.form["time_indicator"]
        project_cost_indicator = request.form["cost_indicator"]
        project_expected_results = request.form.get("expected_results", "")
        
        # ข้อมูลกิจกรรม
        activities = []
        activity_data = request.form.getlist("activity[]")
        for i, activity in enumerate(activity_data):
            if activity:
                selected_months = request.form.getlist(f"month[{i}][]")
                activities.append({"activity": activity, "months": selected_months})
        activities_json = json.dumps(activities, ensure_ascii=False)
        
        # ค่าตอบแทน
        compensation = []
        compensation_descriptions = request.form.getlist("compensation_description[]")
        compensation_amounts = request.form.getlist("compensation_amount[]")
        for desc, amount in zip(compensation_descriptions, compensation_amounts):
            if desc and amount:
                compensation.append({"description": desc, "amount": float(amount)})
        compensation_json = json.dumps(compensation, ensure_ascii=False)
        
        # ค่าใช้สอย
        expenses = []
        expense_descriptions = request.form.getlist("expense_description[]")
        expense_amounts = request.form.getlist("expense_amount[]")
        for desc, amount in zip(expense_descriptions, expense_amounts):
            if desc and amount:
                expenses.append({"description": desc, "amount": float(amount)})
        expenses_json = json.dumps(expenses, ensure_ascii=False)
        
        # บันทึกข้อมูลโครงการ
        with get_db_cursor() as (db, cursor):
            query = """INSERT INTO project (
                    project_budgettype, project_year, project_name, project_style,
                    project_address, project_dotime, project_endtime, project_target,
                    teacher_id, project_budget, project_detail,
                    project_output, project_strategy, project_indicator, project_cluster,
                    project_commonality, project_physical_grouping, project_rationale,
                    project_objectives, project_goals, project_output_target, project_outcome_target,
                    project_activity, project_activities_json, project_quantity_indicator,
                    project_quality_indicator, project_time_indicator, project_cost_indicator,
                    project_expected_results, project_compensation_json, project_expenses_json,
                    project_policy, project_create_date
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )"""
            
            cursor.execute(
                query,
                (
                    project_budgettype, project_year, project_name, project_style,
                    project_address, project_dotime, project_endtime, project_target,
                    teacher_id, project_budget, project_detail,
                    project_output, project_strategy, project_indicator, project_cluster,
                    project_commonality, project_physical_grouping, project_rationale,
                    project_objectives, project_goals, project_output_target, project_outcome_target,
                    project_activity_text, activities_json, project_quantity_indicator,
                    project_quality_indicator, project_time_indicator, project_cost_indicator,
                    project_expected_results, compensation_json, expenses_json,
                    project_policy
                )
            )
            db.commit()
            project_id = cursor.lastrowid
            
            # สร้างระเบียนใน approval table
            cursor.execute("""
                INSERT INTO approval (project_id, project_status, project_statusStart)
                VALUES (%s, 0, 0)
            """, (project_id,))
            
            # สร้างและบันทึก PDF ลงตาราง approval
            project_data = {
                "project_id": project_id,
                "project_budgettype": project_budgettype,
                "project_year": project_year,
                "project_name": project_name,
                "project_style": project_style,
                "project_address": project_address,
                "project_dotime": project_dotime,
                "project_endtime": project_endtime,
                "project_target": project_target,
                "project_budget": project_budget,
                "project_detail": project_detail,
                "teacher_name": teacher_info[0],
                "branch_name": teacher_info[1],
                "project_output": project_output,
                "project_strategy": project_strategy,
                "project_indicator": project_indicator,
                "project_cluster": project_cluster,
                "project_commonality": project_commonality,
                "project_physical_grouping": project_physical_grouping,
                "project_rationale": project_rationale,
                "project_objectives": project_objectives,
                "project_goals": project_goals,
                "project_output_target": project_output_target,
                "project_outcome_target": project_outcome_target,
                "project_activity": project_activity_text,
                "project_quantity_indicator": project_quantity_indicator,
                "project_quality_indicator": project_quality_indicator,
                "project_time_indicator": project_time_indicator,
                "project_cost_indicator": project_cost_indicator,
                "project_expected_results": project_expected_results,
                "activities": activities,
                "compensation": compensation,
                "expenses": expenses,
                "policy": project_policy
            }
            
            pdf_buffer = create_project_pdf(project_data)
            if pdf_buffer:
                pdf_content = pdf_buffer.getvalue()
                
                # บันทึก PDF ลงตาราง approval
                cursor.execute("""
                    UPDATE approval SET project_pdf = %s WHERE project_id = %s
                """, (pdf_content, project_id))
                db.commit()
            
        flash("สร้างโครงการเรียบร้อยแล้ว", "success")
        return redirect(url_for("teacher_projects"))

    return render_template("add_project.html", teacher_info=teacher_info)

    
def is_project_name_duplicate(project_name, current_project_id=None):
    with get_db_cursor() as (db, cursor):
        try:
            if current_project_id is not None:
                # แปลงเป็นตัวเลขเพื่อป้องกันข้อผิดพลาด
                current_project_id = int(current_project_id)
                query = "SELECT COUNT(*) FROM project WHERE project_name = %s AND project_id != %s"
                cursor.execute(query, (project_name, current_project_id))
            else:
                query = "SELECT COUNT(*) FROM project WHERE project_name = %s"
                cursor.execute(query, (project_name,))
            
            count = cursor.fetchone()[0]
            return count > 0
        except (ValueError, TypeError) as e:
            print(f"Error in is_project_name_duplicate: {e}")
            # กรณีเกิดข้อผิดพลาด ให้ตรวจสอบแค่ชื่อโดยไม่สนใจ ID
            query = "SELECT COUNT(*) FROM project WHERE project_name = %s"
            cursor.execute(query, (project_name,))
            count = cursor.fetchone()[0]
            return count > 0

def get_teacher_by_id(teacher_id):
    with get_db_cursor() as (db, cursor):
        query = """SELECT t.teacher_id, t.teacher_name, t.teacher_username, t.teacher_password, 
                          t.teacher_phone, t.teacher_email, b.branch_name, t.branch_id
                   FROM teacher t 
                   JOIN branch b ON t.branch_id = b.branch_id 
                   WHERE t.teacher_id = %s"""
        cursor.execute(query, (teacher_id,))
        teacher = cursor.fetchone()
    return teacher

def update_teacher(
    teacher_id,
    teacher_name,
    teacher_username,
    teacher_password,
    teacher_phone,
    teacher_email
):
    with get_db_cursor() as (db, cursor):
        query = """UPDATE teacher SET teacher_name = %s, teacher_username = %s, 
                   teacher_password = %s, teacher_phone = %s, teacher_email = %s 
                   WHERE teacher_id = %s"""
        cursor.execute(
            query,
            (
                teacher_name,
                teacher_username,
                teacher_password,
                teacher_phone,
                teacher_email,
                teacher_id,
            ),
        )
        db.commit()
# แก้ไขฟังก์ชัน edit_teacher เพื่อใช้ระบบสิทธิ์ใหม่
@app.route("/edit_teacher/<int:teacher_id>", methods=["GET", "POST"])
@login_required("admin")
def edit_teacher(teacher_id):
    # ตรวจสอบสิทธิ์ก่อนแก้ไข
    current_username = session.get('admin_name', '')  # หรือฟิลด์ที่เก็บ username
    
    # ดึงข้อมูลอาจารย์ที่จะแก้ไข
    teacher = get_teacher_by_id(teacher_id)
    if not teacher:
        flash("ไม่พบข้อมูลอาจารย์", "error")
        return redirect(url_for("edit_basic_info"))
    
    # ตรวจสอบสิทธิ์
    if not can_edit_user(
        session.get('admin_id'), 
        current_username,
        teacher_id, 
        teacher[2],  # teacher_username
        'admin', 
        'teacher'
    ):
        flash("คุณไม่มีสิทธิ์แก้ไขข้อมูลอาจารย์นี้", "error")
        return redirect(url_for("edit_basic_info"))
    
    if request.method == "GET":
        branches = get_branches_from_database()
        return render_template("edit_teacher.html", teacher=teacher, branches=branches)
        
    elif request.method == "POST":
        # ดำเนินการแก้ไขตามเดิม
        teacher_name = request.form["teacher_name"]
        teacher_username = request.form["teacher_username"]
        branch_id = request.form.get("branch_id")
        
        # ตรวจสอบรหัสผ่าน
        current_teacher = get_teacher_by_id(teacher_id)
        if request.form["teacher_password"] != current_teacher[3] and request.form["teacher_password"].strip():
            teacher_password = generate_password_hash(request.form["teacher_password"])
        else:
            teacher_password = current_teacher[3]
            
        teacher_phone = request.form["teacher_phone"]
        teacher_email = request.form["teacher_email"]
        
        try:
            with get_db_cursor() as (db, cursor):
                query = """UPDATE teacher SET teacher_name = %s, teacher_username = %s, 
                        teacher_password = %s, teacher_phone = %s, teacher_email = %s,
                        branch_id = %s 
                        WHERE teacher_id = %s"""
                cursor.execute(
                    query,
                    (teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email, branch_id, teacher_id),
                )
                db.commit()
                flash("แก้ไขข้อมูลอาจารย์เรียบร้อยแล้ว", "success")
        except Exception as e:
            flash(f"เกิดข้อผิดพลาดในการแก้ไขข้อมูล: {str(e)}", "error")
            
        return redirect(url_for("edit_basic_info"))
def delete_teacher(teacher_id):
    with get_db_cursor() as (db, cursor):
        query = "DELETE FROM teacher WHERE teacher_id = %s"
        cursor.execute(query, (teacher_id,))
        db.commit()
        
def delete_branch(branch_id):
    with get_db_cursor() as (db, cursor):
        query = "DELETE FROM branch WHERE teacher_id = %s"
        cursor.execute(query, (branch_id,))
        db.commit()
@app.route("/delete_teacher/<int:teacher_id>", methods=["POST"])
@login_required("admin")
def delete_teacher_route(teacher_id):
    current_username = session.get('admin_name', '')  # หรือฟิลด์ที่เก็บ username
    
    # ดึงข้อมูลอาจารย์ที่จะลบ
    teacher = get_teacher_by_id(teacher_id)
    if not teacher:
        flash("ไม่พบข้อมูลอาจารย์", "error")
        return redirect(url_for("edit_basic_info"))
    
    # ตรวจสอบสิทธิ์
    if not can_delete_user(
        session.get('admin_id'), 
        current_username,
        teacher_id, 
        teacher[2],  # teacher_username
        'admin', 
        'teacher'
    ):
        flash("คุณไม่มีสิทธิ์ลบข้อมูลอาจารย์นี้", "error")
        return redirect(url_for("edit_basic_info"))
    
    try:
        delete_teacher(teacher_id)
        flash("ลบข้อมูลอาจารย์เรียบร้อยแล้ว", "success")
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการลบข้อมูล: {str(e)}", "error")
    
    return redirect(url_for("edit_basic_info"))
@app.route("/teacher_home")
@login_required("teacher")
def teacher_home():
    if not g.user or g.user['type'] != 'teacher':
        return redirect(url_for("login"))

    page = request.args.get('page', 1, type=int)
    per_page = 3  # จำนวน constants ต่อหน้า
    search_query = request.args.get('search', '')

    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลข่าวสาร (เหมือนเดิม)
        count_query = "SELECT COUNT(*) FROM constants"
        if search_query:
            count_query += " WHERE constants_headname LIKE %s"
            cursor.execute(count_query, (f"%{search_query}%",))
        else:
            cursor.execute(count_query)
        total_constants = cursor.fetchone()[0]

        total_pages = ceil(total_constants / per_page)
        offset = (page - 1) * per_page

        query = "SELECT constants_headname, constants_detail, constants_image FROM constants"
        if search_query:
            query += " WHERE constants_headname LIKE %s"
            query += " ORDER BY constants_datetime DESC LIMIT %s OFFSET %s"
            cursor.execute(query, (f"%{search_query}%", per_page, offset))
        else:
            query += " ORDER BY constants_datetime DESC LIMIT %s OFFSET %s"
            cursor.execute(query, (per_page, offset))
        constants = cursor.fetchall()

        # แปลงรูปภาพเป็น base64
        constants = [
            (c[0], c[1], base64.b64encode(c[2]).decode("utf-8")) for c in constants
        ]
        
        # แก้ไข: ดึงข้อมูลโครงการที่กำลังจัด - ใช้ approval table
        active_projects_query = """
            SELECT p.project_id, p.project_name, p.project_dotime, p.project_endtime, 
                   p.project_address, a.project_statusStart, p.project_target, t.teacher_name,
                   (SELECT COUNT(*) FROM status_register sr WHERE sr.project_id = p.project_id AND sr.status_register = 1) as participant_count
            FROM project p
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN approval a ON p.project_id = a.project_id
            WHERE a.project_status = 2 AND a.project_statusStart = 1
            ORDER BY p.project_dotime ASC
            LIMIT 10
        """
        cursor.execute(active_projects_query)
        active_projects_raw = cursor.fetchall()
        
        # แปลงข้อมูลโครงการที่กำลังจัด
        active_projects = []
        for p in active_projects_raw:
            active_projects.append({
                'project_id': p[0],
                'project_name': p[1],
                'project_dotime': p[2],
                'project_endtime': p[3],
                'project_address': p[4],
                'project_statusStart': p[5],
                'project_target': int(p[6]) if p[6] else 0,
                'teacher_name': p[7],
                'participant_count': int(p[8]) if p[8] else 0
            })

    return render_template(
        "teacher_home.html", 
        constants=constants, 
        user=g.user, 
        page=page, 
        total_pages=total_pages, 
        search_query=search_query,
        active_projects=active_projects
    )

def get_branches_from_database():
    branches = []
    with get_db_cursor() as (db, cursor):
        try:
            query = "SELECT branch_id, branch_name FROM branch ORDER BY branch_name"
            cursor.execute(query)
            branches = cursor.fetchall()
            print("Branch data:", branches)  # debug log
            return branches
        except Exception as e:
            print(f"Error fetching branches: {e}")
            return []
@app.route("/delete_branch/<branch_id>", methods=["POST"])
@login_required("admin")
def delete_branch_route(branch_id):
    try:
        with get_db_cursor() as (db, cursor):
            # ตรวจสอบว่ามีอาจารย์ในสาขานี้หรือไม่
            cursor.execute("SELECT COUNT(*) FROM teacher WHERE branch_id = %s", (branch_id,))
            teacher_count = cursor.fetchone()[0]
            
            if teacher_count > 0:
                flash(f"ไม่สามารถลบสาขาได้ เนื่องจากมีอาจารย์ในสาขานี้ {teacher_count} คน", "error")
                return redirect(url_for("edit_basic_info"))
            
            # ลบสาขา
            cursor.execute("DELETE FROM branch WHERE branch_id = %s", (branch_id,))
            db.commit()
            flash("ลบสาขาเรียบร้อยแล้ว", "success")
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
    
    return redirect(url_for("edit_basic_info"))

@app.route("/delete_admin/<int:admin_id>", methods=["POST"])
@login_required("admin")
def delete_admin_route(admin_id):
    current_username = session.get('admin_name', '')  # หรือฟิลด์ที่เก็บ username
    
    # ป้องกันการลบตัวเอง
    if int(admin_id) == int(session.get('admin_id')):
        flash("ไม่สามารถลบบัญชีแอดมินที่กำลังใช้งานอยู่ได้", "error")
        return redirect(url_for("edit_basic_info"))
    
    # ดึงข้อมูลแอดมินที่จะลบ
    with get_db_cursor() as (db, cursor):
        cursor.execute("SELECT admin_id, admin_name, admin_username FROM admin WHERE admin_id = %s", (admin_id,))
        target_admin = cursor.fetchone()
        
        if not target_admin:
            flash("ไม่พบข้อมูลแอดมิน", "error")
            return redirect(url_for("edit_basic_info"))
        
        target_username = target_admin[2]
        
        # ตรวจสอบสิทธิ์
        if not can_delete_user(
            session.get('admin_id'), 
            current_username,
            admin_id, 
            target_username,
            'admin', 
            'admin'
        ):
            flash("คุณไม่มีสิทธิ์ลบแอดมินคนนี้", "error")
            return redirect(url_for("edit_basic_info"))
        
        try:
            cursor.execute("DELETE FROM admin WHERE admin_id = %s", (admin_id,))
            db.commit()
            flash("ลบแอดมินเรียบร้อยแล้ว", "success")
        except Exception as e:
            flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
    
    return redirect(url_for("edit_basic_info"))


@app.route("/edit_branch/<branch_id>", methods=["GET", "POST"])
@login_required("admin")
def edit_branch(branch_id):
    if request.method == "GET":
        with get_db_cursor() as (db, cursor):
            cursor.execute("SELECT branch_id, branch_name FROM branch WHERE branch_id = %s", (branch_id,))
            branch = cursor.fetchone()
            
            if not branch:
                flash("ไม่พบข้อมูลสาขา", "error")
                return redirect(url_for("edit_basic_info"))
                
        return render_template("edit_branch.html", branch=branch)
    
    elif request.method == "POST":
        branch_name = request.form["branch_name"]
        
        try:
            with get_db_cursor() as (db, cursor):
                cursor.execute("UPDATE branch SET branch_name = %s WHERE branch_id = %s", 
                              (branch_name, branch_id))
                db.commit()
                flash("อัปเดตข้อมูลสาขาเรียบร้อยแล้ว", "success")
        except Exception as e:
            flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
            
        return redirect(url_for("edit_basic_info"))
@app.route("/add_admin", methods=["GET", "POST"])
@login_required("admin")
def add_admin():
    if request.method == "GET":
        return render_template("add_admin.html")
    
    elif request.method == "POST":
        admin_name = request.form["admin_name"]
        admin_username = request.form["admin_username"]
        admin_password = generate_password_hash(request.form["admin_password"])
        admin_email = request.form["admin_email"]  # Changed from Admin_email to admin_email
        admin_phone = request.form["admin_phone"]  # Changed from Admin_phone to admin_phone
        db = None
        cursor = None
        
        try:
            # เปิดการเชื่อมต่อฐานข้อมูลโดยตรงแทนการใช้ context manager
            db = mysql.connector.connect(
                host="localhost",
                user="root",
                password="",
                database="Finalproject",
                connection_timeout=60,
                use_pure=True
            )
            cursor = db.cursor(buffered=True)
            
            # ตรวจสอบชื่อผู้ใช้ซ้ำ
            cursor.execute("SELECT COUNT(*) FROM admin WHERE admin_username = %s", (admin_username,))
            if cursor.fetchone()[0] > 0:
                flash("ชื่อผู้ใช้นี้มีอยู่แล้ว กรุณาใช้ชื่อผู้ใช้อื่น", "error")
                return render_template("add_admin.html")
            
            query = """INSERT INTO admin (admin_name, admin_username, admin_password, Admin_phone, Admin_email) 
                       VALUES (%s, %s, %s, %s, %s)"""
            cursor.execute(query, (admin_name, admin_username, admin_password, admin_phone, admin_email))
            db.commit()
            flash("เพิ่มแอดมินเรียบร้อยแล้ว", "success")
            
        except Exception as e:
            if db:
                db.rollback()
            flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
            return render_template("add_admin.html")
            
        finally:
            if cursor:
                cursor.close()
            if db:
                db.close()
                
        return redirect(url_for("edit_basic_info"))
@app.route("/teacher_profile", methods=["GET", "POST"])
@login_required("teacher")
def teacher_profile():
    if "teacher_id" not in session:
        return redirect(url_for("login"))

    teacher_id = session["teacher_id"]
    
    if request.method == "GET":
        # ดึงข้อมูลอาจารย์พร้อมสาขา
        with get_db_cursor() as (db, cursor):
            query = """SELECT t.teacher_id, t.teacher_name, t.teacher_username, 
                              t.teacher_password, t.teacher_phone, t.teacher_email, 
                              b.branch_name, t.branch_id
                       FROM teacher t
                       LEFT JOIN branch b ON t.branch_id = b.branch_id
                       WHERE t.teacher_id = %s"""
            cursor.execute(query, (teacher_id,))
            teacher_data = cursor.fetchone()
            
            if not teacher_data:
                flash("ไม่พบข้อมูลอาจารย์", "error")
                return redirect(url_for("teacher_home"))
            
            # แปลงข้อมูลเป็น dictionary
            teacher = {
                'teacher_id': teacher_data[0],
                'teacher_name': teacher_data[1],
                'teacher_username': teacher_data[2],
                'teacher_password': teacher_data[3],
                'teacher_phone': teacher_data[4],
                'teacher_email': teacher_data[5],
                'branch_name': teacher_data[6] if teacher_data[6] else 'ไม่ระบุสาขา',
                'branch_id': teacher_data[7]
            }
            
        return render_template("teacher_profile.html", teacher=teacher)
    
    elif request.method == "POST":
        # รับข้อมูลจากฟอร์ม
        new_phone = request.form.get("teacher_phone", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        current_password = request.form.get("current_password", "").strip()
        
        if not current_password:
            flash("กรุณากรอกรหัสผ่านปัจจุบัน", "error")
            return redirect(url_for("teacher_profile"))
        
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลอาจารย์ปัจจุบัน
            cursor.execute("SELECT teacher_password, teacher_phone FROM teacher WHERE teacher_id = %s", (teacher_id,))
            current_data = cursor.fetchone()
            
            if not current_data:
                flash("ไม่พบข้อมูลอาจารย์", "error")
                return redirect(url_for("teacher_profile"))
            
            stored_password = current_data[0]
            current_phone = current_data[1]
            
            # ตรวจสอบรหัสผ่านปัจจุบัน - รองรับทั้ง hash และไม่ hash
            password_valid = False
            try:
                # ลองตรวจสอบแบบ hash ก่อน
                if stored_password.startswith(('pbkdf2:', 'scrypt:', 'argon2:', '$')):
                    # เป็นรหัสผ่านที่ hash แล้ว
                    password_valid = check_password_hash(stored_password, current_password)
                else:
                    # เป็นรหัสผ่านแบบ plain text
                    password_valid = (stored_password == current_password)
            except Exception as e:
                # ถ้าเกิดข้อผิดพลาดในการตรวจสอบ hash ให้ลองเปรียบเทียบตรงๆ
                password_valid = (stored_password == current_password)
            
            if not password_valid:
                flash("รหัสผ่านปัจจุบันไม่ถูกต้อง", "error")
                return redirect(url_for("teacher_profile"))
            
            # ตรวจสอบการเปลี่ยนแปลง
            changes_made = False
            update_fields = []
            update_values = []
            
            # ตรวจสอบเบอร์โทรศัพท์
            if new_phone and new_phone != current_phone:
                update_fields.append("teacher_phone = %s")
                update_values.append(new_phone)
                changes_made = True
            
            # ตรวจสอบรหัสผ่าน
            if new_password:
                if new_password != confirm_password:
                    flash("รหัสผ่านใหม่และยืนยันรหัสผ่านไม่ตรงกัน", "error")
                    return redirect(url_for("teacher_profile"))
                
                if len(new_password) < 4:
                    flash("รหัสผ่านต้องมีอย่างน้อย 4 ตัวอักษร", "error")
                    return redirect(url_for("teacher_profile"))
                
                # เข้ารหัสรหัสผ่านใหม่
                hashed_password = generate_password_hash(new_password)
                update_fields.append("teacher_password = %s")
                update_values.append(hashed_password)
                changes_made = True
            
            if not changes_made:
                flash("ไม่มีการเปลี่ยนแปลงข้อมูล", "info")
                return redirect(url_for("teacher_profile"))
            
            # อัพเดทข้อมูล
            try:
                query = f"UPDATE teacher SET {', '.join(update_fields)} WHERE teacher_id = %s"
                update_values.append(teacher_id)
                cursor.execute(query, update_values)
                db.commit()
                
                flash("อัพเดทข้อมูลส่วนตัวเรียบร้อยแล้ว", "success")
                
                # อัพเดท session หากเปลี่ยนเบอร์โทร
                if new_phone and new_phone != current_phone:
                    session["teacher_phone"] = new_phone
                
            except Exception as e:
                flash(f"เกิดข้อผิดพลาดในการอัพเดทข้อมูล: {str(e)}", "error")
                
        return redirect(url_for("teacher_profile"))

@app.route("/edit_admin/<int:admin_id>", methods=["GET", "POST"])
@login_required("admin")
def edit_admin(admin_id):
    if request.method == "GET":
        with get_db_cursor() as (db, cursor):
            cursor.execute("""
                SELECT admin_id, admin_name, admin_username, admin_password, Admin_email, Admin_phone 
                FROM admin WHERE admin_id = %s
            """, (admin_id,))
            admin = cursor.fetchone()
            
            if not admin:
                flash("ไม่พบข้อมูลแอดมิน", "error")
                return redirect(url_for("edit_basic_info"))
                
        return render_template("edit_admin.html", admin=admin)
    
    elif request.method == "POST":
        admin_name = request.form["admin_name"]
        admin_username = request.form["admin_username"]
        admin_email = request.form["admin_email"]
        admin_phone = request.form["admin_phone"]  # Added this line to retrieve phone
        
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลแอดมินเดิม
            cursor.execute("SELECT admin_password FROM admin WHERE admin_id = %s", (admin_id,))
            current_admin = cursor.fetchone()
            
            # ตรวจสอบว่ามีการเปลี่ยนรหัสผ่านหรือไม่
            if request.form["admin_password"]:
                admin_password = generate_password_hash(request.form["admin_password"])
            else:
                admin_password = current_admin[0]  # ใช้รหัสผ่านเดิม
                
            try:
                query = """UPDATE admin SET 
                           admin_name = %s, admin_username = %s, 
                           admin_password = %s, Admin_email = %s, Admin_phone = %s 
                           WHERE admin_id = %s"""
                cursor.execute(query, (admin_name, admin_username, admin_password, admin_email, admin_phone, admin_id))
                db.commit()
                flash("อัปเดตข้อมูลแอดมินเรียบร้อยแล้ว", "success")
            except Exception as e:
                flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
                
        return redirect(url_for("edit_basic_info"))

@app.route("/add_teacher", methods=["GET", "POST"])
@login_required("admin")
def add_teacher():
    if request.method == "GET":
        branches = get_branches_from_database()
        return render_template("add_teacher.html", branches=branches)
    elif request.method == "POST":
        teacher_name = request.form["teacher_name"]
        teacher_username = request.form["teacher_username"]
        teacher_password = generate_password_hash(request.form["teacher_password"])
        teacher_phone = request.form["teacher_phone"]
        teacher_email = request.form["teacher_email"]
        branch_id = request.form["branch_id"]

        with get_db_cursor() as (db, cursor):
            query = """INSERT INTO teacher (teacher_name, teacher_username, teacher_password, 
                                            teacher_phone, teacher_email, branch_id) 
                       VALUES (%s, %s, %s, %s, %s, %s)"""
            cursor.execute(
                query,
                (
                    teacher_name,
                    teacher_username,
                    teacher_password,
                    teacher_phone,
                    teacher_email,
                    branch_id
                ),
            )
            db.commit()

        return redirect(url_for("edit_basic_info"))

@app.route("/teacher_projects")
@login_required("teacher")
def teacher_projects():
    if "teacher_id" not in session:
        return redirect(url_for("login"))

    teacher_id = session["teacher_id"]
    page = request.args.get("page", 1, type=int)
    per_page = 6

    with get_db_cursor() as (db, cursor):
        # นับจำนวนโปรเจคที่ยังไม่เสร็จสิ้นทั้งหมด
        cursor.execute(
            """SELECT COUNT(*) 
               FROM project p
               JOIN approval a ON p.project_id = a.project_id
               WHERE p.teacher_id = %s AND (a.project_statusStart != 2 OR a.project_statusStart IS NULL)""", 
            (teacher_id,)
        )
        total_projects = cursor.fetchone()[0]

        # คำนวณจำนวนหน้าทั้งหมด
        total_pages = ceil(total_projects / per_page)

        # ดึงข้อมูลโปรเจคตามหน้าที่ต้องการ
        offset = (page - 1) * per_page
        query = """
            SELECT p.project_id, p.project_name, a.project_status, a.project_statusStart, 
                   CASE WHEN a.project_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_pdf,
                   a.project_reject, a.project_submit_date, a.project_reject_date
            FROM project p
            JOIN approval a ON p.project_id = a.project_id
            WHERE p.teacher_id = %s AND (a.project_statusStart != 2 OR a.project_statusStart IS NULL)
            ORDER BY 
                CASE 
                    WHEN a.project_submit_date IS NOT NULL THEN a.project_submit_date
                    ELSE p.project_create_date
                END DESC,
                p.project_id DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, (teacher_id, per_page, offset))
        projects = cursor.fetchall()

    return render_template(
        "teacher_projects.html",
        projects=projects,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )

@app.route("/request_approval", methods=["POST"])
@login_required("teacher")
def request_approval():
    data = request.json
    project_id = data.get("project_id")
    try:
        with get_db_cursor() as (db, cursor):
            cursor.execute("""
                UPDATE approval 
                SET project_status = 1, project_submit_date = NOW() 
                WHERE project_id = %s
            """, (project_id,))
            db.commit()
        return jsonify({"success": True})
    except Exception as e:
        logging.error(f"Error in request_approval: {str(e)}")
        return jsonify({"success": False}), 500


@app.route("/reject_project", methods=["POST"])
@login_required("admin")
def reject_project():
    if "admin_id" in session:
        project_id = request.form.get("project_id")
        project_reject = request.form.get("project_reject")
        with get_db_cursor() as (db, cursor):
            query = "UPDATE project SET project_status = 3, project_reject = %s WHERE project_id = %s"
            cursor.execute(query, (project_reject, project_id))
            db.commit()
        flash("โครงการถูกตีกลับพร้อมเหตุผล", "warning")
        return redirect(url_for("approve_project"))
    else:
        return redirect(url_for("login"))


@app.route("/project/<int:project_id>")
def project_detail(project_id):
    with get_db_cursor() as (db, cursor):
        # แก้ไข: ใช้ approval table สำหรับ project_statusStart
        query = """SELECT p.project_id, p.project_name, p.project_year, p.project_style, 
                          p.project_address, DATE(p.project_dotime) as project_dotime, 
                          DATE(p.project_endtime) as project_endtime, 
                          p.project_target, t.teacher_name, a.project_statusStart,
                          a.project_status, p.project_detail
                   FROM project p
                   JOIN teacher t ON p.teacher_id = t.teacher_id
                   JOIN approval a ON p.project_id = a.project_id
                   WHERE p.project_id = %s"""
        cursor.execute(query, (project_id,))
        project = cursor.fetchone()

        if not project:
            flash("โครงการไม่พบ", "error")
            return redirect(url_for("active_projects"))

        # ใช้ status_register
        cursor.execute(
            "SELECT COUNT(*) FROM status_register WHERE project_id = %s",
            (project_id,),
        )
        current_count = cursor.fetchone()[0]

        project_dict = {
            "project_id": project[0],
            "project_name": project[1],
            "project_year": project[2],
            "project_style": project[3],
            "project_address": project[4],
            "project_dotime": project[5],
            "project_endtime": project[6],
            "project_target": int(project[7]) if project[7] is not None else 0,
            "teacher_name": project[8],
            "project_statusStart": project[9],
            "project_status": project[10],
            "project_detail": project[11],
        }

    is_logged_in = 'user_type' in session
    user_type = session.get('user_type')

    return render_template(
        "project_detail.html",
        project=project_dict,
        current_count=current_count,
        is_logged_in=is_logged_in,
        user_type=user_type
    )
@app.route("/update_project_statusStart", methods=["POST"])
@login_required("teacher")
def update_project_statusStart():
    if "teacher_id" not in session:
        return redirect(url_for("login"))

    project_id = request.form.get("project_id")
    project_status = request.form.get("projectStatus")

    with get_db_cursor() as (db, cursor):
        cursor.execute(
        "SELECT project_status, project_statusStart FROM approval WHERE project_id = %s", (project_id,)
    )
    result = cursor.fetchone()
    if result and result[0] != 2:
        flash("โครงการยังไม่ได้รับการอนุมัติ ไม่สามารถเริ่มดำเนินการได้", "error")
        return redirect(url_for("project_detail", project_id=project_id))

    # ป้องกันการเปลี่ยนสถานะเมื่อโครงการเสร็จสิ้นแล้ว
    if result and result[1] == 2:
        flash("โครงการนี้เสร็จสิ้นแล้ว ไม่สามารถเปลี่ยนแปลงสถานะได้", "error")
        return redirect(url_for("project_detail", project_id=project_id))

        if project_status is not None and project_status != "":
            try:
                project_status = int(project_status)
                # แก้ไข: อัปเดตใน approval table แทน project table
                query = (
                    "UPDATE approval SET project_statusStart = %s WHERE project_id = %s"
                )
                cursor.execute(query, (project_status, project_id))
                db.commit()
                flash("อัพเดทสถานะโครงการเรียบร้อยแล้ว", "success")
            except ValueError:
                flash("สถานะโครงการไม่ถูกต้อง", "error")
        else:
            flash("กรุณาเลือกสถานะโครงการ", "error")

    return redirect(url_for("project_detail", project_id=project_id))



# แก้ไข route active_projects ใน app.py
@app.route("/active_projects")
def active_projects():
    # ตรวจสอบสถานะการล็อกอิน
    is_logged_in = False
    user_type = None
    
    if 'user_type' in session:
        is_logged_in = True
        user_type = session['user_type']
    
    with get_db_cursor() as (db, cursor):
        # แก้ไข: ใช้ approval table แทน project table สำหรับ project_statusStart
        query = """
        SELECT p.project_id, p.project_name, p.project_dotime, p.project_endtime,
               a.project_statusStart, t.teacher_name
        FROM project p
        JOIN teacher t ON p.teacher_id = t.teacher_id
        JOIN approval a ON p.project_id = a.project_id
        WHERE a.project_status = 2 AND (a.project_statusStart = 1 OR a.project_statusStart = 2)
        ORDER BY p.project_dotime DESC
        """
        cursor.execute(query)
        projects = cursor.fetchall()

    return render_template(
        "active_projects.html", 
        projects=projects,
        is_logged_in=is_logged_in,
        user_type=user_type
    )

@app.route("/project/<int:project_id>/approve_participants")
@login_required("teacher")
def approve_participants(project_id):
    if "teacher_id" not in session:
        flash("คุณไม่มีสิทธิ์ในการดำเนินการนี้", "error")
        return redirect(url_for("home"))

    with get_db_cursor() as (db, cursor):
        cursor.execute(
            "SELECT teacher_id FROM project WHERE project_id = %s", (project_id,)
        )
        project = cursor.fetchone()
        if not project or project[0] != session["teacher_id"]:
            flash("คุณไม่มีสิทธิ์อนุมัติผู้เข้าร่วมโครงการนี้", "error")
            return redirect(url_for("project_detail", project_id=project_id))

        cursor.execute(
            """
            SELECT join_id, join_name, join_email, join_telephone, join_status
            FROM `join`
            WHERE project_id = %s
        """,
            (project_id,),
        )
        participants = cursor.fetchall()

        # แปลง tuple เป็น dictionary
        participants = [
            {
                "join_id": p[0],
                "join_name": p[1],
                "join_email": p[2],
                "join_telephone": p[3],
                "join_status": p[4],
            }
            for p in participants
        ]

    return render_template(
        "approve_participants.html", project_id=project_id, participants=participants
    )

@app.route('/check_student', methods=['POST'])
def check_student():
    student_id = request.form.get('student_id')  # รหัสบัตรนักศึกษา
    project_id = request.form.get('project_id')
    
    if not student_id or not project_id:
        return jsonify({'exists': False})
    
    with get_db_cursor() as (db, cursor):
        try:
            # แก้ไข: ตรวจสอบใน status_register
            cursor.execute(
                """
                SELECT COUNT(*) 
                FROM status_register 
                WHERE join_id = %s AND project_id = %s
                """, 
                (student_id, project_id)
            )
            already_in_project = cursor.fetchone()[0] > 0
            
            if already_in_project:
                return jsonify({
                    'exists': False,
                    'already_joined': True,
                    'message': f"รหัสบัตรนักศึกษา {student_id} ได้ลงทะเบียนเข้าร่วมโครงการนี้แล้ว"
                })
            
            # ดึงข้อมูลนักศึกษาจากรหัสบัตรนักศึกษา
            cursor.execute("""
                SELECT j.join_name, j.join_email, j.join_telephone, j.branch_id, b.branch_name 
                FROM `join` j
                LEFT JOIN branch b ON j.branch_id = b.branch_id
                WHERE j.join_id = %s
            """, (student_id,))
            
            student = cursor.fetchone()
            
            if student:
                return jsonify({
                    'exists': True,
                    'student_name': student[0] if student[0] is not None else '',
                    'student_email': student[1] if student[1] is not None else '',
                    'student_phone': student[2] if student[2] is not None else '',
                    'branch_id': student[3] if student[3] is not None else '',
                    'branch_name': student[4] if student[4] is not None else '',
                    'message': f"พบข้อมูลนักศึกษารหัส {student_id} ในระบบ"
                })
            
            return jsonify({
                'exists': False,
                'message': f"ไม่พบข้อมูลนักศึกษารหัส {student_id} ในระบบ โปรดลงทะเบียนแบบนักศึกษาใหม่"
            })
            
        except Exception as e:
            return jsonify({
                'exists': False, 
                'error': str(e),
                'message': "เกิดข้อผิดพลาดในการตรวจสอบข้อมูล"
            })


@app.route("/manage_students")
@login_required("admin")
def manage_students():
    if not g.user or g.user["type"] != "admin":
        return redirect(url_for("login"))

    page = request.args.get('page', 1, type=int)
    per_page = 10
    search_query = request.args.get('search', '')

    with get_db_cursor() as (db, cursor):
        base_query = """
            SELECT j.join_id, j.join_name, j.join_email, j.join_telephone, 
                   j.branch_id, b.branch_name
            FROM `join` j
            LEFT JOIN branch b ON j.branch_id = b.branch_id
        """
        
        count_query = "SELECT COUNT(*) FROM `join`"
        
        query_params = []
        
        if search_query:
            base_query += " WHERE (j.join_id LIKE %s OR j.join_name LIKE %s)"
            count_query += " WHERE (join_id LIKE %s OR join_name LIKE %s)"
            search_pattern = f"%{search_query}%"
            query_params.extend([search_pattern, search_pattern])
            
        if search_query:
            cursor.execute(count_query, [f"%{search_query}%", f"%{search_query}%"])
        else:
            cursor.execute(count_query)
        total_students = cursor.fetchone()[0]
        
        total_pages = ceil(total_students / per_page)
        
        base_query += " ORDER BY j.join_name LIMIT %s OFFSET %s"
        offset = (page - 1) * per_page
        query_params.extend([per_page, offset])
        
        cursor.execute(base_query, query_params)
        student_rows = cursor.fetchall()
        
        students = []
        for row in student_rows:
            students.append({
                'student_id': row[0],  # join_id
                'name': row[1],
                'email': row[2],
                'phone': row[3],
                'branch_id': row[4],
                'branch_name': row[5] if row[5] else 'ไม่ระบุสาขา'
            })
    
    return render_template(
        "manage_students.html",
        students=students,
        page=page,
        total_pages=total_pages,
        search_query=search_query
    )

@app.route('/check_student_id_exists')
def check_student_id_exists():
    """ตรวจสอบรหัสนักศึกษาซ้ำ"""
    student_id = request.args.get('student_id')
    
    if not student_id:
        return jsonify({'exists': False})
    
    with get_db_cursor() as (db, cursor):
        cursor.execute(
            "SELECT COUNT(*) FROM `join` WHERE join_student_id = %s",
            (student_id,)
        )
        count = cursor.fetchone()[0]
        
    return jsonify({'exists': count > 0})

@app.route("/add_student", methods=["GET", "POST"])
@login_required("admin")
def add_student():
    """เพิ่มข้อมูลนักศึกษา"""
    if request.method == "GET":
        branches = get_branches_from_database()
        return render_template("add_student.html", branches=branches)
    
    elif request.method == "POST":
        student_id = request.form["student_id"]
        student_name = request.form["student_name"]
        student_email = request.form.get("student_email", "")
        student_phone = request.form["student_phone"]
        branch_id = request.form.get("branch_id")
        student_password = request.form.get("student_password", "")  # รหัสผ่านใหม่
        
        # ตรวจสอบรหัสนักศึกษาซ้ำ
        with get_db_cursor() as (db, cursor):
            cursor.execute(
                "SELECT COUNT(*) FROM `join` WHERE join_id = %s",
                (student_id,)
            )
            if cursor.fetchone()[0] > 0:
                flash("รหัสนักศึกษานี้มีอยู่ในระบบแล้ว", "error")
                return redirect(url_for("add_student"))
            
            # เข้ารหัสรหัสผ่าน
            hashed_password = ""
            if student_password:
                hashed_password = generate_password_hash(student_password)
                
            try:
                # บันทึกข้อมูลนักศึกษาโดยตรงในตาราง join
                query = """
                    INSERT INTO `join` (join_id, join_name, join_email, join_telephone, branch_id, join_password)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    query,
                    (student_id, student_name, student_email, student_phone, branch_id, hashed_password)
                )
                db.commit()
                
                flash("เพิ่มข้อมูลนักศึกษาเรียบร้อยแล้ว", "success")
                return redirect(url_for("manage_students"))
                
            except Exception as e:
                db.rollback()
                flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {str(e)}", "error")
                return redirect(url_for("add_student"))
                
        return redirect(url_for("manage_students"))

@app.route("/edit_student/<student_id>", methods=["GET", "POST"])
@login_required("admin")
def edit_student(student_id):
    """แก้ไขข้อมูลนักศึกษาพร้อมจัดการรหัสผ่าน"""
    with get_db_cursor() as (db, cursor):
        if request.method == "GET":
            # ดึงข้อมูลนักศึกษา
            cursor.execute("""
                SELECT j.join_id, j.join_name, j.join_email, j.join_telephone, 
                       j.branch_id, b.branch_name, j.join_password
                FROM `join` j
                LEFT JOIN branch b ON j.branch_id = b.branch_id
                WHERE j.join_id = %s
                ORDER BY j.join_id DESC
                LIMIT 1
            """, (student_id,))
            student_data = cursor.fetchone()
            
            if not student_data:
                flash("ไม่พบข้อมูลนักศึกษา", "error")
                return redirect(url_for("manage_students"))
                
            # สร้าง dictionary ข้อมูลนักศึกษา
            student = {
                'student_id': student_data[0],
                'name': student_data[1],
                'email': student_data[2],
                'phone': student_data[3],
                'branch_id': student_data[4],
                'branch_name': student_data[5] if student_data[5] else 'ไม่ระบุสาขา',
                'has_password': bool(student_data[6])  # ตรวจสอบว่ามีรหัสผ่านหรือไม่
            }
            
            # ดึงข้อมูลสาขาทั้งหมด
            branches = get_branches_from_database()
            
            return render_template("edit_student.html", student=student, branches=branches)
            
        elif request.method == "POST":
            student_name = request.form["student_name"]
            student_email = request.form.get("student_email", "")
            student_phone = request.form["student_phone"]
            branch_id = request.form.get("branch_id")
            
            # จัดการรหัสผ่าน
            reset_password = request.form.get("reset_password") == "1"
            clear_password = request.form.get("clear_password") == "1"
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            
            try:
                # เตรียมข้อมูลสำหรับอัปเดต
                update_fields = ["join_name = %s", "join_email = %s", "join_telephone = %s", "branch_id = %s"]
                update_values = [student_name, student_email, student_phone, branch_id]
                
                # จัดการรหัสผ่าน
                if clear_password:
                    # ลบรหัสผ่าน
                    update_fields.append("join_password = NULL")
                    flash("ลบรหัสผ่านเรียบร้อยแล้ว นักศึกษาจะต้องใช้เบอร์โทรในการเข้าสู่ระบบ", "info")
                    
                elif reset_password:
                    # รีเซ็ตรหัสผ่าน
                    if not new_password or not confirm_password:
                        flash("กรุณากรอกรหัสผ่านใหม่และยืนยันรหัสผ่านให้ครบถ้วน", "error")
                        return redirect(url_for("edit_student", student_id=student_id))
                    
                    if new_password != confirm_password:
                        flash("รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน", "error")
                        return redirect(url_for("edit_student", student_id=student_id))
                    
                    if len(new_password) < 4:
                        flash("รหัสผ่านต้องมีอย่างน้อย 4 ตัวอักษร", "error")
                        return redirect(url_for("edit_student", student_id=student_id))
                    
                    # เข้ารหัสรหัสผ่านใหม่
                    hashed_password = generate_password_hash(new_password)
                    update_fields.append("join_password = %s")
                    update_values.append(hashed_password)
                    flash("รีเซ็ตรหัสผ่านเรียบร้อยแล้ว กรุณาแจ้งรหัสผ่านใหม่ให้นักศึกษาทราบ", "success")
                
                # อัปเดตข้อมูลนักศึกษา
                query = f"""
                    UPDATE `join` 
                    SET {', '.join(update_fields)}
                    WHERE join_id = %s
                """
                update_values.append(student_id)
                
                cursor.execute(query, update_values)
                db.commit()
                
                if not (reset_password or clear_password):
                    flash("อัปเดตข้อมูลนักศึกษาเรียบร้อยแล้ว", "success")
                
            except Exception as e:
                db.rollback()
                flash(f"เกิดข้อผิดพลาดในการอัปเดตข้อมูล: {str(e)}", "error")
                
            return redirect(url_for("manage_students"))
        # เพิ่มฟังก์ชันเหล่านี้ใน app.py

@app.route("/register_student", methods=["POST"])
def register_student():
    """ฟังก์ชันสมัครสมาชิกนักศึกษา"""
    try:
        student_id = request.form.get("student_id", "").strip()
        student_name = request.form.get("student_name", "").strip()
        student_email = request.form.get("student_email", "").strip()
        student_phone = request.form.get("student_phone", "").strip()
        branch_id = request.form.get("branch_id", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        # ตรวจสอบข้อมูลพื้นฐาน
        if not all([student_id, student_name, student_email, student_phone, branch_id, password, confirm_password]):
            flash("กรุณากรอกข้อมูลให้ครบถ้วน", "danger")
            return redirect(url_for("login"))
        
        # ตรวจสอบรหัสผ่าน
        if password != confirm_password:
            flash("รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน", "danger")
            return redirect(url_for("login"))
        
        if len(password) < 4:
            flash("รหัสผ่านต้องมีอย่างน้อย 4 ตัวอักษร", "danger")
            return redirect(url_for("login"))
        
        # ตรวจสอบรูปแบบอีเมล
        import re
        email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_regex, student_email):
            flash("กรุณากรอกอีเมลให้ถูกต้อง", "danger")
            return redirect(url_for("login"))
        
        # ตรวจสอบเบอร์โทร
        if len(student_phone) < 9:
            flash("กรุณากรอกเบอร์โทรศัพท์ให้ถูกต้อง (อย่างน้อย 9 หลัก)", "danger")
            return redirect(url_for("login"))
        
        with get_db_cursor() as (db, cursor):
            # ตรวจสอบรหัสนักศึกษาซ้ำ
            cursor.execute("SELECT COUNT(*) FROM `join` WHERE join_id = %s", (student_id,))
            if cursor.fetchone()[0] > 0:
                flash("รหัสนักศึกษานี้มีอยู่ในระบบแล้ว", "danger")
                return redirect(url_for("login"))
            
            # ตรวจสอบอีเมลซ้ำ
            cursor.execute("SELECT COUNT(*) FROM `join` WHERE join_email = %s", (student_email,))
            if cursor.fetchone()[0] > 0:
                flash("อีเมลนี้มีอยู่ในระบบแล้ว", "danger")
                return redirect(url_for("login"))
            
            # ตรวจสอบว่าสาขาที่เลือกมีอยู่จริง
            cursor.execute("SELECT COUNT(*) FROM branch WHERE branch_id = %s", (branch_id,))
            if cursor.fetchone()[0] == 0:
                flash("ไม่พบสาขาที่เลือก", "danger")
                return redirect(url_for("login"))
            
            # เข้ารหัสรหัสผ่าน
            hashed_password = generate_password_hash(password)
            
            # บันทึกข้อมูลนักศึกษา
            cursor.execute("""
                INSERT INTO `join` (join_id, join_name, join_email, join_telephone, branch_id, join_password)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (student_id, student_name, student_email, student_phone, branch_id, hashed_password))
            
            db.commit()
            
            flash(f"สมัครสมาชิกเรียบร้อยแล้ว! ยินดีต้อนรับ {student_name} สามารถเข้าสู่ระบบได้ทันที", "success")
            
            # ล็อกอินอัตโนมัติหลังสมัครสมาชิก
            session.clear()
            session["student_id"] = student_id
            session["student_name"] = student_name
            session["student_email"] = student_email
            session["student_phone"] = student_phone
            session["student_branch_id"] = branch_id
            
            # ดึงชื่อสาขา
            cursor.execute("SELECT branch_name FROM branch WHERE branch_id = %s", (branch_id,))
            branch_result = cursor.fetchone()
            session["student_branch"] = branch_result[0] if branch_result else "ไม่ระบุสาขา"
            session["user_type"] = "student"
            
            return redirect(url_for("student_dashboard"))
            
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการสมัครสมาชิก: {str(e)}", "danger")
        return redirect(url_for("login"))

@app.route("/get_branches", methods=["GET"])
def get_branches():
    """API สำหรับดึงข้อมูลสาขาทั้งหมด"""
    try:
        with get_db_cursor() as (db, cursor):
            cursor.execute("SELECT branch_id, branch_name FROM branch ORDER BY branch_name")
            branches = cursor.fetchall()
            
            branch_list = []
            for branch in branches:
                branch_list.append({
                    "id": branch[0],
                    "name": branch[1]
                })
            
            return jsonify({
                "success": True,
                "branches": branch_list
            })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/check_student_exists", methods=["POST"])
def check_student_exists():
    """API สำหรับตรวจสอบรหัสนักศึกษาซ้ำ"""
    try:
        student_id = request.form.get("student_id", "").strip()
        
        if not student_id:
            return jsonify({"exists": False})
        
        with get_db_cursor() as (db, cursor):
            cursor.execute("SELECT COUNT(*) FROM `join` WHERE join_id = %s", (student_id,))
            count = cursor.fetchone()[0]
            
            return jsonify({"exists": count > 0})
    except Exception as e:
        return jsonify({"exists": False, "error": str(e)}), 500

@app.route("/delete_student/<student_id>", methods=["POST"])
@login_required("admin")
def delete_student(student_id):
    """ลบข้อมูลนักศึกษา"""
    try:
        with get_db_cursor() as (db, cursor):
            # ลบข้อมูลการประเมินของนักศึกษาก่อน
            cursor.execute("""
                DELETE pe 
                FROM project_evaluation pe 
                JOIN `join` j ON pe.join_id = j.join_id 
                WHERE j.join_student_id = %s
            """, (student_id,))
            
            # ลบข้อมูลการเข้าร่วมโครงการของนักศึกษา
            cursor.execute("DELETE FROM `join` WHERE join_student_id = %s", (student_id,))
            
            db.commit()
            flash("ลบข้อมูลนักศึกษาเรียบร้อยแล้ว", "success")
            
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการลบข้อมูล: {str(e)}", "error")
        
    return redirect(url_for("manage_students"))
@app.route("/student_profile", methods=["GET", "POST"])
def student_profile():
    if 'user_type' not in session or session['user_type'] != 'student':
        flash('คุณต้องล็อกอินด้วยบัญชีนักศึกษาก่อน', 'error')
        return redirect(url_for('login'))
    
    student_id = session.get('student_id')  # รหัสบัตรนักศึกษา
    
    if request.method == "GET":
        with get_db_cursor() as (db, cursor):
            cursor.execute("""
                SELECT j.join_id, j.join_name, j.join_email, j.join_telephone, 
                       j.branch_id, b.branch_name, j.join_password
                FROM `join` j
                LEFT JOIN branch b ON j.branch_id = b.branch_id
                WHERE j.join_id = %s
            """, (student_id,))
            student_data = cursor.fetchone()
            
            if not student_data:
                flash("ไม่พบข้อมูลนักศึกษา", "error")
                return redirect(url_for("student_dashboard"))
            
            student = {
                'join_id': student_data[0],
                'join_name': student_data[1],
                'join_email': student_data[2],
                'join_telephone': student_data[3],
                'branch_id': student_data[4],
                'branch_name': student_data[5] if student_data[5] else 'ไม่ระบุสาขา',
                'has_password': bool(student_data[6])  # ตรวจสอบว่ามีรหัสผ่านหรือไม่
            }
            
        return render_template("student_profile.html", student=student)
    
    elif request.method == "POST":
        new_name = request.form.get("join_name", "").strip()
        new_email = request.form.get("join_email", "").strip()
        new_phone = request.form.get("join_telephone", "").strip()
        current_password = request.form.get("current_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        if not all([new_name, new_email, new_phone]):
            flash("กรุณากรอกข้อมูลให้ครบถ้วน", "error")
            return redirect(url_for("student_profile"))
        
        with get_db_cursor() as (db, cursor):
            cursor.execute(
                "SELECT join_name, join_email, join_telephone, join_password FROM `join` WHERE join_id = %s",
                (student_id,)
            )
            current_data = cursor.fetchone()
            
            if not current_data:
                flash("ไม่พบข้อมูลนักศึกษา", "error")
                return redirect(url_for("student_profile"))
            
            stored_password = current_data[3]
            changes_made = False
            update_fields = []
            update_values = []
            
            # ตรวจสอบการเปลี่ยนแปลงข้อมูลพื้นฐาน
            if new_name != current_data[0]:
                update_fields.append("join_name = %s")
                update_values.append(new_name)
                changes_made = True
                
            if new_email != current_data[1]:
                update_fields.append("join_email = %s")
                update_values.append(new_email)
                changes_made = True
                
            if new_phone != current_data[2]:
                update_fields.append("join_telephone = %s")
                update_values.append(new_phone)
                changes_made = True
            
            # ตรวจสอบการเปลี่ยนรหัสผ่าน
            if new_password:
                if new_password != confirm_password:
                    flash("รหัสผ่านใหม่และยืนยันรหัสผ่านไม่ตรงกัน", "error")
                    return redirect(url_for("student_profile"))
                
                if len(new_password) < 4:
                    flash("รหัสผ่านต้องมีอย่างน้อย 4 ตัวอักษร", "error")
                    return redirect(url_for("student_profile"))
                
                # ตรวจสอบรหัสผ่านปัจจุบัน (ถ้ามี)
                if stored_password:
                    if not current_password:
                        flash("กรุณากรอกรหัสผ่านปัจจุบัน", "error")
                        return redirect(url_for("student_profile"))
                    
                    password_valid = False
                    try:
                        if stored_password.startswith(('pbkdf2:', 'scrypt:', 'argon2:', '$')):
                            password_valid = check_password_hash(stored_password, current_password)
                        else:
                            password_valid = (stored_password == current_password)
                    except Exception as e:
                        password_valid = (stored_password == current_password)
                    
                    if not password_valid:
                        flash("รหัสผ่านปัจจุบันไม่ถูกต้อง", "error")
                        return redirect(url_for("student_profile"))
                
                # เข้ารหัสรหัสผ่านใหม่
                hashed_password = generate_password_hash(new_password)
                update_fields.append("join_password = %s")
                update_values.append(hashed_password)
                changes_made = True
            
            if not changes_made:
                flash("ไม่มีการเปลี่ยนแปลงข้อมูล", "info")
                return redirect(url_for("student_profile"))
            
            # อัพเดทข้อมูล
            try:
                query = f"UPDATE `join` SET {', '.join(update_fields)} WHERE join_id = %s"
                update_values.append(student_id)
                cursor.execute(query, update_values)
                db.commit()
                
                flash("อัพเดทข้อมูลส่วนตัวเรียบร้อยแล้ว", "success")
                
                # อัพเดท session หากมีการเปลี่ยนแปลง
                if new_name != current_data[0]:
                    session["student_name"] = new_name
                if new_email != current_data[1]:
                    session["student_email"] = new_email
                if new_phone != current_data[2]:
                    session["student_phone"] = new_phone
                
            except Exception as e:
                flash(f"เกิดข้อผิดพลาดในการอัพเดทข้อมูล: {str(e)}", "error")
                
        return redirect(url_for("student_profile"))
@app.route("/manage_evaluation_questions", methods=["GET", "POST"])
@login_required("admin")
def manage_evaluation_questions():
    """จัดการคำถามแบบประเมิน"""
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            question_text = request.form.get("question_text")
            question_category = request.form.get("question_category")
            question_order = request.form.get("question_order", type=int)
            
            with get_db_cursor() as (db, cursor):
                try:
                    cursor.execute("""
                        INSERT INTO system_constants 
                        (system_constants_question_text, system_constants_question_order, system_constants_question_category)
                        VALUES (%s, %s, %s)
                    """, (question_text, question_order, question_category))
                    db.commit()
                    flash("เพิ่มคำถามเรียบร้อยแล้ว", "success")
                except Exception as e:
                    flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        
        elif action == "update":
            question_id = request.form.get("question_id", type=int)
            question_text = request.form.get("question_text")
            question_category = request.form.get("question_category")
            question_order = request.form.get("question_order", type=int)
            is_active = request.form.get("is_active") == "1"
            
            with get_db_cursor() as (db, cursor):
                try:
                    cursor.execute("""
                        UPDATE system_constants 
                        SET system_constants_question_text = %s,
                            system_constants_question_category = %s,
                            system_constants_question_order = %s,
                            system_constants_is_active = %s
                        WHERE system_constants_id = %s
                    """, (question_text, question_category, question_order, is_active, question_id))
                    db.commit()
                    flash("อัปเดตคำถามเรียบร้อยแล้ว", "success")
                except Exception as e:
                    flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        
        elif action == "delete":
            question_id = request.form.get("question_id", type=int)
            
            with get_db_cursor() as (db, cursor):
                try:
                    cursor.execute("""
                        UPDATE system_constants 
                        SET system_constants_is_active = FALSE
                        WHERE system_constants_id = %s
                    """, (question_id,))
                    db.commit()
                    flash("ปิดใช้งานคำถามเรียบร้อยแล้ว", "success")
                except Exception as e:
                    flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        
        return redirect(url_for("manage_evaluation_questions"))
    
    # GET request - แสดงรายการคำถาม
    with get_db_cursor() as (db, cursor):
        cursor.execute("""
            SELECT system_constants_id, system_constants_question_text, 
                   system_constants_question_order, system_constants_question_category,
                   system_constants_is_active, system_constants_created_date
            FROM system_constants
            ORDER BY system_constants_question_order, system_constants_id
        """)
        questions = cursor.fetchall()
        
        # จัดกลุ่มคำถามตามหมวดหมู่
        questions_by_category = {}
        for q in questions:
            category = q[3]
            if category not in questions_by_category:
                questions_by_category[category] = []
            questions_by_category[category].append({
                'id': q[0],
                'text': q[1],
                'order': q[2],
                'category': q[3],
                'is_active': q[4],
                'created_date': q[5]
            })
    
    return render_template("manage_evaluation_questions.html", 
                         questions_by_category=questions_by_category)

@app.route("/get_evaluation_questions")
def get_evaluation_questions():
    """API สำหรับดึงคำถามแบบประเมินที่ใช้งานอยู่"""
    with get_db_cursor() as (db, cursor):
        cursor.execute("""
            SELECT system_constants_id, system_constants_question_text, 
                   system_constants_question_order, system_constants_question_category
            FROM system_constants
            WHERE system_constants_is_active = TRUE
            ORDER BY system_constants_question_order
        """)
        questions = cursor.fetchall()
        
        question_list = []
        for q in questions:
            question_list.append({
                'id': q[0],
                'text': q[1],
                'order': q[2],
                'category': q[3]
            })
    
    return jsonify({'questions': question_list})

# อัปเดตฟังก์ชันการประเมินโครงการ
@app.route("/evaluate_project/<int:project_id>", methods=["GET", "POST"])
def evaluate_project_updated(project_id):
    if 'user_type' not in session or session['user_type'] != 'student':
        flash('คุณต้องล็อกอินด้วยบัญชีนักศึกษาก่อน', 'error')
        return redirect(url_for('login'))
    
    student_id = session.get('student_id')
    student_name = session.get('student_name')
    
    with get_db_cursor() as (db, cursor):
        # ตรวจสอบโครงการและสิทธิ์
        cursor.execute("""
            SELECT p.project_name, a.project_statusStart
            FROM project p 
            JOIN approval a ON p.project_id = a.project_id
            WHERE p.project_id = %s
        """, (project_id,))
        project = cursor.fetchone()
        
        if not project:
            flash('ไม่พบโครงการ', 'error')
            return redirect(url_for('student_dashboard'))
        
        project_name = project[0]
        project_status = project[1]
        
        if project_status != 2:
            flash('โครงการยังไม่เสร็จสิ้น ไม่สามารถประเมินได้', 'warning')
            return redirect(url_for('student_dashboard'))
        
        # ตรวจสอบสิทธิ์การประเมิน
        cursor.execute("""
            SELECT sr.join_id 
            FROM status_register sr
            WHERE sr.project_id = %s 
            AND sr.status_register = 1 
            AND sr.join_id = %s
        """, (project_id, student_id))
        participant = cursor.fetchone()
        
        if not participant:
            flash('คุณไม่มีสิทธิ์ประเมินโครงการนี้', 'error')
            return redirect(url_for('student_dashboard'))
        
        # ตรวจสอบว่าประเมินแล้วหรือยัง
        cursor.execute("""
            SELECT COUNT(*) FROM project_evaluation 
            WHERE project_id = %s AND join_id = %s
        """, (project_id, student_id))
        already_evaluated = cursor.fetchone()[0] > 0
        
        if already_evaluated:
            flash('คุณได้ประเมินโครงการนี้ไปแล้ว', 'warning')
            return redirect(url_for('student_dashboard'))
        
        if request.method == "POST":
            try:
                # รับคะแนนจากแต่ละคำถาม
                detailed_scores = {}
                category_scores = {
                    'content': [],
                    'organization': [],
                    'instructor': [],
                    'overall': []
                }
                
                # ดึงคำถามทั้งหมด
                cursor.execute("""
                    SELECT system_constants_id, system_constants_question_category
                    FROM system_constants
                    WHERE system_constants_is_active = TRUE
                    ORDER BY system_constants_question_order
                """)
                active_questions = cursor.fetchall()
                
                total_score = 0
                question_count = 0
                
                for question_id, category in active_questions:
                    score_key = f'question_{question_id}'
                    score = request.form.get(score_key)
                    
                    if score:
                        score = int(score)
                        detailed_scores[score_key] = score
                        category_scores[category].append(score)
                        total_score += score
                        question_count += 1
                
                # คำนวณคะแนนเฉลี่ยตามหมวดหมู่
                content_avg = sum(category_scores['content']) / len(category_scores['content']) if category_scores['content'] else 0
                organization_avg = sum(category_scores['organization']) / len(category_scores['organization']) if category_scores['organization'] else 0
                instructor_avg = sum(category_scores['instructor']) / len(category_scores['instructor']) if category_scores['instructor'] else 0
                overall_avg = sum(category_scores['overall']) / len(category_scores['overall']) if category_scores['overall'] else 0
                
                # คะแนนรวมเฉลี่ย
                total_avg = total_score / question_count if question_count > 0 else 0
                
                evaluation_comments = request.form.get('evaluation_comments', '')
                detailed_scores_json = json.dumps(detailed_scores)
                
                # บันทึกการประเมิน
                cursor.execute("""
                    INSERT INTO project_evaluation 
                    (project_id, join_id, evaluation_score, evaluation_comments, 
                     project_evaluation_content_score, project_evaluation_organization_score,
                     project_evaluation_instructor_score, project_evaluation_overall_score,
                     project_evaluation_detailed_scores, evaluation_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (project_id, student_id, total_avg, evaluation_comments,
                     content_avg, organization_avg, instructor_avg, overall_avg,
                     detailed_scores_json))
                db.commit()
                
                flash('ขอบคุณสำหรับการประเมินโครงการ', 'success')
                return redirect(url_for('student_dashboard'))
                
            except Exception as e:
                flash(f'เกิดข้อผิดพลาดในการบันทึกข้อมูล: {str(e)}', 'error')
        
        # ดึงคำถามสำหรับแสดงในฟอร์ม
        cursor.execute("""
            SELECT system_constants_id, system_constants_question_text, 
                   system_constants_question_category
            FROM system_constants
            WHERE system_constants_is_active = TRUE
            ORDER BY system_constants_question_order
        """)
        questions = cursor.fetchall()
        
        # จัดกลุ่มคำถามตามหมวดหมู่
        questions_by_category = {}
        for q in questions:
            category = q[2]
            if category not in questions_by_category:
                questions_by_category[category] = []
            questions_by_category[category].append({
                'id': q[0],
                'text': q[1]
            })
        
        return render_template('project_evaluation_updated.html',
                             project_id=project_id,
                             project_name=project_name,
                             student_name=student_name,
                             questions_by_category=questions_by_category)
# อัปเดตฟังก์ชันดูผลการประเมิน
@app.route("/teacher_evaluation_project/<int:project_id>")
@login_required("teacher")
def teacher_evaluation_project_updated(project_id):
    with get_db_cursor() as (db, cursor):
        cursor.execute("""
            SELECT project_name, teacher_id 
            FROM project 
            WHERE project_id = %s
        """, (project_id,))
        project_info = cursor.fetchone()
        
        if not project_info:
            flash('ไม่พบโครงการ', 'error')
            return redirect(url_for('teacher_projects'))
        
        project_name, project_teacher_id = project_info
        
        if project_teacher_id != session.get('teacher_id'):
            flash('คุณไม่มีสิทธิ์ดูข้อมูลโครงการนี้', 'error')
            return redirect(url_for('teacher_projects'))
        
        # ดึงข้อมูลการประเมินพร้อมคะแนนแยกตามหมวดหมู่
        query = """
        SELECT 
            pe.evaluation_id,
            j.join_name,
            j.join_email,
            pe.evaluation_score,
            pe.project_evaluation_content_score,
            pe.project_evaluation_organization_score,
            pe.project_evaluation_instructor_score,
            pe.project_evaluation_overall_score,
            pe.evaluation_comments,
            pe.evaluation_date,
            pe.project_evaluation_detailed_scores
        FROM 
            project_evaluation pe
        JOIN 
            `join` j ON pe.join_id = j.join_id
        WHERE 
            pe.project_id = %s
        ORDER BY 
            pe.evaluation_date DESC
        """
        cursor.execute(query, (project_id,))
        evaluations = cursor.fetchall()
        
        # สรุปผลการประเมิน
        summary_query = """
        SELECT 
            COUNT(*) as total_evaluations,
            ROUND(AVG(evaluation_score), 2) as average_score,
            ROUND(AVG(project_evaluation_content_score), 2) as avg_content,
            ROUND(AVG(project_evaluation_organization_score), 2) as avg_organization,
            ROUND(AVG(project_evaluation_instructor_score), 2) as avg_instructor,
            ROUND(AVG(project_evaluation_overall_score), 2) as avg_overall,
            MIN(evaluation_score) as min_score,
            MAX(evaluation_score) as max_score
        FROM 
            project_evaluation
        WHERE 
            project_id = %s
        """
        cursor.execute(summary_query, (project_id,))
        summary = cursor.fetchone()
        
        evaluation_list = []
        for row in evaluations:
            evaluation_list.append({
                'evaluation_id': row[0],
                'join_name': row[1] or 'ไม่ระบุชื่อ',
                'join_email': row[2] or 'ไม่ระบุอีเมล',
                'evaluation_score': float(row[3] or 0),
                'content_score': float(row[4] or 0),
                'organization_score': float(row[5] or 0),
                'instructor_score': float(row[6] or 0),
                'overall_score': float(row[7] or 0),
                'evaluation_comments': row[8] or '',
                'evaluation_date': row[9],
                'detailed_scores': row[10] or '{}'
            })
        
        if summary:
            summary_data = {
                'total_evaluations': int(summary[0]) if summary[0] else 0,
                'average_score': float(summary[1] or 0),
                'avg_content': float(summary[2] or 0),
                'avg_organization': float(summary[3] or 0),
                'avg_instructor': float(summary[4] or 0),
                'avg_overall': float(summary[5] or 0),
                'min_score': float(summary[6] or 0),
                'max_score': float(summary[7] or 0)
            }
        else:
            summary_data = {
                'total_evaluations': 0,
                'average_score': 0,
                'avg_content': 0,
                'avg_organization': 0,
                'avg_instructor': 0,
                'avg_overall': 0,
                'min_score': 0,
                'max_score': 0
            }
    
    return render_template(
        'teacher_evaluation_project_detail_updated.html', 
        evaluations=evaluation_list,
        project_id=project_id,
        project_name=project_name,
        summary=summary_data
    )
# ตรวจสอบข้อมูลใหม่ทุกๆ 5 นาที
if __name__ == "__main__":
    init_scheduler(app)
    app.run(debug=True, port=5000)
