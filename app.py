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
def get_db_cursor():
    db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="project",
        connection_timeout=60,  # เพิ่มเวลา timeout
    )
    try:
        cursor = db.cursor(buffered=True)  # ใช้ buffered cursor
        yield db, cursor
    finally:
        cursor.close()
        db.close()


def get_db_connection():
    conn = mysql.connector.connect(
        host="localhost", user="root", password="", database="project"
    )
    cursor = conn.cursor(dictionary=True)
    return conn, cursor

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


@app.route("/")
def home():
    page = request.args.get("page", 1, type=int)
    per_page = 3  # จำนวน constants ต่อหน้า

    with get_db_cursor() as (db, cursor):
        cursor.execute("SELECT COUNT(*) FROM constants")
        total_constants = cursor.fetchone()[0]

        total_pages = ceil(total_constants / per_page)

        # ป้องกันการเข้าถึงหน้าที่ไม่มีอยู่
        page = max(1, min(page, total_pages))

        offset = (page - 1) * per_page
        query = "SELECT constants_headname, constants_detail, constants_image FROM constants LIMIT %s OFFSET %s"
        cursor.execute(query, (per_page, offset))
        constants = cursor.fetchall()

    constants = [
        (c[0], c[1], base64.b64encode(c[2]).decode("utf-8")) for c in constants
    ]

    return render_template(
        "home.html", constants=constants, page=page, total_pages=total_pages
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_type = request.form.get("login_type", "staff")  # ค่าเริ่มต้นเป็น staff
        
        if login_type == "staff":
            # ล็อกอินสำหรับอาจารย์/แอดมิน
            username = request.form["username"]
            password = request.form["password"]

            with get_db_cursor() as (db, cursor):
                query_teacher = "SELECT * FROM teacher WHERE teacher_username = %s"
                cursor.execute(query_teacher, (username,))
                teacher = cursor.fetchone()

                if teacher and check_password_hash(teacher[3], password):  # ตำแหน่งที่ 3 คือ teacher_password
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

                    if admin and check_password_hash(admin[3], password):  # ตำแหน่งที่ 3 คือ admin_password
                        session.clear()
                        session["admin_id"] = admin[0]
                        session["admin_name"] = admin[1]
                        session["admin_email"] = admin[4]
                        session["user_type"] = "admin"
                        return redirect(url_for("admin_home"))
                    else:
                        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "danger")
        
        elif login_type == "student":
            # ล็อกอินสำหรับนักศึกษา
            student_id = request.form.get("student_id")
            phone = request.form.get("phone")
            
            if not student_id or not phone:
                flash("กรุณากรอกข้อมูลให้ครบถ้วน", "danger")
                return render_template("login.html")
            
            with get_db_cursor() as (db, cursor):
                # ตรวจสอบข้อมูลนักศึกษาที่ได้รับการอนุมัติแล้ว
                query = """
                SELECT j.join_id, j.join_name, j.join_email, j.join_telephone, j.branch_id, 
                       b.branch_name, j.join_student_id, j.project_id
                FROM `join` j
                LEFT JOIN branch b ON j.branch_id = b.branch_id
                WHERE j.join_student_id = %s AND j.join_telephone = %s AND j.join_status = 1
                ORDER BY j.join_timestamp DESC
                LIMIT 1
                """
                cursor.execute(query, (student_id, phone))
                student = cursor.fetchone()
                
                if not student:
                    flash("ไม่พบข้อมูลหรือยังไม่ได้รับการอนุมัติ กรุณาตรวจสอบรหัสนักศึกษาและเบอร์โทรศัพท์อีกครั้ง", "danger")
                    return render_template("login.html")
                
                # เก็บข้อมูลใน session
                session.clear()
                session["student_id"] = student[6]  # join_student_id
                session["student_name"] = student[1]  # join_name
                session["student_email"] = student[2]  # join_email
                session["student_phone"] = student[3]  # join_telephone
                session["student_branch_id"] = student[4]  # branch_id
                session["student_branch"] = student[5] if student[5] else "ไม่ระบุสาขา"  # branch_name
                session["user_type"] = "student"  # ระบุประเภทผู้ใช้เป็นนักศึกษา
                
                flash(f"ยินดีต้อนรับ {student[1]}", "success")
                return redirect(url_for("student_dashboard"))

    return render_template("login.html")
@app.route("/student_dashboard")
def student_dashboard():
    if "student_id" not in session or session.get("user_type") != "student":
        flash("กรุณาเข้าสู่ระบบก่อน", "danger")
        return redirect(url_for("login"))
    
    student_id = session.get("student_id")
    student_email = session.get("student_email")
    
    with get_db_cursor() as (db, cursor):
        # ดึงโครงการที่นักศึกษาลงทะเบียนไว้แล้ว
        query = """
        SELECT j.join_id, j.join_status, p.project_id, p.project_name, p.project_dotime, 
               p.project_endtime, p.project_statusStart, p.project_address, t.teacher_name,
               (SELECT COUNT(*) FROM project_evaluation pe WHERE pe.join_id = j.join_id) as has_evaluated
        FROM `join` j
        JOIN project p ON j.project_id = p.project_id
        JOIN teacher t ON p.teacher_id = t.teacher_id
        WHERE j.join_student_id = %s
        ORDER BY j.join_timestamp DESC
        """
        cursor.execute(query, (student_id,))
        registered_projects = cursor.fetchall()
        
        # แปลงข้อมูลให้อยู่ในรูปแบบที่ใช้งานง่าย
        projects = []
        for p in registered_projects:
            projects.append({
                "join_id": p[0],
                "join_status": p[1],
                "project_id": p[2],
                "project_name": p[3],
                "project_dotime": p[4],
                "project_endtime": p[5],
                "project_statusStart": p[6],
                "project_address": p[7],
                "teacher_name": p[8],
                "has_evaluated": p[9] > 0
            })
        
        # ดึงโครงการที่เปิดรับสมัคร (อนุมัติแล้ว และยังไม่เสร็จสิ้น)
        query = """
        SELECT p.project_id, p.project_name, p.project_dotime, p.project_endtime, 
               p.project_target, p.project_address, t.teacher_name,
               (SELECT COUNT(*) FROM `join` WHERE project_id = p.project_id) as current_count,
               (SELECT COUNT(*) FROM `join` WHERE project_id = p.project_id AND join_student_id = %s) as already_joined
        FROM project p
        JOIN teacher t ON p.teacher_id = t.teacher_id
        WHERE p.project_status = 2 AND p.project_statusStart = 1
        ORDER BY p.project_dotime ASC
        """
        cursor.execute(query, (student_id,))
        available_projects = cursor.fetchall()
        
        # แปลงข้อมูล
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

    # ดึงข้อมูล constants สำหรับการแสดงผล
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
    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {err}", "danger")
        constants = []
        total_pages = 1

    return render_template("admin_home.html", constants=constants, page=page, total_pages=total_pages, search_query=search_query)
@app.route("/approve_project", methods=["GET", "POST"])
@login_required("admin")
def approve_project():
    if not g.user or g.user["type"] != "admin":
        return redirect(url_for("login"))

    if request.method == "POST":
        project_id = request.form.get("project_id")
        action = request.form.get("action")
        
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลโครงการและอาจารย์
            cursor.execute("""
                SELECT p.project_name, t.teacher_name
                FROM project p
                JOIN teacher t ON p.teacher_id = t.teacher_id
                WHERE p.project_id = %s
            """, (project_id,))
            result = cursor.fetchone()
            if result:
                project_name, teacher_name = result
            else:
                project_name, teacher_name = "ไม่ทราบชื่อโครงการ", "ไม่ทราบชื่อ"

            if action == "approve":
                new_status = 2
                status_text = "อนุมัติ"
                query = "UPDATE project SET project_status = %s, project_approve_date = NOW() WHERE project_id = %s"
                cursor.execute(query, (new_status, project_id))
            elif action == "reject":
                new_status = 3
                status_text = "ตีกลับ"
                reason = request.form.get("reason", "")
                query = "UPDATE project SET project_status = %s, project_reject = %s, project_reject_date = NOW() WHERE project_id = %s"
                cursor.execute(query, (new_status, reason, project_id))
            else:
                status_text = "ไม่ทราบสถานะ"
            
            db.commit()

        # ลบส่วนเกี่ยวกับการส่งอีเมลออกทั้งหมด
        flash(f'โครงการได้รับการ{status_text}แล้ว', 'success')
        return redirect(url_for("approve_project"))

    page = request.args.get("page", 1, type=int)
    per_page = 6  # จำนวนโปรเจคต่อหน้า
    search_query = request.args.get("search", "")
    approval_filter = request.args.get("approval", "all")

    with get_db_cursor() as (db, cursor):
        base_query = """
        SELECT p.project_id, p.project_name, p.project_status, 
               CASE WHEN p.project_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_pdf,
               p.project_submit_date, p.project_approve_date, p.project_reject_date
        FROM project p
        """
        count_query = "SELECT COUNT(*) FROM project p"
        where_clauses = []
        query_params = []

        if approval_filter == "approved":
            where_clauses.append("p.project_status = 2")
        elif approval_filter == "pending":
            where_clauses.append("p.project_status = 1")
        elif approval_filter == "unapproved":
            where_clauses.append("p.project_status = 0")

        if search_query:
            where_clauses.append("p.project_name LIKE %s")
            query_params.append(f"%{search_query}%")

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)
            count_query += " WHERE " + " AND ".join(where_clauses)

        # Count total projects
        cursor.execute(count_query, query_params)
        total_projects = cursor.fetchone()[0]

        # Calculate total pages
        total_pages = ceil(total_projects / per_page)

        # Get projects for current page
        base_query += " ORDER BY p.project_id DESC LIMIT %s OFFSET %s"
        query_params.extend([per_page, (page - 1) * per_page])

        cursor.execute(base_query, query_params)
        projects = cursor.fetchall()
        
        # ดึงข้อมูลเหตุผลการตีกลับของโครงการที่รออนุมัติในหน้านี้
        project_prev_reject = {}
        pending_project_ids = [p[0] for p in projects if p[2] == 1]  # ดึง ID ของโครงการสถานะ "รออนุมัติ"
        
        if pending_project_ids:
            placeholders = ', '.join(['%s'] * len(pending_project_ids))
            cursor.execute(
                f"""
                SELECT p.project_id, p.project_reject 
                FROM project p
                WHERE p.project_id IN ({placeholders})
                AND p.project_reject IS NOT NULL AND p.project_reject != ''
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
        project_prev_reject=project_prev_reject  # ส่งข้อมูลเหตุผลการตีกลับครั้งก่อนไปยัง template
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
@app.route("/student_history/<student_id>")
def student_history(student_id):
    # ถ้าล็อกอินด้วยนักศึกษา ให้ใช้รหัสนักศึกษาจากเซสชัน
    if session.get("user_type") == "student":
        # ถ้าพยายามดูประวัติของนักศึกษาคนอื่น
        if student_id != session.get("student_id"):
            flash("คุณไม่มีสิทธิ์ดูข้อมูลของนักศึกษาคนอื่น", "danger")
            return redirect(url_for("student_dashboard"))
    
    # ถ้าเป็นอาจารย์หรือแอดมิน ให้ใช้รหัสนักศึกษาที่ส่งมา
    search_done = True  # ให้แสดงข้อมูลเลย ไม่ต้องกดค้นหา
    
    projects = []
    student_info = None
    
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลนักศึกษา
        cursor.execute("""
            SELECT join_name, join_email, join_telephone, branch_id, 
                   (SELECT branch_name FROM branch WHERE branch_id = j.branch_id) as branch_name
            FROM `join` j
            WHERE join_student_id = %s
            LIMIT 1
        """, (student_id,))
        student_info = cursor.fetchone()
        
        # ดึงประวัติการเข้าร่วมโครงการ
        cursor.execute("""
            SELECT j.join_id, j.join_status, j.join_timestamp, 
                   p.project_id, p.project_name, p.project_dotime, p.project_endtime,
                   p.project_statusStart
            FROM `join` j
            JOIN project p ON j.project_id = p.project_id
            WHERE j.join_student_id = %s
            ORDER BY j.join_timestamp DESC
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
            # ดึงข้อมูลโครงการ
            cursor.execute(
                "SELECT project_name, project_target FROM project WHERE project_id = %s",
                (project_id,),
            )
            project = cursor.fetchone()

            if not project:
                flash("โครงการไม่พบ", "error")
                return redirect(url_for("active_projects"))

            # ตรวจสอบจำนวนผู้เข้าร่วมปัจจุบัน
            cursor.execute(
                "SELECT COUNT(*) as current_count FROM `join` WHERE project_id = %s",
                (project_id,),
            )
            result = cursor.fetchone()
            current_count = result[0] if isinstance(result, tuple) else result[0]

            if current_count >= project[1]:
                flash("ขออภัย โครงการนี้มีผู้เข้าร่วมเต็มแล้ว", "error")
                return redirect(url_for("project_detail", project_id=project_id))
            
            # ดึงข้อมูลสาขาสำหรับแสดงในฟอร์ม
            cursor.execute("SELECT branch_id, branch_name FROM branch ORDER BY branch_name")
            branches = cursor.fetchall()

            if request.method == "POST":
                registration_type = request.form.get("registrationType")
                student_id = request.form.get("student_id")
                
                # ตรวจสอบว่ามีรหัสนักศึกษานี้ในโครงการแล้วหรือไม่
                cursor.execute(
                    "SELECT COUNT(*) as count FROM `join` WHERE project_id = %s AND join_student_id = %s",
                    (project_id, student_id)
                )
                result = cursor.fetchone()
                count = result[0] if isinstance(result, tuple) else result[0]
                
                if count > 0:
                    flash(f"รหัสนักศึกษา {student_id} ได้ลงทะเบียนเข้าร่วมโครงการนี้แล้ว", "error")
                    return render_template(
                        "join_project.html",
                        project=project,
                        project_id=project_id,
                        current_count=current_count,
                        branches=branches
                    )
                
                if registration_type == "returning":
                    # นักศึกษาที่เคยเข้าร่วมโครงการแล้ว ดึงข้อมูลจากฐานข้อมูล
                    cursor.execute(
                        """
                        SELECT join_name, join_email, join_telephone, branch_id 
                        FROM `join` 
                        WHERE join_student_id = %s
                        LIMIT 1
                        """, 
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
                        
                    join_name = student[0] if len(student) > 0 else ""
                    join_email = student[1] if len(student) > 1 else ""
                    join_telephone = student[2] if len(student) > 2 else ""
                    branch_id = student[3] if len(student) > 3 else None
                    
                else:
                    # นักศึกษาใหม่ รับข้อมูลจากฟอร์ม
                    join_name = request.form["join_name"]
                    join_telephone = request.form["join_telephone"]
                    join_email = request.form["join_email"]
                    branch_id = request.form.get("branch_id")

                # เพิ่ม print debug
                print(f"Data to insert: name={join_name}, email={join_email}, phone={join_telephone}, branch={branch_id}")
                
                try:
                    cursor.execute(
                        """
                        INSERT INTO `join` (join_name, join_telephone, join_email, 
                                          branch_id, join_student_id, project_id, join_status, join_timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, 0, NOW())
                        """,
                        (join_name, join_telephone, join_email, branch_id, student_id, project_id),
                    )
                    db.commit()
                    flash("คุณได้ลงทะเบียนเข้าร่วมโครงการเรียบร้อยแล้ว โปรดรอการอนุมัติ", "success")
                except mysql.connector.Error as err:
                    print(f"Error during insert: {err}")
                    flash(f"เกิดข้อผิดพลาดในการลงทะเบียน: {err}", "error")

                return redirect(url_for("project_detail", project_id=project_id))

            return render_template(
                "join_project.html",
                project=project,
                project_id=project_id,
                current_count=current_count,
                branches=branches
            )
            
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
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

def generate_confirmation_token(join_id, email):
    # สร้างโทเค็นอย่างง่ายจาก join_id และ email
    import hashlib
    token = hashlib.md5(f"{join_id}:{email}:{app.secret_key}".encode()).hexdigest()
    print(f"สร้างโทเค็นสำหรับ join_id: {join_id}, email: {email}, token: {token}")
    return token


# ฟังก์ชันแรก - อัพเดทสถานะแต่ละคน
@app.route("/update_join_status/<int:join_id>", methods=["POST"])
@login_required("teacher", "admin")
def update_join_status(join_id):
    try:
        join_status = int(request.form.get('join_status', 0))
        project_id = None
        
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลผู้เข้าร่วมและโครงการ
            cursor.execute(
                """
                SELECT j.project_id, j.join_status, p.project_target, p.teacher_id,
                       (SELECT COUNT(*) FROM `join` WHERE project_id = j.project_id AND join_status = 1) as current_approved
                FROM `join` j
                JOIN project p ON j.project_id = p.project_id
                WHERE j.join_id = %s
                """,
                (join_id,)
            )
            participant_info = cursor.fetchone()
            
            if not participant_info:
                flash("ไม่พบข้อมูลผู้เข้าร่วม", "error")
                return redirect(url_for("admin_home"))
                
            project_id = participant_info[0]
            old_status = participant_info[1]
            max_participants = int(participant_info[2]) if participant_info[2] else 0
            project_teacher_id = participant_info[3]
            current_approved = participant_info[4]
            
            # ตรวจสอบสิทธิ์ในการอนุมัติ
            user_type = session.get("user_type", "")
            logged_in_teacher_id = session.get("teacher_id") if user_type == "teacher" else None
            
            # เป็นอาจารย์เจ้าของโครงการหรือไม่
            is_project_owner = logged_in_teacher_id and str(logged_in_teacher_id) == str(project_teacher_id)
            is_admin = user_type == "admin"
            
            if not (is_project_owner or is_admin):
                flash("คุณไม่มีสิทธิ์ในการอนุมัติผู้เข้าร่วมโครงการนี้", "error")
                return redirect(url_for("project_participants", project_id=project_id))
            
            # ตรวจสอบกรณีเปลี่ยนจากสถานะอื่นเป็นอนุมัติ
            if join_status == 1 and old_status != 1:
                # ตรวจสอบว่าจำนวนเต็มหรือยัง
                if current_approved >= max_participants:
                    flash(f"ไม่สามารถอนุมัติได้เนื่องจากโครงการเต็มแล้ว ({current_approved}/{max_participants})", "warning")
                    return redirect(url_for("project_participants", project_id=project_id))
            
            # อัปเดตสถานะ
            cursor.execute(
                "UPDATE `join` SET join_status = %s WHERE join_id = %s",
                (join_status, join_id)
            )
            db.commit()
            
            status_text = ""
            if join_status == 0:
                status_text = "รอการอนุมัติ"
            elif join_status == 1:
                status_text = "อนุมัติแล้ว"
            elif join_status == 2:
                status_text = "ไม่อนุมัติ"
                
            flash(f"อัปเดตสถานะผู้เข้าร่วมเป็น '{status_text}' เรียบร้อยแล้ว", "success")
                
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        
    if project_id:
        return redirect(url_for("project_participants", project_id=project_id))
    else:
        return redirect(url_for("admin_home"))
@app.route("/project/<int:project_id>/approve_all", methods=["POST"])
@login_required("teacher", "admin")
def approve_all_participants(project_id):
    try:
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลโครงการเพื่อตรวจสอบสิทธิ์และจำนวนที่รับได้
            cursor.execute(
                "SELECT project_target, teacher_id FROM project WHERE project_id = %s",
                (project_id,)
            )
            project = cursor.fetchone()
            
            if not project:
                flash("ไม่พบข้อมูลโครงการ", "error")
                return redirect(url_for("project_participants", project_id=project_id))
            
            max_participants = int(project[0]) if project[0] else 0
            project_teacher_id = project[1]
            
            # ตรวจสอบสิทธิ์ในการอนุมัติ
            user_type = session.get("user_type", "")
            logged_in_teacher_id = session.get("teacher_id") if user_type == "teacher" else None
            
            # เป็นอาจารย์เจ้าของโครงการหรือไม่
            is_project_owner = logged_in_teacher_id and str(logged_in_teacher_id) == str(project_teacher_id)
            is_admin = user_type == "admin"
            
            if not (is_project_owner or is_admin):
                flash("คุณไม่มีสิทธิ์ในการอนุมัติผู้เข้าร่วมโครงการนี้", "error")
                return redirect(url_for("project_participants", project_id=project_id))
            
            # ตรวจสอบจำนวนผู้เข้าร่วมที่อนุมัติแล้ว
            cursor.execute(
                "SELECT COUNT(*) FROM `join` WHERE project_id = %s AND join_status = 1",
                (project_id,)
            )
            current_approved = cursor.fetchone()[0]
            
            # หาจำนวนที่ยังสามารถอนุมัติได้อีก
            remaining_slots = max_participants - current_approved
            
            if remaining_slots <= 0:
                flash(f"โครงการนี้เต็มแล้ว ไม่สามารถอนุมัติผู้เข้าร่วมเพิ่มได้", "warning")
                return redirect(url_for("project_participants", project_id=project_id))
            
            # ดึงรายชื่อผู้ที่รออนุมัติเรียงตามเวลาที่สมัคร
            cursor.execute(
                """
                SELECT join_id, join_timestamp 
                FROM `join` 
                WHERE project_id = %s AND join_status = 0
                ORDER BY join_timestamp ASC
                """,
                (project_id,)
            )
            waiting_participants = cursor.fetchall()
            
            # อนุมัติตามจำนวนที่เหลือ
            approved_count = 0
            for participant in waiting_participants:
                if approved_count >= remaining_slots:
                    break
                
                cursor.execute(
                    "UPDATE `join` SET join_status = 1 WHERE join_id = %s",
                    (participant[0],)
                )
                approved_count += 1
            
            db.commit()
            
            if approved_count > 0:
                flash(f"อนุมัติผู้เข้าร่วม {approved_count} คน เรียบร้อยแล้ว", "success")
            else:
                flash("ไม่มีผู้เข้าร่วมที่รออนุมัติ", "info")
                
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
        
    return redirect(url_for("project_participants", project_id=project_id))
# ฟังก์ชันแสดงรายชื่อผู้เข้าร่วม
@app.route("/project/<int:project_id>/participants")
def project_participants(project_id):
    try:
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลโครงการ
            cursor.execute("""
                SELECT p.project_id, p.project_name, p.project_style, p.project_dotime, p.project_endtime, 
                       p.project_target, p.project_status, p.project_detail, p.project_budgettype, p.project_year,
                       p.teacher_id
                FROM project p
                WHERE p.project_id = %s
            """, (project_id,))
            project_data = cursor.fetchone()
            
            if not project_data:
                flash("ไม่พบข้อมูลโครงการ", "error")
                return redirect(url_for("home"))
            
            # ตรวจสอบว่ามีผู้เข้าร่วมกี่คนที่อนุมัติแล้ว
            cursor.execute(
                "SELECT COUNT(*) FROM `join` WHERE project_id = %s AND join_status = 1",
                (project_id,)
            )
            approved_count = cursor.fetchone()[0]
            
            # ตรวจสอบการเชื่อมต่อกับข้อมูลอาจารย์
            cursor.execute("""
                SELECT t.teacher_id, t.teacher_name, t.teacher_email, t.teacher_phone, b.branch_name
                FROM project p
                JOIN teacher t ON p.teacher_id = t.teacher_id
                JOIN branch b ON t.branch_id = b.branch_id
                WHERE p.project_id = %s
            """, (project_id,))
            teacher_data = cursor.fetchone()
            
            # ดึงข้อมูลผู้เข้าร่วม
            cursor.execute(
                """
                SELECT j.join_id, j.join_name, j.join_email, j.join_telephone, j.join_status,
                       j.branch_id, b.branch_name, j.join_student_id, j.join_timestamp
                FROM `join` j
                LEFT JOIN branch b ON j.branch_id = b.branch_id
                WHERE j.project_id = %s
                ORDER BY j.join_status, j.join_timestamp
                """,
                (project_id,)
            )
            participants_raw = cursor.fetchall()
            
            # แปลงข้อมูลจาก tuple เป็น dictionary
            participants = []
            for p in participants_raw:
                participants.append({
                    'join_id': p[0], 
                    'join_name': p[1],
                    'join_email': p[2],
                    'join_telephone': p[3],
                    'join_status': p[4],
                    'branch_id': p[5],
                    'branch_name': p[6] if p[6] else "ไม่ระบุสาขา",
                    'join_student_id': p[7],
                    'join_timestamp': p[8],
                    'join_role': 'student'  # ค่าเริ่มต้น
                })
            
            # แปลง project_data เป็น dictionary
            project = {
                'project_id': project_data[0],
                'project_name': project_data[1],
                'project_style': project_data[2],
                'project_dotime': project_data[3],
                'project_endtime': project_data[4],
                'project_target': project_data[5],
                'project_status': project_data[6],
                'project_detail': project_data[7],
                'project_budgettype': project_data[8],
                'project_year': project_data[9],
                'teacher_id': project_data[10]
            }
            
            # แปลง teacher_data เป็น dictionary (ถ้ามี)
            teacher = None
            if teacher_data:
                teacher = {
                    'teacher_id': teacher_data[0],
                    'teacher_name': teacher_data[1],
                    'teacher_email': teacher_data[2],
                    'teacher_phone': teacher_data[3],
                    'branch_name': teacher_data[4]
                }

            # เช็คสิทธิ์ในการอนุมัติ
            is_logged_in = "user_type" in session
            user_type = session.get("user_type", "")
            logged_in_teacher_id = session.get("teacher_id") if user_type == "teacher" else None
            
            # เป็นอาจารย์เจ้าของโครงการหรือไม่
            is_project_owner = logged_in_teacher_id and str(logged_in_teacher_id) == str(project['teacher_id'])
            
            # เป็นแอดมินหรือไม่
            is_admin = user_type == "admin"
            
            # สามารถอนุมัติได้หรือไม่
            can_approve = is_admin or is_project_owner
            
            # คำนวณที่เหลือ
            available_slots = int(project['project_target']) - approved_count if project['project_target'] else 0
            
            # สร้างเทมเพลต
            return render_template(
                "project_participants.html",
                project_id=project_id,
                project=project,
                teacher=teacher,
                participants=participants,
                is_logged_in=is_logged_in,
                user_type=user_type,
                is_project_owner=is_project_owner,
                is_admin=is_admin,
                can_approve=can_approve,
                current_approved=approved_count,
                available_slots=available_slots,
                total_participants=len(participants)
            )
            
    except Exception as e:
        print(f"Error in project_participants: {str(e)}")
        import traceback
        traceback.print_exc()
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


@app.route("/download_project_pdf/<int:project_id>")
@login_required("teacher", "admin")
def download_project_pdf(project_id):
    user_type = g.user["type"]

    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลโครงการ
        if user_type == "teacher":
            teacher_id = g.user["id"]
            query = """
                SELECT project_pdf, project_name, 
                       project_budgettype, project_year, project_style, project_address, 
                       project_dotime, project_endtime, project_target, project_budget, 
                       project_detail, project_output, project_strategy, project_indicator,
                       project_cluster, project_commonality, project_physical_grouping,
                       project_rationale, project_objectives, project_goals, 
                       project_output_target, project_outcome_target, project_activity,
                       project_activities_json, project_quantity_indicator, project_quality_indicator,
                       project_time_indicator, project_cost_indicator, project_expected_results,
                       project_compensation_json, project_expenses_json
                FROM project 
                WHERE project_id = %s AND teacher_id = %s
            """
            cursor.execute(query, (project_id, teacher_id))
        else:  # admin
            query = """
                SELECT project_pdf, project_name, 
                       project_budgettype, project_year, project_style, project_address, 
                       project_dotime, project_endtime, project_target, project_budget, 
                       project_detail, project_output, project_strategy, project_indicator,
                       project_cluster, project_commonality, project_physical_grouping,
                       project_rationale, project_objectives, project_goals, 
                       project_output_target, project_outcome_target, project_activity,
                       project_activities_json, project_quantity_indicator, project_quality_indicator,
                       project_time_indicator, project_cost_indicator, project_expected_results,
                       project_compensation_json, project_expenses_json
                FROM project 
                WHERE project_id = %s
            """
            cursor.execute(query, (project_id,))

        result = cursor.fetchone()

        if result and result[0]:  # มี PDF ในฐานข้อมูล
            pdf_content = result[0]
            project_name = result[1]
            
            # ตรวจสอบว่า PDF ถูกต้องหรือไม่
            if verify_pdf(pdf_content):
                return send_file(
                    BytesIO(pdf_content),
                    as_attachment=True,
                    download_name=f"{project_name}.pdf",
                    mimetype="application/pdf",
                )
            else:
                # ถ้า PDF ไม่ถูกต้อง ให้สร้างใหม่
                project_data = {
                    "project_name": result[1],
                    "project_budgettype": result[2],
                    "project_year": result[3],
                    "project_style": result[4],
                    "project_address": result[5],
                    "project_dotime": result[6],
                    "project_endtime": result[7],
                    "project_target": result[8],
                    "project_budget": result[9],
                    "project_detail": result[10],
                    "project_output": result[11],
                    "strategy": result[12],
                    "indicator": result[13],
                    "cluster": result[14],
                    "commonality": result[15],
                    "physical_grouping": result[16],
                    "rationale": result[17],
                    "objectives": result[18],
                    "goals": result[19],
                    "output_target": result[20],
                    "outcome_target": result[21],
                    "project_activity": result[22],
                }
                
                # แปลง JSON strings
                try:
                    if result[23]:  # project_activities_json
                        project_data["activities"] = json.loads(result[23])
                except:
                    project_data["activities"] = []
                    
                project_data["quantity_indicator"] = result[24]
                project_data["quality_indicator"] = result[25]
                project_data["time_indicator"] = result[26]
                project_data["cost_indicator"] = result[27]
                project_data["expected_results"] = result[28]
                
                try:
                    if result[29]:  # project_compensation_json
                        project_data["compensation"] = json.loads(result[29])
                except:
                    project_data["compensation"] = []
                    
                try:
                    if result[30]:  # project_expenses_json
                        project_data["expenses"] = json.loads(result[30])
                except:
                    project_data["expenses"] = []
                
                # สร้าง PDF ใหม่
                pdf_buffer = create_project_pdf(project_data)
                if pdf_buffer:
                    new_pdf_content = pdf_buffer.getvalue()
                    
                    # บันทึกลงฐานข้อมูล
                    update_query = "UPDATE project SET project_pdf = %s WHERE project_id = %s"
                    cursor.execute(update_query, (new_pdf_content, project_id))
                    db.commit()
                    
                    return send_file(
                        BytesIO(new_pdf_content),
                        as_attachment=True,
                        download_name=f"{project_name}.pdf",
                        mimetype="application/pdf",
                    )
        else:
            # ไม่มี PDF หรือไม่พบโครงการ
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
                # เพิ่มรหัสโครงการ
                project_id = project_data.get('project_id', '')
                canvas.drawCentredString(
                    page_width / 2, text_y, f"รหัสโครงการ {project_id}"
                )
            
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

        # เริ่มสร้างตาราง
        current_fiscal_year = project_data.get('project_year', '2567')  # ปีงบประมาณปัจจุบัน
        next_fiscal_year = str(int(current_fiscal_year) + 1)  # ปีงบประมาณถัดไป

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

        activity_data = []

        # แถวแรก: หัวตาราง - กิจกรรมดำเนินงาน, แถวแรกว่าง
        header_row = ['กิจกรรมดำเนินงาน', f'ปี พ.ศ. {current_fiscal_year}', f'ปี พ.ศ. {next_fiscal_year}']
        activity_data.append(header_row)

        # แถวที่สอง: เดือนต่างๆ
        month_row = [''] + thai_months
        activity_data.append(month_row)

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
            ('SPAN', (1, 0), (3, 0)),  # รวมเซลล์ไตรมาสแรก (ปี 2567)
            ('SPAN', (4, 0), (-1, 0)),  # รวมเซลล์เดือนที่เหลือ (ปี 2568)
            
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
        
        # ดึงข้อมูลโครงการที่เสร็จสิ้น (project_statusStart = 2)
        # รับพารามิเตอร์กรองจาก URL
        branch_id = request.args.get("branch", "all")
        year = request.args.get("year", "all")
        budget_type = request.args.get("budget_type", "all")
        policy = request.args.get("policy", "all")
        
        # สร้าง query พื้นฐาน
        base_query = """
            SELECT p.project_id, p.project_name, p.project_year, p.project_budgettype,
                   p.project_dotime, p.project_endtime, p.project_close_date,
                   p.project_budget, p.project_policy, t.teacher_name, b.branch_name
            FROM project p
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN branch b ON t.branch_id = b.branch_id
            WHERE p.project_statusStart = 2
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
        base_query += " ORDER BY p.project_close_date DESC"
        
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
        policy_stats=policy_stats
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
            "UPDATE project SET project_statusStart = 2, project_close_date = NOW() WHERE project_id = %s",
            (project_id,)
        )
        db.commit()
        
        flash("ปิดโครงการเรียบร้อยแล้ว", "success")
        
    return redirect(url_for("teacher_projects"))
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
        # ดึงข้อมูลโครงการเดิม
        query = """SELECT project_id, project_budgettype, project_year, project_name, 
                   project_style, project_address, project_dotime, project_endtime, 
                   project_target, project_status, project_budget, project_detail,
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
        "project_status": project[9],
        "project_budget": project[10],
        "project_detail": project[11],
        "project_output": project[12],
        "project_strategy": project[13],
        "project_indicator": project[14],
        "project_cluster": project[15],
        "project_commonality": project[16],
        "project_physical_grouping": project[17],
        "project_rationale": project[18],
        "project_objectives": project[19],
        "project_goals": project[20],
        "project_output_target": project[21],
        "project_outcome_target": project[22],
        "project_activity": project[23],
        "project_activities_json": project[24],
        "project_quantity_indicator": project[25],
        "project_quality_indicator": project[26],
        "project_time_indicator": project[27],
        "project_cost_indicator": project[28],
        "project_expected_results": project[29],
        "project_compensation_json": project[30],
        "project_expenses_json": project[31],
        "project_policy": project[32] if len(project) > 32 else "",
        "policy": project[32] if len(project) > 32 else "",
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
                "output": request.form["output"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_strategy": request.form["strategy"],
                "strategy": request.form["strategy"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_indicator": request.form["indicator"],
                "indicator": request.form["indicator"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_cluster": request.form["cluster"],
                "cluster": request.form["cluster"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_commonality": request.form["commonality"],
                "commonality": request.form["commonality"], 
                "project_physical_grouping": request.form["physical_grouping"],
                "physical_grouping": request.form["physical_grouping"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_rationale": request.form["rationale"],
                "rationale": request.form["rationale"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_objectives": request.form["objectives"],
                "objectives": request.form["objectives"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_goals": request.form["goals"],
                "goals": request.form["goals"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_output_target": request.form["output_target"],
                "output_target": request.form["output_target"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_outcome_target": request.form["outcome_target"],
                "outcome_target": request.form["outcome_target"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_activity": request.form["project_activity"],
                "project_quantity_indicator": request.form["quantity_indicator"],
                "quantity_indicator": request.form["quantity_indicator"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_quality_indicator": request.form["quality_indicator"],
                "quality_indicator": request.form["quality_indicator"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_time_indicator": request.form["time_indicator"],
                "time_indicator": request.form["time_indicator"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_cost_indicator": request.form["cost_indicator"],
                "cost_indicator": request.form["cost_indicator"],  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_expected_results": request.form.get("expected_results", ""),
                "expected_results": request.form.get("expected_results", ""),  # เพิ่มเพื่อให้แน่ใจว่ามีทั้งสองฟิลด์
                "project_policy": request.form.get("policy", ""),
                "policy": request.form.get("policy", ""),
            }
        )

        error_messages = []

        # ตรวจสอบชื่อโครงการซ้ำ
        if project_data["project_name"] != project[3]:  # ถ้าชื่อโครงการมีการเปลี่ยนแปลง
            if is_project_name_duplicate(project_data["project_name"], project_id):
                error_messages.append("ไม่สามารถแก้ไขโครงการได้เนื่องจากชื่อโครงการ '{}' มีอยู่แล้ว กรุณาใช้ชื่อโครงการอื่น".format(project_data["project_name"]))

        # ตรวจสอบวันที่ซ้ำสำหรับครูคนเดียวกัน
        if is_date_overlap_for_teacher(teacher_id, project_data["project_dotime"], project_data["project_endtime"], project_id):
            error_messages.append("ไม่สามารถแก้ไขโครงการได้เนื่องจากคุณมีโครงการอื่นในช่วงเวลา {} ถึง {} แล้ว กรุณาเลือกวันที่อื่น".format(project_data["project_dotime"], project_data["project_endtime"]))

        if error_messages:
            for message in error_messages:
                flash(message, "error")
                
            # แปลง JSON strings กลับเป็น Python lists เพื่อส่งกลับไปยังหน้า edit_project.html
            try:
                if project_data.get("project_activities_json"):
                    activities = json.loads(project_data.get("project_activities_json"))
                else:
                    activities = []
                project_data["activities"] = activities
            except (json.JSONDecodeError, TypeError):
                project_data["activities"] = []
                
            try:
                if project_data.get("project_compensation_json"):
                    compensation = json.loads(project_data.get("project_compensation_json"))
                else:
                    compensation = []
                project_data["compensation"] = compensation
            except (json.JSONDecodeError, TypeError):
                project_data["compensation"] = []
                
            try:
                if project_data.get("project_expenses_json"):
                    expenses = json.loads(project_data.get("project_expenses_json"))
                else:
                    expenses = []
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
                activities.append(
                    {"activity": activity, "months": selected_months}
                )
        activities_json = json.dumps(activities, ensure_ascii=False)
        project_data["activities"] = activities
        
        # รับข้อมูลค่าตอบแทนและค่าใช้สอย
        compensation = []
        compensation_descriptions = request.form.getlist("compensation_description[]")
        compensation_amounts = request.form.getlist("compensation_amount[]")
        for desc, amount in zip(compensation_descriptions, compensation_amounts):
            if desc and amount:
                compensation.append(
                    {"description": desc, "amount": float(amount)}
                )
        compensation_json = json.dumps(compensation, ensure_ascii=False)
        project_data["compensation"] = compensation

        expenses = []
        expense_descriptions = request.form.getlist("expense_description[]")
        expense_amounts = request.form.getlist("expense_amount[]")
        for desc, amount in zip(expense_descriptions, expense_amounts):
            if desc and amount:
                expenses.append(
                    {"description": desc, "amount": float(amount)}
                )
        expenses_json = json.dumps(expenses, ensure_ascii=False)
        project_data["expenses"] = expenses

        # คำนวณยอดรวม
        total_compensation = sum(item["amount"] for item in compensation)
        total_expenses = sum(item["amount"] for item in expenses)
        grand_total = total_compensation + total_expenses

        # บันทึกข้อมูลลงฐานข้อมูล
        with get_db_cursor() as (db, cursor):
            # อัปเดตข้อมูลโครงการในฐานข้อมูล
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

        # เพิ่มข้อมูลยอดรวมใน project_data สำหรับใช้ในการสร้าง PDF
        project_data["total_compensation"] = total_compensation
        project_data["total_expenses"] = total_expenses
        project_data["grand_total"] = grand_total

        # แปลงวันที่เป็น string ก่อนส่งไปสร้าง PDF
        if isinstance(project_data["project_dotime"], datetime):
            project_data["project_dotime"] = project_data["project_dotime"].strftime('%Y-%m-%d')
        if isinstance(project_data["project_endtime"], datetime):
            project_data["project_endtime"] = project_data["project_endtime"].strftime('%Y-%m-%d')

        # เพิ่ม log เพื่อดูข้อมูล
        logging.info(f"Creating PDF for project: {project_data['project_name']}")
        logging.info(f"Project data keys: {list(project_data.keys())}")
        logging.info(f"Project dates: {project_data['project_dotime']} to {project_data['project_endtime']}")
        logging.info(f"Project policy: {project_data['policy']}")

        # สร้าง PDF ใหม่
        pdf_buffer = create_project_pdf(project_data)
        if pdf_buffer:
            pdf_content = pdf_buffer.getvalue()

            # ตรวจสอบ PDF 
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(BytesIO(pdf_content))
                page_count = len(reader.pages)
                logging.info(f"Generated PDF has {page_count} pages")
            except Exception as e:
                logging.error(f"Error checking PDF: {e}")

            with get_db_cursor() as (db, cursor):
                try:
                    query = "UPDATE project SET project_pdf = %s WHERE project_id = %s"
                    cursor.execute(query, (pdf_content, project_id))
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

    # แปลง JSON strings กลับเป็น Python lists สำหรับการแสดงผลในฟอร์ม
    try:
        if project_data.get("project_activities_json"):
            activities = json.loads(project_data.get("project_activities_json"))
        else:
            activities = []
        project_data["activities"] = activities
    except (json.JSONDecodeError, TypeError):
        project_data["activities"] = []
        
    try:
        if project_data.get("project_compensation_json"):
            compensation = json.loads(project_data.get("project_compensation_json"))
        else:
            compensation = []
        project_data["compensation"] = compensation
    except (json.JSONDecodeError, TypeError):
        project_data["compensation"] = []
        
    try:
        if project_data.get("project_expenses_json"):
            expenses = json.loads(project_data.get("project_expenses_json"))
        else:
            expenses = []
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
@app.route("/teacher_evaluation_project/<int:project_id>")
@login_required("teacher")
def teacher_evaluation_project(project_id):
    # ตรวจสอบว่าเป็นอาจารย์เจ้าของโครงการหรือไม่
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลโครงการ
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
        
        # ตรวจสอบสิทธิ์อาจารย์
        if project_teacher_id != session.get('teacher_id'):
            flash('คุณไม่มีสิทธิ์ดูข้อมูลโครงการนี้', 'error')
            return redirect(url_for('teacher_projects'))
        
        # ดึงข้อมูลผู้เข้าร่วมโครงการทั้งหมด
        cursor.execute("""
            SELECT COUNT(*) as total_participants
            FROM `join`
            WHERE project_id = %s
        """, (project_id,))
        participants_count = cursor.fetchone()[0] or 0  # เพิ่มการป้องกันค่า None
        
        # ดึงข้อมูลการประเมิน
        query = """
        SELECT 
            pe.evaluation_id,
            j.join_name,
            j.join_email,
            pe.evaluation_score,
            pe.evaluation_comments,
            pe.evaluation_date
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
        
        # คำนวณสรุปคะแนน
        summary_query = """
        SELECT 
            COUNT(*) as total_evaluations,
            ROUND(AVG(evaluation_score), 2) as average_score,
            MIN(evaluation_score) as min_score,
            MAX(evaluation_score) as max_score
        FROM 
            project_evaluation
        WHERE 
            project_id = %s
        """
        cursor.execute(summary_query, (project_id,))
        summary = cursor.fetchone()
        
        # แปลงผลลัพธ์เป็น list of dictionaries
        evaluation_list = []
        for row in evaluations:
            evaluation_list.append({
                'evaluation_id': row[0],
                'join_name': row[1] or 'ไม่ระบุชื่อ',
                'join_email': row[2] or 'ไม่ระบุอีเมล',
                'evaluation_score': row[3] or 0,
                'evaluation_comments': row[4] or '',
                'evaluation_date': row[5]
            })
        
        # เตรียมข้อมูลสรุป และป้องกันค่า None
        total_evaluations = summary[0] if summary and summary[0] is not None else 0
        average_score = summary[1] if summary and summary[1] is not None else 0
        min_score = summary[2] if summary and summary[2] is not None else 0
        max_score = summary[3] if summary and summary[3] is not None else 0
        
        summary_data = {
            'total_evaluations': total_evaluations,
            'average_score': average_score,
            'min_score': min_score,
            'max_score': max_score
        }
    
    return render_template(
        'teacher_evaluation_project_detail.html', 
        evaluations=evaluation_list,
        project_id=project_id,
        project_name=project_name,
        summary=summary_data,
        participants_count=participants_count  # เพิ่มข้อมูลจำนวนผู้เข้าร่วม
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
            # ตรวจสอบว่าเป็นโครงการของอาจารย์และสถานะเป็น "รออนุมัติ" หรือไม่
            cursor.execute(
                "SELECT project_id FROM project WHERE project_id = %s AND teacher_id = %s AND project_status = 1",
                (project_id, teacher_id)
            )
            project = cursor.fetchone()
            
            if not project:
                return jsonify({"success": False, "message": "ไม่พบโครงการหรือไม่มีสิทธิ์ในการยกเลิก"})
            
            # อัปเดตสถานะกลับเป็น "ยังไม่ยื่นอนุมัติ"
            cursor.execute(
                "UPDATE project SET project_status = 0 WHERE project_id = %s",
                (project_id,)
            )
            db.commit()
            
            return jsonify({"success": True})
    except Exception as e:
        logging.error(f"Error in cancel_submission: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/project/<int:project_id>/summary")
@login_required("teacher", "admin")
def project_summary(project_id):
    """หน้าสรุปผลการดำเนินโครงการ รวมข้อมูลโครงการ ผลประเมิน และคะแนนการทดสอบ"""
    with get_db_cursor() as (db, cursor):
        # 1. ดึงข้อมูลโครงการ
        cursor.execute("""
            SELECT p.project_id, p.project_name, p.project_budgettype, p.project_year, 
                   p.project_style, p.project_address, p.project_dotime, p.project_endtime, 
                   p.project_target, p.project_status, p.project_statusStart, 
                   p.project_budget, p.project_submit_date, p.project_approve_date,
                   p.project_close_date, t.teacher_name, b.branch_name, p.summary_text
            FROM project p
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN branch b ON t.branch_id = b.branch_id
            WHERE p.project_id = %s
        """, (project_id,))
        project = cursor.fetchone()
        
        if not project:
            flash("ไม่พบข้อมูลโครงการ", "error")
            return redirect(url_for('home'))
        
        # สร้าง project_dict เพื่อให้สามารถเข้าถึงข้อมูลแบบ attribute ได้
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
            "summary_text": project[17]
        }
        
        # 2. ดึงข้อมูลผู้เข้าร่วมโครงการ
        cursor.execute("""
            SELECT COUNT(*) as approved_count
            FROM `join` 
            WHERE project_id = %s AND join_status = 1
        """, (project_id,))
        participant_count = int(cursor.fetchone()[0])
        
        # 3. ดึงข้อมูลการประเมินความพึงพอใจ
        cursor.execute("""
            SELECT 
                COUNT(*) as total_evaluations,
                ROUND(AVG(evaluation_score), 2) as average_score,
                MIN(evaluation_score) as min_score,
                MAX(evaluation_score) as max_score
            FROM 
                project_evaluation
            WHERE 
                project_id = %s
        """, (project_id,))
        evaluation_summary = cursor.fetchone()
        
        if evaluation_summary:
            evaluation_dict = {
                "total_evaluations": int(evaluation_summary[0]),
                "average_score": float(evaluation_summary[1] or 0),
                "min_score": float(evaluation_summary[2] or 0),
                "max_score": float(evaluation_summary[3] or 0)
            }
        else:
            evaluation_dict = {
                "total_evaluations": 0,
                "average_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0
            }
        
        # 4. ดึงข้อมูลความคิดเห็นจากผู้ประเมิน
        cursor.execute("""
            SELECT pe.evaluation_comments
            FROM project_evaluation pe
            WHERE pe.project_id = %s AND pe.evaluation_comments IS NOT NULL AND pe.evaluation_comments != ''
            ORDER BY pe.evaluation_date DESC
            LIMIT 5
        """, (project_id,))
        evaluation_comments = [row[0] for row in cursor.fetchall()]
        
        # 5. ดึงข้อมูลคะแนนทดสอบ
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tests,
                ROUND(AVG(pre_score), 2) as avg_pre_score,
                ROUND(AVG(post_score), 2) as avg_post_score,
                COUNT(CASE WHEN post_score >= 50 THEN 1 END) as pass_count
            FROM 
                test_scores
            WHERE 
                project_id = %s
        """, (project_id,))
        test_summary = cursor.fetchone()
        
        if test_summary and int(test_summary[0]) > 0:
            total_tests = int(test_summary[0])
            avg_pre_score = float(test_summary[1] or 0)
            avg_post_score = float(test_summary[2] or 0)
            pass_count = int(test_summary[3] or 0)
            
            pass_percent = 0
            if total_tests > 0:
                pass_percent = round((pass_count / total_tests * 100), 2)
                
            improvement = 0
            if avg_pre_score > 0:
                improvement = round(((avg_post_score - avg_pre_score) / avg_pre_score * 100), 2)
            elif avg_post_score > 0:
                improvement = 100.0
                
            test_dict = {
                "total_tests": total_tests,
                "avg_pre_score": avg_pre_score,
                "avg_post_score": avg_post_score,
                "pass_count": pass_count,
                "pass_percent": pass_percent,
                "improvement": improvement
            }
        else:
            test_dict = {
                "total_tests": 0,
                "avg_pre_score": 0.0,
                "avg_post_score": 0.0,
                "pass_count": 0,
                "pass_percent": 0.0,
                "improvement": 0.0
            }
            
        # 6. ดึงข้อมูลคะแนนสูงสุด/ต่ำสุด
        cursor.execute("""
            SELECT j.join_name, ts.pre_score, ts.post_score, 
                   (ts.post_score - ts.pre_score) as improvement,
                   CASE WHEN ts.pre_score > 0 
                        THEN ((ts.post_score - ts.pre_score) / ts.pre_score * 100) 
                        ELSE (CASE WHEN ts.post_score > 0 THEN 100 ELSE 0 END) 
                   END as improvement_percent
            FROM test_scores ts
            JOIN `join` j ON ts.join_id = j.join_id
            WHERE ts.project_id = %s
            ORDER BY improvement_percent DESC
            LIMIT 3
        """, (project_id,))
        top_improvers = []
        for row in cursor.fetchall():
            top_improvers.append({
                "name": row[0],
                "pre_score": float(row[1] or 0),
                "post_score": float(row[2] or 0),
                "improvement": float(row[3] or 0),
                "improvement_percent": round(float(row[4] or 0), 2)
            })
            
    # สรุปผลสำเร็จของโครงการ
    project_success = {}
    if evaluation_dict["total_evaluations"] > 0 and test_dict["total_tests"] > 0:
        # คำนวณคะแนนรวมจากทั้งความพึงพอใจและการทดสอบ
        eval_score = float(evaluation_dict["average_score"]) * 20  # ปรับสเกลจาก 0-5 เป็น 0-100
        test_score = float(test_dict["pass_percent"])
        total_score = (eval_score + test_score) / 2  # เฉลี่ยจาก 2 ส่วน
        
        project_success = {
            "score": round(total_score, 2),
            "level": get_success_level(total_score)
        }
    elif evaluation_dict["total_evaluations"] > 0:
        # มีแต่ผลประเมินความพึงพอใจ
        score = float(evaluation_dict["average_score"]) * 20  # ปรับสเกลจาก 0-5 เป็น 0-100
        project_success = {
            "score": round(score, 2),
            "level": get_success_level(score)
        }
    elif test_dict["total_tests"] > 0:
        # มีแต่ผลการทดสอบ
        project_success = {
            "score": round(float(test_dict["pass_percent"]), 2),
            "level": get_success_level(float(test_dict["pass_percent"]))
        }
    else:
        # ไม่มีข้อมูลทั้งสองส่วน
        project_success = {
            "score": 0.0,
            "level": "ไม่สามารถประเมินได้"
        }
        
    return render_template(
        "project_summary.html",
        project=project_dict,
        participant_count=participant_count,
        evaluation=evaluation_dict,
        evaluation_comments=evaluation_comments,
        test=test_dict,
        top_improvers=top_improvers,
        project_success=project_success
    )
@app.route("/admin_project_history")
@login_required("admin")
def admin_project_history():
    if not g.user or g.user["type"] != "admin":
        return redirect(url_for("login"))

    page = request.args.get("page", 1, type=int)
    per_page = 6  # จำนวนโปรเจคต่อหน้า
    search_query = request.args.get("search", "")
    branch_filter = request.args.get("branch", "all")

    with get_db_cursor() as (db, cursor):
        # สร้าง base query
        base_query = """
            SELECT p.project_id, p.project_name, p.project_year, p.project_budgettype,
                   p.project_dotime, p.project_endtime, p.project_close_date,
                   t.teacher_name, b.branch_name, 
                   CASE WHEN p.summary_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_summary
            FROM project p
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN branch b ON t.branch_id = b.branch_id
            WHERE p.project_statusStart = 2
        """
        
        count_query = """
            SELECT COUNT(*) 
            FROM project p
            JOIN teacher t ON p.teacher_id = t.teacher_id
            JOIN branch b ON t.branch_id = b.branch_id
            WHERE p.project_statusStart = 2
        """
        
        query_params = []
        
        # เพิ่มเงื่อนไขการค้นหา
        if search_query:
            base_query += " AND (p.project_name LIKE %s OR t.teacher_name LIKE %s)"
            count_query += " AND (p.project_name LIKE %s OR t.teacher_name LIKE %s)"
            search_pattern = f"%{search_query}%"
            query_params.extend([search_pattern, search_pattern])
            
        # เพิ่มเงื่อนไขกรองตามสาขา
        if branch_filter != "all":
            base_query += " AND b.branch_id = %s"
            count_query += " AND b.branch_id = %s"
            query_params.append(branch_filter)
            
        # นับจำนวนโครงการทั้งหมดที่ตรงตามเงื่อนไข
        cursor.execute(count_query, query_params)
        total_projects = cursor.fetchone()[0]
        
        # คำนวณจำนวนหน้าทั้งหมด
        total_pages = ceil(total_projects / per_page)
        
        # จัดเรียงและจำกัดจำนวนการแสดงผล
        base_query += " ORDER BY p.project_close_date DESC LIMIT %s OFFSET %s"
        offset = (page - 1) * per_page
        query_params.extend([per_page, offset])
        
        # ดึงข้อมูลโครงการ
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
def get_success_level(score):
    """กำหนดระดับความสำเร็จของโครงการจากคะแนน"""
    score = float(score)  # แปลงให้เป็น float เพื่อความแน่ใจ
    if score >= 90:
        return "ดีเยี่ยม"
    elif score >= 80:
        return "ดีมาก"
    elif score >= 70:
        return "ดี"
    elif score >= 60:
        return "ค่อนข้างดี"
    elif score >= 50:
        return "พอใช้"
    else:
        return "ควรปรับปรุง"
# ฟังก์ชันสำหรับกรองข้อความ nl2br เพื่อแปลงบรรทัดใหม่เป็น <br>
@app.template_filter('nl2br')
def nl2br(value):
    if value:
        value = re.sub(r'\r\n|\r|\n', '<br>', value)
        return Markup(value)
    return ''

# ฟังก์ชันบันทึกข้อความสรุปโครงการ
@app.route("/save_project_summary/<int:project_id>", methods=["POST"])
@login_required("teacher")
def save_project_summary(project_id):
    if "teacher_id" not in session:
        flash("คุณไม่มีสิทธิ์ในการดำเนินการนี้", "error")
        return redirect(url_for("home"))

    teacher_id = session["teacher_id"]
    summary_text = request.form.get("summary_text", "")
    
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
            # อัปเดตข้อความสรุปโครงการ
            cursor.execute(
                "UPDATE project SET summary_text = %s WHERE project_id = %s",
                (summary_text, project_id)
            )
            db.commit()
            
            # สร้าง PDF ทันทีหลังจากบันทึกข้อความ
            pdf_created = generate_summary_pdf(project_id)
            
            if pdf_created:
                flash("บันทึกสรุปรายงานและสร้าง PDF เรียบร้อยแล้ว", "success")
                # เปลี่ยนเส้นทางไปยังหน้าดาวน์โหลด PDF ทันที
                return redirect(url_for("download_summary_pdf", project_id=project_id))
            else:
                flash("บันทึกข้อความสรุปเรียบร้อยแล้ว แต่ไม่สามารถสร้าง PDF ได้", "warning")
                return redirect(url_for("project_summary", project_id=project_id))
        except Exception as err:
            flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {err}", "error")
            return redirect(url_for("project_summary", project_id=project_id))
# ฟังก์ชันสร้าง PDF สรุปผลการดำเนินโครงการ
def generate_summary_pdf(project_id):
    try:
        # นำเข้าคลาส PageBreak
        from reportlab.platypus import PageBreak
        # ดึงข้อมูลโครงการ
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูลโครงการและสาขาของอาจารย์
            cursor.execute("""
                SELECT p.project_id, p.project_name, p.project_budgettype, p.project_year, 
                       p.project_style, p.project_address, p.project_dotime, p.project_endtime, 
                       p.project_target, p.project_budget, p.project_detail,
                       p.project_output, p.project_strategy, p.project_indicator, 
                       p.project_cluster, p.project_commonality, p.project_physical_grouping,
                       p.project_rationale, p.project_objectives, p.project_goals, 
                       p.project_output_target, p.project_outcome_target, p.project_activity,
                       p.project_quantity_indicator, p.project_quality_indicator,
                       p.project_time_indicator, p.project_cost_indicator,
                       p.project_expected_results, p.summary_text, p.project_close_date,
                       t.teacher_id, t.teacher_name, b.branch_name
                FROM project p
                JOIN teacher t ON p.teacher_id = t.teacher_id
                JOIN branch b ON t.branch_id = b.branch_id
                WHERE p.project_id = %s
            """, (project_id,))
            project = cursor.fetchone()
            
            if not project:
                logging.error(f"ไม่พบข้อมูลโครงการ ID: {project_id}")
                return False
            
            # ดึงข้อมูลผู้เข้าร่วมโครงการ
            cursor.execute("""
                SELECT COUNT(*) as approved_count
                FROM `join` 
                WHERE project_id = %s AND join_status = 1
            """, (project_id,))
            participant_count = int(cursor.fetchone()[0])
            
            # ดึงข้อมูลการประเมินความพึงพอใจ
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_evaluations,
                    ROUND(AVG(evaluation_score), 2) as average_score,
                    MIN(evaluation_score) as min_score,
                    MAX(evaluation_score) as max_score
                FROM 
                    project_evaluation
                WHERE 
                    project_id = %s
            """, (project_id,))
            evaluation_summary = cursor.fetchone()
            
            # แปลงข้อมูลประเมินให้พร้อมใช้งาน
            if evaluation_summary:
                total_evaluations = int(evaluation_summary[0]) if evaluation_summary[0] is not None else 0
                average_score = float(evaluation_summary[1]) if evaluation_summary[1] is not None else 0
                min_score = float(evaluation_summary[2]) if evaluation_summary[2] is not None else 0
                max_score = float(evaluation_summary[3]) if evaluation_summary[3] is not None else 0
            else:
                total_evaluations = 0
                average_score = 0
                min_score = 0
                max_score = 0
            
            # คำนวณประสิทธิผลโครงการ (จากความพึงพอใจ)
            satisfaction_percentage = average_score * 20  # แปลงคะแนนจาก 0-5 เป็น 0-100
            target_percentage = (participant_count / int(project[8])) * 100 if int(project[8]) > 0 else 0
            
            # สาขาที่ถูกต้อง (branch_name)
            branch_name = project[32]
        
        # สร้าง PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,  # ลดลงจาก 36
        leftMargin=30,   # ลดลงจาก 36
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
            fontSize=14,  # ลดขนาดตัวอักษร
            leading=18,   # ลดช่องว่างระหว่างบรรทัด
            spaceBefore=4,
            spaceAfter=4
        )
        
        heading_style = ParagraphStyle(
            'Heading',
            fontName='THSarabunNew-Bold',
            fontSize=16,  # ลดขนาดตัวอักษร
            leading=20,   # ลดช่องว่างระหว่างบรรทัด
            alignment=1,  # center
            spaceAfter=8
        )
        
        title_style = ParagraphStyle(
            'Title',
            fontName='THSarabunNew-Bold',
            fontSize=18,  # ลดขนาดตัวอักษร
            alignment=1,  # center
            spaceAfter=8
        )
        
        # สไตล์ที่ปรับปรุงสำหรับตาราง
        table_header_style = ParagraphStyle(
            'TableHeader',
            fontName='THSarabunNew-Bold',
            fontSize=14,  # ลดขนาดตัวอักษร
            alignment=1,  # center alignment
            spaceBefore=4,
            spaceAfter=4
        )
        
        table_item_style = ParagraphStyle(
            'TableItem',
            fontName='THSarabunNew',
            fontSize=14,  # ลดขนาดตัวอักษร
            spaceBefore=4,
            spaceAfter=4,
            alignment=1  # center alignment by default
        )
        
        table_item_left_style = ParagraphStyle(
            'TableItemLeft',
            fontName='THSarabunNew',
            fontSize=14,  # ลดขนาดตัวอักษร
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
                # โลโก้มหาวิทยาลัย
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
                else:
                    logging.error(f"Logo file not found at {logo_path}")
                
                # หัวเรื่องโปรไฟล์
                canvas.setFont('THSarabunNew-Bold', 20)
                canvas.drawCentredString(
                    page_center,
                    doc.pagesize[1] - 175,
                    "บันทึกข้อความ"
                )
                
                # เส้นคั่นด้านล่างหลังจากข้อมูลส่วนงานภายใน
                
                
            
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
        
        # ส่วนงานภายใน - ใช้ branch_name แทนที่จะใช้เบอร์โทรศัพท์
        content.append(Paragraph(f"<b>ส่วนงานภายใน</b> สาขา/แผนก{branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ โทร. (IP) ................", normal_style))
        
        # เลขที่และวันที่
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
        project_date_format = project[6].strftime('%d/%m/%Y') + " ถึง " + project[7].strftime('%d/%m/%Y')
        main_text = f"""        ตามที่ สาขา/แผนก{branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ ได้ดำเนินโครงการ{project[1]} งบประมาณ{project[1]} (ในแผน) ประจำปีงบประมาณ พ.ศ. {project[3]} จำนวนเงิน {'{:,.2f}'.format(float(project[9]))} บาท ({thai_money_text(float(project[9]))}) วันที่{project_date_format} ณ {project[5]}
        
        ในการนี้ สาขา/แผนก{branch_name} คณะบริหารธุรกิจและเทคโนโลยีสารสนเทศ ได้ดำเนินโครงการเสร็จเป็นที่เรียบร้อยแล้ว จึงขอนำส่งรายงานสรุปผลประเมินความสำเร็จตามวัตถุประสงค์ของแผนการจัดกิจกรรมตามผลผลิต โดยมีรายละเอียดดังเอกสารแนบ"""
        content.append(Paragraph(main_text, normal_style))
        
        # สร้างตารางสรุป - ปรับปรุงการจัดวางข้อความในตาราง
        target_percent = '{:.1f}'.format(target_percentage)
        data = [
            [Paragraph("<b>ตัวชี้วัด</b>", table_header_style), 
             Paragraph("<b>หน่วยนับ</b>", table_header_style), 
             Paragraph("<b>แผน</b>", table_header_style), 
             Paragraph("<b>ผลดำเนินงาน</b>", table_header_style),
             Paragraph("<b>สรุปผล</b>", table_header_style)],
             
            [Paragraph("<b>เชิงปริมาณ</b>", table_header_style), "", "", "", ""],
            
            [Paragraph(f"ผู้เข้าร่วมโครงการจำนวน {project[8]} คน", table_item_left_style),
             Paragraph("คน", table_item_style),
             Paragraph(f"{project[8]}", table_item_style),
             Paragraph(f"{participant_count}", table_item_style),
             Paragraph("บรรลุ" if target_percentage >= 80 else "ไม่บรรลุ", table_item_style)],
             
            [Paragraph(f"จำนวนผู้เข้าร่วมโครงการไม่ต่ำกว่าร้อยละ 80", table_item_left_style),
             Paragraph("ร้อยละ", table_item_style),
             Paragraph("80", table_item_style),
             Paragraph(f"{target_percent}", table_item_style),
             Paragraph("บรรลุ" if target_percentage >= 80 else "ไม่บรรลุ", table_item_style)],
             
            [Paragraph("<b>เชิงคุณภาพ</b>", table_header_style), "", "", "", ""],
            
            [Paragraph(f"ผู้เข้าร่วมโครงการมีความพึงพอใจไม่ต่ำกว่าร้อยละ 70", table_item_left_style),
             Paragraph("ร้อยละ", table_item_style),
             Paragraph("70", table_item_style),
             Paragraph(f"{average_score * 20:.1f}", table_item_style),
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
            
            [Paragraph(f"งบประมาณที่ใช้ดำเนินโครงการ {'{:,.2f}'.format(float(project[9]))} บาท", table_item_left_style),
             Paragraph("บาท", table_item_style),
             Paragraph(f"{'{:,.2f}'.format(float(project[9]))}", table_item_style),
             Paragraph(f"{'{:,.2f}'.format(float(project[9]))}", table_item_style),
             Paragraph("บรรลุ", table_item_style)]
        ]
        
        col_widths = [200, 70, 70, 100, 70]  # กำหนดความกว้างคอลัมน์
        summary_table = Table(data, colWidths=col_widths)
        
        # ปรับปรุงการจัดวางในตาราง เพิ่ม padding และ align ที่ดีขึ้น
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
        
        content.append(Spacer(1, 6))  # ลดระยะห่างลง
        content.append(summary_table)
        content.append(Spacer(1, 6))  # ลดระยะห่างลง
        
        # ลงชื่อ - ลดระยะห่างและทำให้อยู่ในหน้าเดียวกัน
        content.append(Paragraph("จึงเรียนมาเพื่อโปรดพิจารณา", normal_style))
        content.append(Spacer(1, 15))  # ลดระยะห่างลง
        content.append(Paragraph(f"({project[31]})", normal_style))
        content.append(Paragraph("ผู้รับผิดชอบโครงการ", normal_style))
        
        # ส่วนรายงานสรุปผล - แยกไปหน้าต่อไป
        content.append(PageBreak())
        
        # หัวรายงานสรุปผล
        content.append(Paragraph(f"<b>ชื่อโครงการ :</b> {project[1]}", normal_style))
        content.append(Paragraph(f"<b>สาขา :</b> {branch_name} <b>งบประมาณเงินรายได้</b> (ในแผน) ประจำปีงบประมาณ {project[3]}", normal_style))
        content.append(Paragraph(f"<b>ระยะเวลา</b> วันที่{project[6].strftime('%d/%m/%Y')}ถึง{project[7].strftime('%d/%m/%Y')} <b>สถานที่</b> ณ {project[5]}", normal_style))
        content.append(Paragraph(f"<b>ผู้รับผิดชอบ</b> ชื่อ{project[31]}", normal_style))
        
        # สร้างตารางข้อมูลวัตถุประสงค์และเป้าหมาย - ปรับปรุงการจัดวาง
        # อ้างอิงตามภาพที่ 2 - ลบคอลัมน์ "แผน" และ "ผลลัพธ์"
        objective_data = [
            [Paragraph(f"<b>วัตถุประสงค์ :</b> {project[18]}", normal_style)],
            [Paragraph(f"<b>เป้าหมายเชิงผลผลิต (Output) :</b> {project[20]}", normal_style)],
            [Paragraph(f"<b>เป้าหมายเชิงผลลัพธ์ (Outcome) :</b> {project[21]}", normal_style)]
        ]
        
        objective_table = Table(objective_data, colWidths=[550])
        objective_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),   # เพิ่ม padding ซ้าย
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),  # เพิ่ม padding ขวา
            ('TOPPADDING', (0, 0), (-1, -1), 4),    # เพิ่ม padding บน
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4), # เพิ่ม padding ล่าง
        ]))
        
        content.append(Spacer(1, 12))
        content.append(objective_table)
        content.append(Spacer(1, 12))
        
        # สร้างตารางตัวบ่งชี้ - ปรับปรุงการจัดวาง
        indicator_data = [
            [Paragraph("<b>ตัวบ่งชี้</b>", table_header_style), 
             Paragraph("<b>ค่าเป้าหมาย</b>", table_header_style), 
             Paragraph("<b>บรรลุ (/ X)</b>", table_header_style)],
             
            [Paragraph("<b>เชิงปริมาณ :</b>", table_item_style),
             Paragraph(f"{project[8]}", table_item_style),
             Paragraph("/" if target_percentage >= 80 else "X", table_item_style)],
             
            [Paragraph(f"- ผู้เข้าร่วมโครงการจำนวน {project[8]} คน", table_item_left_style),
             "2", "/"],
             
            [Paragraph("- จำนวนโครงการที่ได้ดำเนินการ", table_item_left_style),
             Paragraph("1", table_item_style),
             Paragraph("/", table_item_style)],
             
            [Paragraph("<b>เชิงคุณภาพ :</b>", table_item_style),
             Paragraph("", table_item_style),
             Paragraph("" if average_score >= 3.5 else "", table_item_style)],
             
            [Paragraph("- ร้อยละของผู้เข้าร่วมโครงการ", table_item_left_style),
             Paragraph("80%", table_item_style),
             Paragraph("/" if target_percentage >= 80 else "X", table_item_style)],
             
            [Paragraph("- พึงพอใจของผู้เข้าร่วมโครงการ", table_item_left_style),
             Paragraph("3/5", table_item_style),
             Paragraph("/" if average_score >= 3.5 else "X", table_item_style)],
             
            [Paragraph("<b>เชิงเวลา :</b>", table_item_style),
             Paragraph("", table_item_style),
             Paragraph("", table_item_style)],
             
            [Paragraph("- โครงการแล้วเสร็จตามระยะเวลาที่กำหนด", table_item_left_style),
             "100%", "/"],
             
            [Paragraph("<b>เชิงค่าใช้จ่าย :</b>", table_item_style),
             Paragraph(f"{'{:,.2f}'.format(float(project[9]))} บาท", table_item_style),
             Paragraph("/", table_item_style)],
             
            [Paragraph(f"- งบประมาณที่ใช้ในการดำเนินโครงการ {'{:,.2f}'.format(float(project[9]))} บาท", table_item_left_style),
             "", ""]
        ]
        
        indicator_table = Table(indicator_data, colWidths=[270, 120, 160])
        indicator_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (2, -1), 'CENTER'),  # Center align second and third columns
            ('ALIGN', (0, 0), (2, 0), 'CENTER'),   # Center align header row
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),    # Left align first column
            ('BACKGROUND', (0, 0), (2, 0), colors.lightgrey),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),   # เพิ่ม padding ซ้าย
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),  # เพิ่ม padding ขวา
            ('TOPPADDING', (0, 0), (-1, -1), 4),    # เพิ่ม padding บน
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4), # เพิ่ม padding ล่าง
        ]))
        
        content.append(indicator_table)
        content.append(Spacer(1, 12))
        
        # ปัญหาและแนวทางแก้ไข - ปรับปรุงการจัดวาง
        problem_data = [
            [Paragraph("<b>ปัญหา :</b>", normal_style),
             ""],
            [Paragraph("การประชาสัมพันธ์ยังไม่ทั่วถึงทำให้มีผู้เข้าร่วมน้อยกว่าเป้าหมาย", normal_style),
             ""],
            [Paragraph("<b>แนวทางแก้ไข :</b>", normal_style),
             ""],
            [Paragraph("เพิ่มช่องทางประชาสัมพันธ์ให้หลากหลายและครอบคลุมกลุ่มเป้าหมายทุกกลุ่ม", normal_style),
             ""]
        ]
        
        problem_table = Table(problem_data, colWidths=[520, 30])
        problem_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'THSarabunNew', 14),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),   # เพิ่ม padding ซ้าย
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),  # เพิ่ม padding ขวา
            ('TOPPADDING', (0, 0), (-1, -1), 4),    # เพิ่ม padding บน
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4), # เพิ่ม padding ล่าง
            ('SPAN', (0, 0), (1, 0)),  # ปัญหา
            ('SPAN', (0, 1), (1, 1)),  # รายละเอียดปัญหา
            ('SPAN', (0, 2), (1, 2)),  # แนวทางแก้ไข
            ('SPAN', (0, 3), (1, 3)),  # รายละเอียดแนวทางแก้ไข
        ]))
        
        content.append(problem_table)
        
        # สรุปข้อมูลจากผู้ใช้
        if project[28]:  # summary_text
            content.append(PageBreak())
            content.append(Paragraph("<b>สรุปผลการดำเนินโครงการ</b>", heading_style))
            content.append(Spacer(1, 10))
            
            # แยกข้อความเป็นย่อหน้า
            paragraphs = project[28].split('\n')
            for para in paragraphs:
                if para.strip():
                    content.append(Paragraph(para, normal_style))
            
        try:
            doc.build(content, onFirstPage=header, onLaterPages=header)
            buffer.seek(0)
            
            # บันทึก PDF ลงฐานข้อมูล
            with get_db_cursor() as (db, cursor):
                query = "UPDATE project SET summary_pdf = %s WHERE project_id = %s"
                cursor.execute(query, (buffer.getvalue(), project_id))
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

# Route สำหรับดาวน์โหลด PDF สรุปผลการดำเนินโครงการ
@app.route("/download_summary_pdf/<int:project_id>")
@login_required("teacher", "admin")
def download_summary_pdf(project_id):
    try:
        with get_db_cursor() as (db, cursor):
            # ดึงข้อมูล PDF
            if g.user["type"] == "teacher":
                query = """
                    SELECT project_name, summary_pdf 
                    FROM project 
                    WHERE project_id = %s AND teacher_id = %s
                """
                cursor.execute(query, (project_id, g.user["id"]))
            else:  # admin
                query = """
                    SELECT project_name, summary_pdf 
                    FROM project 
                    WHERE project_id = %s
                """
                cursor.execute(query, (project_id,))
                
            result = cursor.fetchone()
            
            if not result or not result[1]:  # ไม่พบข้อมูลหรือไม่มี PDF
                # พยายามสร้าง PDF ใหม่
                pdf_created = generate_summary_pdf(project_id)
                
                if pdf_created:
                    # ดึงข้อมูล PDF ที่เพิ่งสร้าง
                    cursor.execute(
                        "SELECT project_name, summary_pdf FROM project WHERE project_id = %s",
                        (project_id,)
                    )
                    result = cursor.fetchone()
                
                if not result or not result[1]:
                    flash("ไม่พบไฟล์ PDF สรุปสำหรับโครงการนี้", "error")
                    return redirect(url_for("project_summary", project_id=project_id))
                    
            project_name, pdf_content = result
            
            # สร้างชื่อไฟล์ที่ใช้เฉพาะตัวอักษรภาษาอังกฤษและตัวเลข
            safe_filename = f"project_summary_{project_id}.pdf"
            
            # ส่ง PDF กลับไปยังผู้ใช้
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
    per_page = 6  # จำนวนโปรเจคต่อหน้า

    with get_db_cursor() as (db, cursor):
        # นับจำนวนโปรเจคที่ปิดแล้วทั้งหมด
        cursor.execute(
            "SELECT COUNT(*) FROM project WHERE teacher_id = %s AND project_statusStart = 2", 
            (teacher_id,)
        )
        total_projects = cursor.fetchone()[0]

        # คำนวณจำนวนหน้าทั้งหมด
        total_pages = ceil(total_projects / per_page)

        # ดึงข้อมูลโปรเจคตามหน้าที่ต้องการ
        offset = (page - 1) * per_page
        query = """
            SELECT 
                project_id, 
                project_name, 
                project_status, 
                project_statusStart, 
                CASE WHEN project_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_pdf,
                project_dotime, 
                project_endtime,
                project_close_date
            FROM project 
            WHERE teacher_id = %s AND project_statusStart = 2
            ORDER BY project_close_date DESC
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
    # ตรวจสอบการล็อกอิน
    if 'user_type' not in session or session['user_type'] != 'student':
        flash('คุณต้องล็อกอินด้วยบัญชีนักศึกษาก่อน', 'error')
        return redirect(url_for('login'))
    
    student_id = session.get('student_id')
    student_name = session.get('student_name')
    
    # ตรวจสอบว่าเคยอนุมัติเข้าร่วมโครงการนี้แล้วหรือยัง
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลโครงการ และตรวจสอบว่าเสร็จสิ้นแล้วหรือยัง
        cursor.execute("""
            SELECT p.project_name, p.project_statusStart 
            FROM project p 
            WHERE p.project_id = %s
        """, (project_id,))
        project = cursor.fetchone()
        
        if not project:
            flash('ไม่พบโครงการ', 'error')
            return redirect(url_for('student_dashboard'))
        
        project_name = project[0]
        project_status = project[1]
        
        # ตรวจสอบว่าโครงการเสร็จสิ้นแล้วหรือยัง (status=2 คือเสร็จสิ้น)
        if project_status != 2:
            flash('โครงการยังไม่เสร็จสิ้น ไม่สามารถประเมินได้', 'warning')
            return redirect(url_for('student_dashboard'))
        
        # ตรวจสอบว่านักศึกษาได้รับอนุมัติเข้าร่วมโครงการนี้หรือไม่
        cursor.execute("""
            SELECT j.join_id, j.join_name, j.join_email 
            FROM `join` j
            WHERE j.project_id = %s 
            AND j.join_status = 1 
            AND j.join_student_id = %s
        """, (project_id, student_id))
        participant = cursor.fetchone()
        
        if not participant:
            flash('คุณไม่มีสิทธิ์ประเมินโครงการนี้ เนื่องจากไม่ได้ลงทะเบียนหรือยังไม่ได้รับการอนุมัติ', 'error')
            return redirect(url_for('student_dashboard'))
        
        join_id = participant[0]
        
        # ตรวจสอบว่าเคยประเมินไปแล้วหรือยัง
        cursor.execute("""
            SELECT COUNT(*) 
            FROM project_evaluation 
            WHERE project_id = %s AND join_id = %s
        """, (project_id, join_id))
        existing_evaluation = cursor.fetchone()[0]
        
        if existing_evaluation > 0:
            flash('คุณได้ประเมินโครงการนี้ไปแล้ว', 'warning')
            return redirect(url_for('student_dashboard'))
        
        if request.method == 'POST':
            # รับข้อมูลการประเมิน
            evaluation_score = request.form.get('evaluation_score')
            evaluation_comments = request.form.get('evaluation_comments', '')
            
            # ตรวจสอบว่ามีการให้คะแนนหรือไม่
            if not evaluation_score:
                flash('กรุณาให้คะแนนประเมิน', 'error')
                return render_template('project_evaluation.html', 
                               project_id=project_id, 
                               project_name=project_name)
            
            # ตรวจสอบความถูกต้องของข้อมูล
            try:
                cursor.execute("""
                    INSERT INTO project_evaluation 
                    (project_id, join_id, evaluation_score, evaluation_comments, evaluation_date) 
                    VALUES (%s, %s, %s, %s, NOW())
                """, (project_id, join_id, evaluation_score, evaluation_comments))
                db.commit()
                
                flash('บันทึกการประเมินสำเร็จ ขอบคุณสำหรับการประเมิน', 'success')
                return redirect(url_for('student_dashboard'))
            
            except mysql.connector.Error as err:
                flash(f'เกิดข้อผิดพลาดในการบันทึกการประเมิน: {err}', 'error')
        
        # แสดงฟอร์มประเมิน
        return render_template('project_evaluation.html', 
                               project_id=project_id, 
                               project_name=project_name,
                               student_name=student_name)
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
        return render_template("add_branch.html")
    elif request.method == "POST":
        branch_id = request.form["branch_id"]
        branch_name = request.form["branch_name"]
        with get_db_cursor() as (db, cursor):
            query = "INSERT INTO branch (branch_name,branch_id) VALUES (%s,%s)"
            cursor.execute(query, (branch_name,branch_id))
            db.commit()

        flash("เพิ่มข้อมูลสาขาเรียบร้อยแล้ว", "success")
        return redirect(url_for("edit_basic_info"))
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
        # รับข้อมูลพื้นฐาน
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
        # รับข้อมูลอื่นๆ จากฟอร์ม
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
        project_activity_text = request.form["project_activity"]  # ข้อความรายละเอียดกิจกรรม
        project_quantity_indicator = request.form["quantity_indicator"]
        project_quality_indicator = request.form["quality_indicator"]
        project_time_indicator = request.form["time_indicator"]
        project_cost_indicator = request.form["cost_indicator"]
        project_expected_results = request.form.get("expected_results", "")
        
        # สร้าง JSON สำหรับข้อมูลที่มีหลายรายการ
        # กิจกรรม
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
        
        # บันทึกลงฐานข้อมูล
        with get_db_cursor() as (db, cursor):
            query = """INSERT INTO project (
    project_budgettype, project_year, project_name, project_style,
    project_address, project_dotime, project_endtime, project_target,
    project_status, teacher_id, project_budget, project_detail,
    project_output, project_strategy, project_indicator, project_cluster,
    project_commonality, project_physical_grouping, project_rationale,
    project_objectives, project_goals, project_output_target, project_outcome_target,
    project_activity, project_activities_json, project_quantity_indicator,
    project_quality_indicator, project_time_indicator, project_cost_indicator,
    project_expected_results, project_compensation_json, project_expenses_json,
    project_policy
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s
)"""
            cursor.execute(
                query,
                (
                    project_budgettype, project_year, project_name, project_style,
                    project_address, project_dotime, project_endtime, project_target,
                    0, teacher_id, project_budget, project_detail,
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
            
            # สร้างข้อมูลสำหรับส่งไปสร้าง PDF
            pdf_data = {
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
                "output": project_output,
                "strategy": project_strategy,
                "indicator": project_indicator,
                "cluster": project_cluster,
                "commonality": project_commonality,
                "physical_grouping": project_physical_grouping,
                "rationale": project_rationale,
                "objectives": project_objectives,
                "goals": project_goals,
                "output_target": project_output_target,
                "outcome_target": project_outcome_target,
                "project_activity": project_activity_text,
                "quantity_indicator": project_quantity_indicator,
                "quality_indicator": project_quality_indicator,
                "time_indicator": project_time_indicator,
                "cost_indicator": project_cost_indicator,
                "expected_results": project_expected_results,
                "activities": activities,
                "compensation": compensation,
                "expenses": expenses,
                "total_compensation": sum(item["amount"] for item in compensation),
                "total_expenses": sum(item["amount"] for item in expenses),
                "grand_total": sum(item["amount"] for item in compensation) + sum(item["amount"] for item in expenses)
            }
            
            # สร้าง PDF
            pdf_buffer = create_project_pdf(pdf_data)
            if pdf_buffer:
                pdf_content = pdf_buffer.getvalue()
                
                # บันทึก PDF ลงฐานข้อมูล
                update_query = "UPDATE project SET project_pdf = %s WHERE project_id = %s"
                cursor.execute(update_query, (pdf_content, project_id))
                db.commit()
                logging.info(f"PDF uploaded for project_id: {project_id}")
                flash("โครงการและ PDF ถูกบันทึกเรียบร้อยแล้ว", "success")
            else:
                logging.error("PDF buffer is None")
                flash("เกิดข้อผิดพลาดในการสร้าง PDF", "error")
            
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
@app.route("/edit_basic_info", methods=["GET", "POST"])
@login_required("admin")
def edit_basic_info():
    try:
        if "admin_id" in session:
            # ดึงข้อมูลสาขา
            with get_db_cursor() as (db, cursor):
                try:
                    # ดึงข้อมูลสาขา
                    cursor.execute("SELECT branch_id, branch_name FROM branch ORDER BY branch_name")
                    branches = cursor.fetchall()
                    
                    # ดึงข้อมูลอาจารย์
                    cursor.execute("""
                        SELECT t.teacher_id, t.teacher_name, t.teacher_username, 
                               t.teacher_password, t.teacher_phone, t.teacher_email, 
                               b.branch_name, t.branch_id
                        FROM teacher t
                        LEFT JOIN branch b ON t.branch_id = b.branch_id
                        ORDER BY t.teacher_name
                    """)
                    teachers = cursor.fetchall()
                    
                    # ดึงข้อมูลแอดมิน
                    cursor.execute("""
                        SELECT admin_id, admin_name, admin_username, admin_password, 
                               admin_email FROM admin ORDER BY admin_name
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
@app.route("/edit_teacher/<int:teacher_id>", methods=["GET", "POST"])
@login_required("admin")
def edit_teacher(teacher_id):
    if request.method == "GET":
        teacher = get_teacher_by_id(teacher_id)
        
        # ดึงข้อมูลสาขาทั้งหมด
        branches = get_branches_from_database()
        
        if teacher:
            return render_template("edit_teacher.html", teacher=teacher, branches=branches)
        else:
            flash("ไม่พบข้อมูลอาจารย์", "error")
            return redirect(url_for("edit_basic_info"))
            
    elif request.method == "POST":
        teacher_name = request.form["teacher_name"]
        teacher_username = request.form["teacher_username"]
        branch_id = request.form.get("branch_id")  # รับค่าเป็น string
        
        # ตรวจสอบว่ามีการเปลี่ยนรหัสผ่านหรือไม่
        current_teacher = get_teacher_by_id(teacher_id)
        if request.form["teacher_password"] != current_teacher[3] and request.form["teacher_password"].strip():
            # มีการเปลี่ยนรหัสผ่าน
            teacher_password = generate_password_hash(request.form["teacher_password"])
        else:
            # ใช้รหัสผ่านเดิม
            teacher_password = current_teacher[3]
            
        teacher_phone = request.form["teacher_phone"]
        teacher_email = request.form["teacher_email"]
        
        try:
            # อัปเดตข้อมูลอาจารย์
            with get_db_cursor() as (db, cursor):
                query = """UPDATE teacher SET teacher_name = %s, teacher_username = %s, 
                        teacher_password = %s, teacher_phone = %s, teacher_email = %s,
                        branch_id = %s 
                        WHERE teacher_id = %s"""
                cursor.execute(
                    query,
                    (
                        teacher_name,
                        teacher_username,
                        teacher_password,
                        teacher_phone,
                        teacher_email,
                        branch_id,
                        teacher_id,
                    ),
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
    try:
        delete_teacher(teacher_id)
        flash("ลบข้อมูลอาจารย์เรียบร้อยแล้ว", "success")
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการลบข้อมูล: {str(e)}", "error")
    return redirect(url_for("edit_basic_info"))  # แก้จาก teacher_home เป็น edit_basic_info
@app.route("/teacher_home")
@login_required("teacher")
def teacher_home():
    if not g.user or g.user['type'] != 'teacher':
        return redirect(url_for("login"))

    page = request.args.get('page', 1, type=int)
    per_page = 3  # จำนวน constants ต่อหน้า
    search_query = request.args.get('search', '')

    with get_db_cursor() as (db, cursor):
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
            query += " LIMIT %s OFFSET %s"
            cursor.execute(query, (f"%{search_query}%", per_page, offset))
        else:
            query += " LIMIT %s OFFSET %s"
            cursor.execute(query, (per_page, offset))
        constants = cursor.fetchall()

    constants = [
        (c[0], c[1], base64.b64encode(c[2]).decode("utf-8")) for c in constants
    ]

    return render_template("teacher_home.html", constants=constants, user=g.user, page=page, total_pages=total_pages, search_query=search_query)

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
    try:
        # ป้องกันการลบตัวเอง
        if int(admin_id) == int(session.get('admin_id')):
            flash("ไม่สามารถลบบัญชีแอดมินที่กำลังใช้งานอยู่ได้", "error")
            return redirect(url_for("edit_basic_info"))
        
        with get_db_cursor() as (db, cursor):
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
        admin_email = request.form["admin_email"]
        
        try:
            with get_db_cursor() as (db, cursor):
                # ตรวจสอบชื่อผู้ใช้ซ้ำ
                cursor.execute("SELECT COUNT(*) FROM admin WHERE admin_username = %s", (admin_username,))
                if cursor.fetchone()[0] > 0:
                    flash("ชื่อผู้ใช้นี้มีอยู่แล้ว กรุณาใช้ชื่อผู้ใช้อื่น", "error")
                    return render_template("add_admin.html")
                
                query = """INSERT INTO admin (admin_name, admin_username, admin_password, admin_email) 
                           VALUES (%s, %s, %s, %s)"""
                cursor.execute(query, (admin_name, admin_username, admin_password, admin_email))
                db.commit()
                flash("เพิ่มแอดมินเรียบร้อยแล้ว", "success")
        except Exception as e:
            flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")
            
        return redirect(url_for("edit_basic_info"))

@app.route("/edit_admin/<int:admin_id>", methods=["GET", "POST"])
@login_required("admin")
def edit_admin(admin_id):
    if request.method == "GET":
        with get_db_cursor() as (db, cursor):
            cursor.execute("""
                SELECT admin_id, admin_name, admin_username, admin_password, admin_email 
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
                           admin_password = %s, admin_email = %s 
                           WHERE admin_id = %s"""
                cursor.execute(query, (admin_name, admin_username, admin_password, admin_email, admin_id))
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
    per_page = 6  # จำนวนโปรเจคต่อหน้า

    with get_db_cursor() as (db, cursor):
        # นับจำนวนโปรเจคที่ยังไม่เสร็จสิ้นทั้งหมด
        cursor.execute(
            "SELECT COUNT(*) FROM project WHERE teacher_id = %s AND (project_statusStart != 2 OR project_statusStart IS NULL)", 
            (teacher_id,)
        )
        total_projects = cursor.fetchone()[0]

        # คำนวณจำนวนหน้าทั้งหมด
        total_pages = ceil(total_projects / per_page)

        # ดึงข้อมูลโปรเจคตามหน้าที่ต้องการ
        offset = (page - 1) * per_page
        query = """
            SELECT project_id, project_name, project_status, project_statusStart, 
                   CASE WHEN project_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_pdf,
                   project_reject, project_submit_date, project_reject_date
            FROM project 
            WHERE teacher_id = %s AND (project_statusStart != 2 OR project_statusStart IS NULL)
            ORDER BY project_submit_date DESC
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
            query = "UPDATE project SET project_status = 1, project_submit_date = NOW() WHERE project_id = %s"
            cursor.execute(query, (project_id,))
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
        query = """SELECT project.project_id, project.project_name, project.project_year, project.project_style, 
                          project.project_address, DATE(project.project_dotime) as project_dotime, 
                          DATE(project.project_endtime) as project_endtime, 
                          project.project_target, teacher.teacher_name, project.project_statusStart,
                          project.project_status,project.project_detail
                   FROM project
                   JOIN teacher ON project.teacher_id = teacher.teacher_id
                   WHERE project.project_id = %s"""
        cursor.execute(query, (project_id,))
        project = cursor.fetchone()

        if not project:
            flash("โครงการไม่พบ", "error")
            return redirect(url_for("active_projects"))

        cursor.execute(
            "SELECT COUNT(*) as current_participants FROM `join` WHERE project_id = %s",
            (project_id,),
        )
        result = cursor.fetchone()
        current_count = result[0] if result else 0

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

    # ตรวจสอบสถานะการล็อกอิน
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
        # ตรวจสอบสถานะการอนุมัติโครงการ
        cursor.execute(
            "SELECT project_status FROM project WHERE project_id = %s", (project_id,)
        )
        result = cursor.fetchone()
        if result and result[0] != 2:
            flash("โครงการยังไม่ได้รับการอนุมัติ ไม่สามารถเริ่มดำเนินการได้", "error")
            return redirect(url_for("project_detail", project_id=project_id))

        if project_status is not None and project_status != "":
            try:
                project_status = int(project_status)
                query = (
                    "UPDATE project SET project_statusStart = %s WHERE project_id = %s"
                )
                cursor.execute(query, (project_status, project_id))
                db.commit()
                flash("อัพเดทสถานะโครงการเรียบร้อยแล้ว", "success")
            except ValueError:
                flash("สถานะโครงการไม่ถูกต้อง", "error")
        else:
            flash("กรุณาเลือกสถานะโครงการ", "error")

    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/active_projects")
def active_projects():
    # ตรวจสอบสถานะการล็อกอิน
    is_logged_in = False
    user_type = None
    
    if 'user_type' in session:
        is_logged_in = True
        user_type = session['user_type']
    
    with get_db_cursor() as (db, cursor):
        # แก้ไข query เพื่อให้ดึงโครงการทั้งหมด ทั้งที่กำลังดำเนินการและเสร็จสิ้นแล้ว
        query = """
        SELECT p.project_id, p.project_name, p.project_dotime, p.project_endtime,
               p.project_statusStart, t.teacher_name
        FROM project p
        JOIN teacher t ON p.teacher_id = t.teacher_id
        WHERE p.project_status = 2 AND (p.project_statusStart = 1 OR p.project_statusStart = 2)
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
    student_id = request.form.get('student_id')
    project_id = request.form.get('project_id')
    
    if not student_id or not project_id:
        return jsonify({'exists': False})
    
    with get_db_cursor() as (db, cursor):
        try:
            # ตรวจสอบว่ามีรหัสนักศึกษานี้ในโครงการนี้แล้วหรือไม่
            cursor.execute(
                """
                SELECT COUNT(*) as count 
                FROM `join` 
                WHERE join_student_id = %s AND project_id = %s
                """, 
                (student_id, project_id)
            )
            result = cursor.fetchone()
            already_in_project = result[0] > 0
            
            if already_in_project:
                # นักศึกษานี้ลงทะเบียนในโครงการนี้แล้ว
                return jsonify({
                    'exists': False,
                    'already_joined': True,
                    'message': f"รหัสนักศึกษา {student_id} ได้ลงทะเบียนเข้าร่วมโครงการนี้แล้ว"
                })
            
            # ดึงข้อมูลนักศึกษาจากรหัสนักศึกษา
            cursor.execute("""
                SELECT j.join_name, j.join_email, j.join_telephone, j.branch_id, b.branch_name 
                FROM `join` j
                LEFT JOIN branch b ON j.branch_id = b.branch_id
                WHERE j.join_student_id = %s
                LIMIT 1
            """, (student_id,))
            
            student = cursor.fetchone()
            
            if student:
                data = {
                    'exists': True,
                    'student_name': student[0] if len(student) > 0 and student[0] is not None else '',
                    'student_email': student[1] if len(student) > 1 and student[1] is not None else '',
                    'student_phone': student[2] if len(student) > 2 and student[2] is not None else '',
                    'branch_id': student[3] if len(student) > 3 and student[3] is not None else '',
                    'branch_name': student[4] if len(student) > 4 and student[4] is not None else '',
                    'message': f"พบข้อมูลนักศึกษารหัส {student_id} ในระบบ กำลังดึงข้อมูลอัตโนมัติ"
                }
                
                return jsonify(data)
            
            return jsonify({
                'exists': False,
                'message': f"ไม่พบข้อมูลนักศึกษารหัส {student_id} ในระบบ โปรดลงทะเบียนแบบนักศึกษาใหม่"
            })
            
        except Exception as e:
            print(f"Error in check_student: {str(e)}")
            return jsonify({
                'exists': False, 
                'error': str(e),
                'message': "เกิดข้อผิดพลาดในการตรวจสอบข้อมูล กรุณาลองใหม่อีกครั้ง"
            })

# ตรวจสอบข้อมูลใหม่ทุกๆ 5 นาที
if __name__ == "__main__":
    init_scheduler(app)
    app.run(debug=True, port=5000)
