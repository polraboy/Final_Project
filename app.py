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
from markupsafe import Markup
import mysql.connector
import base64
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

# ตั้งค่าการทำงานอัตโนมัติ
@scheduler.task('cron', id='check_confirmations', hour=0, minute=0)  # รันทุกวันเวลาเที่ยงคืน
def scheduled_check():
    with app.app_context():  # จำเป็นต้องมี app context
        check_pending_confirmations()

# ฟังก์ชันตรวจสอบและอัปเดตสถานะการยืนยันที่หมดเวลา
@scheduler.task('cron', id='check_confirmations', hour=0, minute=0)  # รันทุกวันเวลาเที่ยงคืน
def check_pending_confirmations():
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลผู้สมัครที่รอการยืนยันและโครงการที่ใกล้เริ่ม
        cursor.execute("""
            SELECT j.join_id, j.join_name, j.join_email, p.project_id, p.project_name, p.project_dotime
            FROM `join` j 
            JOIN project p ON j.project_id = p.project_id 
            WHERE j.join_status = 3  # สถานะรอการยืนยัน
        """)
        pending_participants = cursor.fetchall()
        
        current_date = datetime.now().date()
        
        for participant in pending_participants:
            join_id = participant[0]
            name = participant[1]
            email = participant[2]
            project_id = participant[3]
            project_name = participant[4]
            project_date = participant[5]
            
            # แปลง project_dotime เป็น date ถ้าจำเป็น
            if isinstance(project_date, datetime):
                project_date = project_date.date()
                
            # ตรวจสอบว่าโครงการจะเริ่มในอีกไม่เกิน 1 วัน
            if (project_date - current_date).days <= 1:
                # อัปเดตสถานะเป็นไม่อนุมัติ
                cursor.execute(
                    "UPDATE `join` SET join_status = 2 WHERE join_id = %s",
                    (join_id,)
                )
                
                # ส่งอีเมลแจ้งเตือนการยกเลิกอัตโนมัติ
                subject = f"การยกเลิกการเข้าร่วมโครงการ: {project_name}"
                message = f"""
เรียน {name}

เนื่องจากคุณไม่ได้ยืนยันการเข้าร่วมโครงการ "{project_name}" ภายในระยะเวลาที่กำหนด และขณะนี้ใกล้ถึงวันจัดกิจกรรมแล้ว 
ทางระบบจึงได้ยกเลิกการลงทะเบียนของคุณโดยอัตโนมัติ

หากคุณยังสนใจเข้าร่วมโครงการ กรุณาติดต่อผู้ประสานงานโครงการโดยตรง

ขอแสดงความนับถือ
ทีมงานบริหารโครงการ
มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น
"""
                send_email_notification(subject, message, email)
            
        # Commit การเปลี่ยนแปลงทั้งหมด
        db.commit()
        
        return len(pending_participants)  # จำนวนรายการที่ถูกตรวจสอบ

@app.route("/home")
def index():
    return "Welcome to the Flask Google Form Integration App"


def send_email_notification(subject, message, recipient_email):
    if not recipient_email:
        logging.warning("ไม่ส่งอีเมลเนื่องจากไม่มีที่อยู่อีเมล")
        return False
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        import os
        
        # กำหนดค่าสำหรับการส่งอีเมล - ควรเก็บในตัวแปรสภาพแวดล้อมหรือไฟล์การกำหนดค่า
        sender_email = os.environ.get("EMAIL_SENDER", "chawanakorn.ca@gmail.com")  
        password = os.environ.get("EMAIL_PASSWORD", "nosv mtub ctqn wnbv")
        
        # สร้างข้อความ
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = subject
        
        # เพิ่มเนื้อหาอีเมล
        msg.attach(MIMEText(message, 'plain'))
        
        # เชื่อมต่อกับเซิร์ฟเวอร์ SMTP และส่งอีเมล
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, password)
        text = msg.as_string()
        server.sendmail(sender_email, recipient_email, text)
        server.quit()
        
        logging.info(f"ส่งอีเมลถึง {recipient_email} สำเร็จ")
        return True
    except Exception as e:
        logging.error(f"เกิดข้อผิดพลาดในการส่งอีเมล: {e}")
        return False
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
    return mysql.connector.connect(
        host="localhost", user="root", password="", database="project"
    )


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
                    flash(
                        "Login failed. Please check your username and password.",
                        "error",
                    )

    return render_template("login.html")
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
        
        # สร้างโทเค็นเพื่อเปรียบเทียบ (ต้องใช้วิธีเดียวกับที่ใช้สร้างโทเค็นในอีเมล)
        expected_token = generate_confirmation_token(join_id, participant_info[1])  # join_id และ email
        
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
    # ฟังก์ชันสร้างโทเค็นสำหรับยืนยันเข้าร่วม
def generate_confirmation_token(join_id, email):
    # สร้างโทเค็นอย่างง่ายจาก join_id และ email
    # ในระบบจริงควรใช้วิธีที่ปลอดภัยกว่านี้ เช่น ใช้ itsdangerous
    import hashlib
    token = hashlib.md5(f"{join_id}:{email}:{app.secret_key}".encode()).hexdigest()
    return token

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
    session.clear()
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
            # ดึงข้อมูลโครงการและอีเมลของอาจารย์
            cursor.execute("""
                SELECT p.project_name, t.teacher_email, t.teacher_name
                FROM project p
                JOIN teacher t ON p.teacher_id = t.teacher_id
                WHERE p.project_id = %s
            """, (project_id,))
            result = cursor.fetchone()
            if result:
                project_name, teacher_email, teacher_name = result
            else:
                project_name, teacher_email, teacher_name = "ไม่ทราบชื่อโครงการ", None, "ไม่ทราบชื่อ"

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

        # ตรวจสอบว่าต้องการส่งอีเมลหรือไม่
        send_email = request.form.get("send_email") == "on"
        
        # ส่งการแจ้งเตือนผ่านอีเมลไปยังอาจารย์เจ้าของโครงการ (ถ้าเลือกส่ง)
        if send_email and teacher_email:
            subject = f"การแจ้งเตือนสถานะโครงการ: {project_name}"
            
            # สร้างข้อความอีเมลตามสถานะ
            if action == "approve":
                message = f"""เรียน อาจารย์{teacher_name}

โครงการ: {project_name}
สถานะ: {status_text}

โครงการของท่านได้รับการอนุมัติเรียบร้อยแล้ว ท่านสามารถดำเนินโครงการตามที่เสนอได้

ขอแสดงความนับถือ
ผู้ดูแลระบบ
มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น
"""
            elif action == "reject":
                reason = request.form.get("reason", "ไม่ระบุเหตุผล")
                message = f"""เรียน อาจารย์{teacher_name}

โครงการ: {project_name}
สถานะ: {status_text}

โครงการของท่านถูกตีกลับเพื่อแก้ไข โดยมีเหตุผลดังนี้:
------------------------------------------------------------
{reason}
------------------------------------------------------------

กรุณาแก้ไขตามข้อเสนอแนะและส่งกลับเพื่อพิจารณาอีกครั้ง

ขอแสดงความนับถือ
ผู้ดูแลระบบ
มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น
"""
            
            # ส่งอีเมล
            email_result = send_email_notification(subject, message, teacher_email)
            if email_result:
                flash(f'โครงการได้รับการ{status_text}แล้ว และได้ส่งอีเมลแจ้งเตือนไปยัง {teacher_name} เรียบร้อยแล้ว', 'success')
            else:
                flash(f'โครงการได้รับการ{status_text}แล้ว แต่ไม่สามารถส่งอีเมลแจ้งเตือนได้', 'warning')
        else:
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

    return render_template(
        "approve_project.html",
        projects=projects,
        approval_filter=approval_filter,
        page=page,
        total_pages=total_pages,
        search_query=search_query,
        per_page=per_page
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


@app.route("/project/<int:project_id>/join", methods=["GET", "POST"])
def join_project(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT project_name, project_target FROM project WHERE project_id = %s",
        (project_id,),
    )
    project = cursor.fetchone()

    if not project:
        flash("โครงการไม่พบ", "error")
        return redirect(url_for("active_projects"))

    cursor.execute(
        "SELECT COUNT(*) as current_count FROM `join` WHERE project_id = %s",
        (project_id,),
    )
    result = cursor.fetchone()
    current_count = result["current_count"]

    if current_count >= project["project_target"]:
        flash("ขออภัย โครงการนี้มีผู้เข้าร่วมเต็มแล้ว", "error")
        return redirect(url_for("project_detail", project_id=project_id))

    if request.method == "POST":
        join_name = request.form["join_name"]
        join_telephone = request.form["join_telephone"]
        join_email = request.form["join_email"]

        # ตรวจสอบอีเมลซ้ำในโครงการนี้
        cursor.execute(
            """
            SELECT COUNT(*) as email_count 
            FROM `join` 
            WHERE project_id = %s AND join_email = %s
            """,
            (project_id, join_email)
        )
        email_check = cursor.fetchone()
        
        if email_check and email_check["email_count"] > 0:
            flash(f"อีเมล {join_email} ได้ลงทะเบียนเข้าร่วมโครงการนี้แล้ว", "error")
            cursor.close()
            conn.close()
            return render_template(
                "join_project.html",
                project=project,
                project_id=project_id,
                current_count=current_count,
            )

        try:
            cursor.execute(
                """
                INSERT INTO `join` (join_name, join_telephone, join_email, project_id, join_status)
                VALUES (%s, %s, %s, %s, 0)
            """,
                (join_name, join_telephone, join_email, project_id),
            )
            conn.commit()
            flash("คุณได้ลงทะเบียนเข้าร่วมโครงการเรียบร้อยแล้ว โปรดรอการอนุมัติ", "success")
        except mysql.connector.Error as err:
            flash(f"เกิดข้อผิดพลาดในการลงทะเบียน: {err}", "error")

        return redirect(url_for("project_detail", project_id=project_id))

    cursor.close()
    conn.close()
    return render_template(
        "join_project.html",
        project=project,
        project_id=project_id,
        current_count=current_count,
    )

# เพิ่มเส้นทางใหม่สำหรับการยืนยันการเข้าร่วม
# ฟังก์ชันสร้างโทเค็นสำหรับยืนยันเข้าร่วม
def generate_confirmation_token(join_id, email):
    # สร้างโทเค็นอย่างง่ายจาก join_id และ email
    # ในระบบจริงควรใช้วิธีที่ปลอดภัยกว่านี้ เช่น ใช้ itsdangerous
    import hashlib
    token = hashlib.md5(f"{join_id}:{email}:{app.secret_key}".encode()).hexdigest()
    return token


@app.route("/project/<int:project_id>/participants")
def project_participants(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT join_id, join_name, join_email, join_telephone, join_status
        FROM `join`
        WHERE project_id = %s
        ORDER BY join_id
    """,
        (project_id,),
    )
    participants = cursor.fetchall()

    cursor.close()
    conn.close()

    is_logged_in = "teacher_id" in session

    return render_template(
        "project_participants.html",
        project_id=project_id,
        participants=participants,
        is_logged_in=is_logged_in,
    )


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
def check_pending_confirmations():
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลผู้สมัครที่รอการยืนยันและโครงการที่ใกล้เริ่ม
        cursor.execute("""
            SELECT j.join_id, j.join_name, j.join_email, p.project_id, p.project_name, p.project_dotime
            FROM `join` j 
            JOIN project p ON j.project_id = p.project_id 
            WHERE j.join_status = 3  # สถานะรอการยืนยัน
            AND DATEDIFF(p.project_dotime, CURRENT_DATE()) <= 1  # เหลือเวลาไม่เกิน 1 วัน
        """)
        pending_participants = cursor.fetchall()
        
        for participant in pending_participants:
            join_id = participant[0]
            name = participant[1]
            email = participant[2]
            project_id = participant[3]
            project_name = participant[4]
            
            # อัปเดตสถานะเป็นไม่อนุมัติ
            cursor.execute(
                "UPDATE `join` SET join_status = 2 WHERE join_id = %s",
                (join_id,)
            )
            
            # ส่งอีเมลแจ้งเตือนการยกเลิกอัตโนมัติ
            subject = f"การยกเลิกการเข้าร่วมโครงการ: {project_name}"
            message = f"""
เรียน {name}

เนื่องจากคุณไม่ได้ยืนยันการเข้าร่วมโครงการ "{project_name}" ภายในระยะเวลาที่กำหนด และขณะนี้ใกล้ถึงวันจัดกิจกรรมแล้ว 
ทางระบบจึงได้ยกเลิกการลงทะเบียนของคุณโดยอัตโนมัติ

หากคุณยังสนใจเข้าร่วมโครงการ กรุณาติดต่อผู้ประสานงานโครงการโดยตรง

ขอแสดงความนับถือ
ทีมงานบริหารโครงการ
มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น
"""
            send_email_notification(subject, message, email)
            
        # Commit การเปลี่ยนแปลงทั้งหมด
        db.commit()
        
        return len(pending_participants)  # จำนวนรายการที่ถูกปรับเปลี่ยน

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
@app.route("/project/<int:project_id>/approve_all", methods=["POST"])
@login_required("teacher")
def approve_all_participants(project_id):
    if "teacher_id" not in session:
        flash("คุณไม่มีสิทธิ์ในการดำเนินการนี้", "error")
        return redirect(url_for("home"))

    teacher_id = session["teacher_id"]
    
    with get_db_cursor() as (db, cursor):
        # ตรวจสอบว่าเป็นอาจารย์เจ้าของโครงการหรือไม่
        cursor.execute(
            "SELECT teacher_id FROM project WHERE project_id = %s", 
            (project_id,)
        )
        project = cursor.fetchone()
        
        if not project or project[0] != teacher_id:
            flash("คุณไม่มีสิทธิ์อนุมัติผู้เข้าร่วมโครงการนี้", "error")
            return redirect(url_for("project_detail", project_id=project_id))
            
        # ดึงรายชื่อผู้เข้าร่วมที่รออนุมัติ (สถานะ 0)
        cursor.execute(
            """SELECT j.join_id, j.join_name, j.join_email 
               FROM `join` j 
               WHERE j.project_id = %s AND j.join_status = 0""",
            (project_id,)
        )
        pending_participants = cursor.fetchall()
        
        if not pending_participants:
            flash("ไม่มีผู้เข้าร่วมที่รออนุมัติ", "info")
            return redirect(url_for("approve_participants", project_id=project_id))
        
        # ดึงข้อมูลโครงการ
        cursor.execute(
            "SELECT project_name, project_dotime FROM project WHERE project_id = %s",
            (project_id,)
        )
        project_info = cursor.fetchone()
        project_name = project_info[0]
        project_dotime = project_info[1]
        
        # แปลงวันที่โครงการให้เป็น date object ถ้าจำเป็น
        if isinstance(project_dotime, datetime):
            project_date = project_dotime.date()
        else:
            project_date = project_dotime
            
        # คำนวณวันที่เหลือก่อนถึงวันโครงการ
        current_date = datetime.now().date()
        days_until_project = (project_date - current_date).days
        
        approved_count = 0
        pending_confirmation_count = 0
        
        for participant in pending_participants:
            join_id = participant[0]
            join_name = participant[1]
            join_email = participant[2]
            
            # ถ้าโครงการจะเริ่มในอีกไม่เกิน 1 วัน อนุมัติเลยโดยไม่ต้องยืนยัน
            if days_until_project <= 1:
                cursor.execute(
                    "UPDATE `join` SET join_status = 1 WHERE join_id = %s",
                    (join_id,)
                )
                
                # ส่งอีเมลแจ้งการอนุมัติ
                subject = f"การอนุมัติเข้าร่วมโครงการ: {project_name}"
                message = f"""
เรียน {join_name} 

ยินดีด้วย! คุณได้รับการอนุมัติให้เข้าร่วมโครงการ "{project_name}" แล้ว

เนื่องจากโครงการใกล้จะเริ่มในเร็วๆ นี้ จึงไม่จำเป็นต้องยืนยันการเข้าร่วม
โปรดเตรียมตัวให้พร้อมสำหรับการเข้าร่วมกิจกรรมตามวันและเวลาที่กำหนด

ขอแสดงความนับถือ
ทีมงานบริหารโครงการ
มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น
"""
                send_email_notification(subject, message, join_email)
                approved_count += 1
            
            # กรณีปกติ - ส่งอีเมลยืนยัน
            else:
                # สร้างโทเค็นสำหรับยืนยัน
                token = generate_confirmation_token(join_id, join_email)
                
                # สร้าง URL สำหรับยืนยัน
                base_url = request.host_url.rstrip('/')
                confirmation_url = f"{base_url}{url_for('confirm_participation', join_id=join_id, token=token)}"
                
                # ส่งอีเมลยืนยันให้ผู้สมัคร
                subject = f"ยืนยันการเข้าร่วมโครงการ: {project_name}"
                message = f"""
เรียน {join_name} 

ยินดีด้วย! คำขอเข้าร่วมโครงการ "{project_name}" ของคุณได้รับการอนุมัติเบื้องต้นแล้ว

กรุณายืนยันการเข้าร่วมโครงการโดยคลิกที่ลิงก์ด้านล่าง:
{confirmation_url}

หมายเหตุ: การยืนยันนี้จะหมดอายุใน 1 วันก่อนวันเริ่มโครงการ หากไม่ได้รับการยืนยันภายในเวลาดังกล่าว 
ระบบจะยกเลิกการลงทะเบียนของคุณโดยอัตโนมัติ

หากคุณไม่ได้ลงทะเบียนเข้าร่วมโครงการนี้ กรุณาละเว้นอีเมลฉบับนี้

ขอแสดงความนับถือ
ทีมงานบริหารโครงการ
มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น
"""
                # ส่งอีเมล
                send_email_notification(subject, message, join_email)
                
                # อัปเดตสถานะเป็น "รอการยืนยัน" (สถานะ 3)
                cursor.execute(
                    "UPDATE `join` SET join_status = 3 WHERE join_id = %s",
                    (join_id,)
                )
                pending_confirmation_count += 1
        
        # Commit การเปลี่ยนแปลงทั้งหมด
        db.commit()
        
        if approved_count > 0 and pending_confirmation_count > 0:
            flash(f"อนุมัติผู้เข้าร่วมทั้งหมด {approved_count} คน และส่งอีเมลยืนยันให้อีก {pending_confirmation_count} คนแล้ว", "success")
        elif approved_count > 0:
            flash(f"อนุมัติผู้เข้าร่วมทั้งหมด {approved_count} คนเรียบร้อยแล้ว", "success")
        elif pending_confirmation_count > 0:
            flash(f"ส่งอีเมลยืนยันให้ผู้เข้าร่วมทั้งหมด {pending_confirmation_count} คนแล้ว", "success")
        
    return redirect(url_for("approve_participants", project_id=project_id))
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
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
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
        styles["Normal"].fontSize = 12
        styles["Heading1"].fontName = "THSarabunNew"
        styles["Heading1"].fontSize = 14
        styles["Heading2"].fontName = "THSarabunNew"
        styles["Heading2"].fontSize = 12
        styles["Heading3"].fontName = "THSarabunNew"
        styles["Heading3"].fontSize = 12

        def header(canvas, doc):
            canvas.saveState()
            page_width = doc.pagesize[0]
            page_height = doc.pagesize[1]

            if canvas.getPageNumber() == 1:  # เฉพาะหน้าแรก
                logo_path = os.path.join(app.static_folder, "2.png")

                if os.path.exists(logo_path):
                    try:
                        img = Image.open(logo_path)
                        img = img.convert("RGB")
                        img_buffer = BytesIO()
                        img.save(img_buffer, format="PNG")
                        img_buffer.seek(0)

                        logo_width = 0.5 * inch
                        logo_height = 0.5 * inch
                        logo_x = (page_width - logo_width) / 2
                        logo_y = page_height - 0.5 * inch

                        canvas.drawImage(
                            ImageReader(img_buffer),
                            logo_x,
                            logo_y,
                            width=logo_width,
                            height=logo_height,
                        )
                    except Exception as e:
                        logging.error(f"Error loading logo: {e}")
                else:
                    logging.error(f"Logo file not found at {logo_path}")

                # กำหนดค่าเริ่มต้นสำหรับข้อมูลที่อาจไม่มี
                project_budgettype = project_data.get('project_budgettype', 'ไม่ระบุ')
                project_year = project_data.get('project_year', 'ไม่ระบุ')

                canvas.setFont("THSarabunNew", 16)
                canvas.drawCentredString(
                    page_width / 2, logo_y - 0.3 * inch, "มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน"
                )
                canvas.setFont("THSarabunNew", 14)
                canvas.drawCentredString(
                    page_width / 2, logo_y - 0.5 * inch, "วิทยาเขต ขอนแก่น"
                )
                canvas.drawCentredString(
                    page_width / 2,
                    logo_y - 0.7 * inch,
                    f"งบประมาณ{project_budgettype} ประจำปีงบประมาณ พ.ศ. {project_year}",
                )

            canvas.restoreState()

        content = []
        content.append(Spacer(1, 1 * inch))  # เพิ่มระยะห่างด้านบน
        
        # ตรวจสอบและกำหนดค่าเริ่มต้นสำหรับทุกฟิลด์
        project_name = project_data.get('project_name', 'ไม่ระบุชื่อโครงการ')
        content.append(
            Paragraph(f"1. ชื่อโครงการ: {project_name}", styles["Normal"])
        )
        
        project_style = project_data.get('project_style', 'ไม่ระบุลักษณะโครงการ')
        content.append(
            Paragraph(
                f"2. ลักษณะโครงการ: {project_style}", styles["Normal"]
            )
        )
        
        content.append(
    Paragraph("3. โครงการนี้สอดคล้องกับนโยบายชาติ และผลผลิต", styles["Heading2"])
)

# ดึงค่านโยบายและตรวจสอบให้แน่ใจว่ามีค่า
        policy_text = project_data.get('policy', '')
        if not policy_text and 'project_policy' in project_data:
            policy_text = project_data.get('project_policy', '')

        # เพิ่มคำว่า "นโยบาย: " ข้างหน้าค่า policy_text
        content.append(
            Paragraph(
                f"นโยบาย: {policy_text}",
                styles["Normal"],
            )
        )
        # ตรวจสอบและใช้ฟิลด์ output หรือ project_output
        output_text = project_data.get('project_output', '')
        if not output_text and 'output' in project_data:
            output_text = project_data.get('output', '')
        content.append(
            Paragraph(f"ผลผลิต : {output_text}", styles["Normal"])
        )
        
        content.append(
            Paragraph("4. ความสอดคล้องประเด็นยุทธศาสตร์ และตัวชี้วัด", styles["Heading2"])
        )
        
        # ตรวจสอบและใช้ฟิลด์ strategy หรือ project_strategy
        strategy_text = project_data.get('project_strategy', '')
        if not strategy_text and 'strategy' in project_data:
            strategy_text = project_data.get('strategy', '')
        content.append(
            Paragraph(
                f"ประเด็นยุทธศาสตร์ที่ : {strategy_text}",
                styles["Normal"],
            )
        )
        
        # ตรวจสอบและใช้ฟิลด์ indicator หรือ project_indicator
        indicator_text = project_data.get('project_indicator', '')
        if not indicator_text and 'indicator' in project_data:
            indicator_text = project_data.get('indicator', '')
        content.append(
            Paragraph(f"ตัวชี้วัดที่ : {indicator_text}", styles["Normal"])
        )
        
        content.append(
            Paragraph(
                "5. ความสอดคล้องกับ Cluster / Commonality / Physical grouping",
                styles["Heading2"],
            )
        )
        
        # ตรวจสอบและใช้ฟิลด์ cluster หรือ project_cluster
        cluster_text = project_data.get('project_cluster', '')
        if not cluster_text and 'cluster' in project_data:
            cluster_text = project_data.get('cluster', '')
        content.append(
            Paragraph(f"Cluster : {cluster_text}", styles["Normal"])
        )
        
        # ตรวจสอบและใช้ฟิลด์ commonality หรือ project_commonality
        commonality_text = project_data.get('project_commonality', '')
        if not commonality_text and 'commonality' in project_data:
            commonality_text = project_data.get('commonality', '')
        content.append(
            Paragraph(
                f"Commonality : {commonality_text}", styles["Normal"]
            )
        )
        
        # ตรวจสอบและใช้ฟิลด์ physical_grouping หรือ project_physical_grouping
        physical_grouping_text = project_data.get('project_physical_grouping', '')
        if not physical_grouping_text and 'physical_grouping' in project_data:
            physical_grouping_text = project_data.get('physical_grouping', '')
        content.append(
            Paragraph(
                f"Physical grouping : {physical_grouping_text}",
                styles["Normal"],
            )
        )
        
        # ตรวจสอบและกำหนดค่าเริ่มต้นสำหรับ project_address
        project_address = project_data.get('project_address', 'ไม่ระบุสถานที่')
        content.append(
            Paragraph(
                f"7. สถานที่ดำเนินงาน: {project_address}", styles["Normal"]
            )
        )
        
        # ตรวจสอบและแปลงวันที่ให้อยู่ในรูปแบบที่ถูกต้อง
        project_dotime = project_data.get('project_dotime', 'ไม่ระบุวันเริ่มต้น')
        project_endtime = project_data.get('project_endtime', 'ไม่ระบุวันสิ้นสุด')
        
        # ถ้าเป็น datetime object ให้แปลงเป็น string
        if isinstance(project_dotime, datetime):
            project_dotime = project_dotime.strftime('%Y-%m-%d')
        if isinstance(project_endtime, datetime):
            project_endtime = project_endtime.strftime('%Y-%m-%d')
        
        content.append(
            Paragraph(
                f"8. ระยะเวลาดำเนินการ: {project_dotime} ถึง {project_endtime}",
                styles["Normal"],
            )
        )
        
        content.append(Paragraph("9. หลักการและเหตุผล", styles["Heading2"]))
        
        # ตรวจสอบและใช้ฟิลด์ rationale หรือ project_rationale
        rationale_text = project_data.get('project_rationale', '')
        if not rationale_text and 'rationale' in project_data:
            rationale_text = project_data.get('rationale', '')
        content.append(Paragraph(rationale_text, styles["Normal"]))
        
        content.append(Paragraph("10. วัตถุประสงค์", styles["Heading2"]))
        
        # ตรวจสอบและใช้ฟิลด์ objectives หรือ project_objectives
        objectives_text = project_data.get('project_objectives', '')
        if not objectives_text and 'objectives' in project_data:
            objectives_text = project_data.get('objectives', '')
        content.append(Paragraph(objectives_text, styles["Normal"]))
        
        content.append(Paragraph("11. เป้าหมาย", styles["Heading2"]))
        
        # ตรวจสอบและใช้ฟิลด์ goals หรือ project_goals
        goals_text = project_data.get('project_goals', '')
        if not goals_text and 'goals' in project_data:
            goals_text = project_data.get('goals', '')
        content.append(Paragraph(goals_text, styles["Normal"]))
        
        # ตรวจสอบและใช้ฟิลด์ output_target หรือ project_output_target
        output_target_text = project_data.get('project_output_target', '')
        if not output_target_text and 'output_target' in project_data:
            output_target_text = project_data.get('output_target', '')
        content.append(
            Paragraph(
                f"11.1 เป้าหมายเชิงผลผลิต (Output): {output_target_text}",
                styles["Normal"],
            )
        )
        
        # ตรวจสอบและใช้ฟิลด์ outcome_target หรือ project_outcome_target
        outcome_target_text = project_data.get('project_outcome_target', '')
        if not outcome_target_text and 'outcome_target' in project_data:
            outcome_target_text = project_data.get('outcome_target', '')
        content.append(
            Paragraph(
                f"11.2 เป้าหมายเชิงผลลัพธ์ (Outcome): {outcome_target_text}",
                styles["Normal"],
            )
        )
        
        content.append(Paragraph("12. กิจกรรมดำเนินงาน", styles["Heading2"]))
        
        # ตรวจสอบและใช้ฟิลด์ project_activity
        project_activity_text = project_data.get('project_activity', '')
        content.append(
            Paragraph(project_activity_text, styles["Normal"])
        )
        
        content.append(Paragraph("13. กลุ่มเป้าหมายผู้เข้าร่วมโครงการ", styles["Heading2"]))
        
        # ตรวจสอบและกำหนดค่าเริ่มต้นสำหรับ project_target
        project_target = project_data.get('project_target', '0')
        content.append(Paragraph(str(project_target), styles["Normal"]))
        
        content.append(Paragraph("14. งบประมาณ", styles["Heading2"]))
        
        # ตรวจสอบและกำหนดค่าเริ่มต้นสำหรับ project_budget
        project_budget = project_data.get('project_budget', '0')
        content.append(
            Paragraph(
                f"งบประมาณโครงการ: {project_budget} บาท",
                styles["Normal"],
            )
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
                
        content.append(Paragraph("14.1 ค่าตอบแทน", styles["Heading3"]))
        for item in compensation_items:
            content.append(
                Paragraph(
                    f"{item['description']}: {item['amount']} บาท", styles["Normal"]
                )
            )
        
        total_compensation = sum(item["amount"] for item in compensation_items)
        content.append(
            Paragraph(
                f"รวมค่าตอบแทน: {total_compensation} บาท",
                styles["Normal"],
            )
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
                
        content.append(Paragraph("14.2 ค่าใช้สอย", styles["Heading3"]))
        for item in expense_items:
            content.append(
                Paragraph(
                    f"{item['description']}: {item['amount']} บาท", styles["Normal"]
                )
            )
        
        total_expenses = sum(item["amount"] for item in expense_items)
        content.append(
            Paragraph(
                f"รวมค่าใช้สอย: {total_expenses} บาท", styles["Normal"]
            )
        )
        
        grand_total = total_compensation + total_expenses
        content.append(
            Paragraph(
                f"รวมค่าใช้จ่ายทั้งสิ้น: {grand_total} บาท", styles["Normal"]
            )
        )

        # แผนปฏิบัติงาน (ใช้ตารางตามต้นฉบับ)
        content.append(
            Paragraph(
                "15. แผนปฏิบัติงาน (แผนงาน) แผนการใช้จ่ายงบประมาณ (แผนเงิน) และตัวชี้วัดเป้าหมายผลผลิต",
                styles["Heading2"],
            )
        )
        
        # ตรวจสอบและกำหนดค่าเริ่มต้นสำหรับ project_year
        project_year = project_data.get('project_year', '')
        try:
            project_year_int = int(project_year)
        except (ValueError, TypeError):
            project_year_int = datetime.now().year  # ใช้ปีปัจจุบันถ้าแปลงไม่ได้

        months = [
            "ต.ค.", "พ.ย.", "ธ.ค.", "ม.ค.", "ก.พ.", "มี.ค.", 
            "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย."
        ]
        table_data = [
            ["กิจกรรมดำเนินงาน"] + [
                (f"ปี พ.ศ. {project_year_int - 1}" if i < 3 else f"ปี พ.ศ. {project_year_int}")
                for i in range(12)
            ],
            [""] + months,
        ]

        # ตรวจสอบว่ามีข้อมูลกิจกรรมหรือไม่
        activities = []
        if "activities" in project_data and project_data["activities"]:
            activities = project_data["activities"]
        elif "project_activities_json" in project_data and project_data["project_activities_json"]:
            try:
                activities = json.loads(project_data["project_activities_json"])
            except (json.JSONDecodeError, TypeError):
                activities = []

        for activity in activities:
            wrapped_activity = "\n".join(
                simpleSplit(activity["activity"], "THSarabunNew", 8, 6 * cm)
            )
            row = [wrapped_activity] + [
                "X" if month in activity["months"] else "" for month in months
            ]
            table_data.append(row)

        # เพิ่มส่วนของตัวชี้วัดเป้าหมายผลผลิต
        table_data.append(["ตัวชี้วัดเป้าหมายผลผลิต", ""] + [""] * 11)

        # เพิ่มแถวตัวชี้วัดเชิงปริมาณ
        quantity_indicator = project_data.get('project_quantity_indicator', '')
        if not quantity_indicator and 'quantity_indicator' in project_data:
            quantity_indicator = project_data.get('quantity_indicator', '')
        table_data.append(["เชิงปริมาณ", quantity_indicator] + [""] * 11)

        # เพิ่มแถวตัวชี้วัดเชิงคุณภาพ
        quality_indicator = project_data.get('project_quality_indicator', '')
        if not quality_indicator and 'quality_indicator' in project_data:
            quality_indicator = project_data.get('quality_indicator', '')
        table_data.append(["เชิงคุณภาพ", quality_indicator] + [""] * 11)

        # เพิ่มแถวตัวชี้วัดเชิงเวลา
        time_indicator = project_data.get('project_time_indicator', '')
        if not time_indicator and 'time_indicator' in project_data:
            time_indicator = project_data.get('time_indicator', '')
        table_data.append(["เชิงเวลา", time_indicator] + [""] * 11)

        # เพิ่มแถวตัวชี้วัดเชิงค่าใช้จ่าย
        cost_indicator = project_data.get('project_cost_indicator', '')
        if not cost_indicator and 'cost_indicator' in project_data:
            cost_indicator = project_data.get('cost_indicator', '')
        table_data.append(["เชิงค่าใช้จ่าย", cost_indicator] + [""] * 11)

        col_widths = [8 * cm] + [0.7 * cm] * 12
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), "THSarabunNew", 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (1, 0), (-1, -1), "CENTER"),
            ('VALIGN', (0, 0), (-1, -1), "MIDDLE"),
            ('SPAN', (1, 0), (3, 0)),  # ปี พ.ศ. แรก (3 เดือน)
            ('SPAN', (4, 0), (-1, 0)),  # ปี พ.ศ. ถัดไป (9 เดือน)
            ('WORDWRAP', (0, 0), (0, -1), True),
            ('SPAN', (1, -5), (-1, -5)),  # ส่วนหัวของตัวชี้วัด
            ('SPAN', (1, -4), (-1, -4)),  # เชิงปริมาณ
            ('SPAN', (1, -3), (-1, -3)),  # เชิงคุณภาพ
            ('SPAN', (1, -2), (-1, -2)),  # เชิงเวลา
            ('SPAN', (1, -1), (-1, -1)),  # เชิงค่าใช้จ่าย
            ('BACKGROUND', (0, -5), (0, -1), colors.lightgrey),
        ]))

        content.append(table)

        # เพิ่มส่วน "ผลที่คาดว่าจะเกิด (Impact)"
        content.append(Paragraph("16. ผลที่คาดว่าจะเกิด (Impact)", styles["Heading2"]))
        
        # ตรวจสอบและใช้ฟิลด์ expected_results หรือ project_expected_results
        expected_results = project_data.get('project_expected_results', '')
        if not expected_results and 'expected_results' in project_data:
            expected_results = project_data.get('expected_results', '')
            
        if expected_results:
            content.append(Paragraph(expected_results, styles["Normal"]))
        else:
            content.append(Paragraph("ไม่มีข้อมูล", styles["Normal"]))

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
                'join_name': row[1],
                'join_email': row[2],
                'evaluation_score': row[3],
                'evaluation_comments': row[4],
                'evaluation_date': row[5]
            })
        
        # เตรียมข้อมูลสรุป
        summary_data = {
            'total_evaluations': summary[0],
            'average_score': summary[1],
            'min_score': summary[2],
            'max_score': summary[3]
        }
    
    return render_template(
        'teacher_evaluation_project_detail.html', 
        evaluations=evaluation_list,
        project_id=project_id,
        project_name=project_name,
        summary=summary_data
    )
@app.route("/project/<int:project_id>/evaluation", methods=["GET", "POST"])
def project_evaluation(project_id):
    # สร้างการเชื่อมต่อฐานข้อมูล
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # ตรวจสอบโครงการและสถานะโครงการ
        cursor.execute("""
            SELECT project_name, project_endtime, project_statusStart 
            FROM project 
            WHERE project_id = %s
        """, (project_id,))
        project = cursor.fetchone()
        
        if not project:
            flash("ไม่พบโครงการ", "error")
            return redirect(url_for("active_projects"))

        # เช็คว่าโครงการปิดแล้วหรือยัง
        if project['project_statusStart'] != 2:
            flash("ยังไม่สามารถประเมินโครงการได้ ณ ขณะนี้ เนื่องจากโครงการยังไม่เสร็จสิ้น", "warning")
            return redirect(url_for("project_detail", project_id=project_id))

        # รับข้อมูลชื่อและอีเมลจาก URL parameters (ถ้ามี)
        join_name = request.args.get('name', '')
        join_email = request.args.get('email', '')
        
        # ถ้ามีอีเมล ให้ตรวจสอบว่าเคยประเมินแล้วหรือไม่
        if join_email:
            cursor.execute("""
                SELECT j.join_id, pe.evaluation_id
                FROM `join` j
                LEFT JOIN project_evaluation pe ON j.join_id = pe.join_id
                WHERE j.project_id = %s AND j.join_email = %s
            """, (project_id, join_email))
            existing_user = cursor.fetchone()
            
            if existing_user and existing_user['evaluation_id']:
                flash(f"คุณได้ทำการประเมินโครงการนี้ไปแล้ว ไม่สามารถประเมินซ้ำได้", "warning")
                return redirect(url_for("project_detail", project_id=project_id))
            
            # ถ้ามีข้อมูลการลงทะเบียนแต่ยังไม่เคยประเมิน
            join_id = existing_user['join_id'] if existing_user else None

        if request.method == "POST":
            # เก็บ log เพื่อตรวจสอบ
            print("ได้รับการส่งฟอร์มประเมิน:")
            print(f"Form data: {request.form}")
            
            # รับข้อมูลจาก form
            evaluation_score = request.form.get('evaluation_score')
            evaluation_comments = request.form.get('evaluation_comments', '')
            
            # ถ้าไม่มีชื่อและอีเมลใน URL parameters ให้ใช้จากฟอร์ม
            if not join_name:
                join_name = request.form.get('join_name', '')
            if not join_email:
                join_email = request.form.get('join_email', '')
            join_telephone = request.form.get('join_telephone', '')
            
            print(f"evaluation_score: {evaluation_score}")
            
            # ตรวจสอบความครบถ้วนของข้อมูล
            if not evaluation_score:
                print("ไม่พบคะแนนการประเมิน")
                flash('กรุณาให้คะแนนการประเมิน', 'error')
                return render_template("project_evaluation.html", 
                                     project_name=project['project_name'], 
                                     project_id=project_id,
                                     join_name=join_name,
                                     join_email=join_email)

            # แปลงค่าคะแนนเป็น float
            try:
                eval_score_float = float(evaluation_score)
            except ValueError:
                print(f"ไม่สามารถแปลงค่า evaluation_score: {evaluation_score} เป็น float ได้")
                flash('คะแนนการประเมินไม่ถูกต้อง', 'error')
                return render_template("project_evaluation.html", 
                                     project_name=project['project_name'], 
                                     project_id=project_id,
                                     join_name=join_name,
                                     join_email=join_email)
            
            try:
                # ถ้ามีอีเมลและชื่อ
                if join_email and join_name:
                    # ตรวจสอบว่ามีข้อมูลในตาราง join หรือยัง
                    cursor.execute("""
                        SELECT join_id FROM `join` 
                        WHERE project_id = %s AND join_email = %s
                    """, (project_id, join_email))
                    existing_join = cursor.fetchone()
                    
                    if existing_join:
                        # มีข้อมูลแล้ว ใช้ join_id ที่มีอยู่
                        join_id = existing_join['join_id']
                    else:
                        # ยังไม่มีข้อมูล สร้างใหม่
                        telephone = join_telephone if join_telephone else "ไม่ระบุ"
                        cursor.execute("""
                            INSERT INTO `join` (project_id, join_name, join_email, join_telephone, join_status) 
                            VALUES (%s, %s, %s, %s, %s)
                        """, (project_id, join_name, join_email, telephone, 1))
                        join_id = cursor.lastrowid
                else:
                    # ไม่มีข้อมูลชื่อและอีเมล สร้างเป็นผู้ประเมินไม่ระบุชื่อ
                    anonymous_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    anonymous_name = f"ผู้ประเมินไม่ระบุชื่อ_{anonymous_timestamp}"
                    anonymous_email = f"anonymous_{anonymous_timestamp}@example.com"
                    anonymous_phone = f"000000{anonymous_timestamp[-4:]}"
                    
                    cursor.execute("""
                        INSERT INTO `join` (project_id, join_name, join_email, join_telephone, join_status) 
                        VALUES (%s, %s, %s, %s, %s)
                    """, (project_id, anonymous_name, anonymous_email, anonymous_phone, 1))
                    join_id = cursor.lastrowid
                
                # บันทึกการประเมิน
                print(f"กำลังบันทึกการประเมิน: project_id={project_id}, join_id={join_id}, score={eval_score_float}")
                cursor.execute("""
                    INSERT INTO project_evaluation 
                    (project_id, join_id, evaluation_score, evaluation_comments) 
                    VALUES (%s, %s, %s, %s)
                """, (
                    project_id, 
                    join_id, 
                    eval_score_float, 
                    evaluation_comments
                ))
                conn.commit()
                print("บันทึกการประเมินสำเร็จ")
                flash('บันทึกการประเมินสำเร็จ ขอบคุณสำหรับการประเมิน', 'success')
                return redirect(url_for('project_detail', project_id=project_id))

            except mysql.connector.Error as insert_err:
                conn.rollback()
                print(f"เกิดข้อผิดพลาดในการบันทึกการประเมิน: {insert_err}")
                flash(f'เกิดข้อผิดพลาดในการบันทึกการประเมิน: {insert_err}', 'error')
                return render_template("project_evaluation.html", 
                                     project_name=project['project_name'], 
                                     project_id=project_id,
                                     join_name=join_name,
                                     join_email=join_email)

    except mysql.connector.Error as err:
        print(f"เกิดข้อผิดพลาดในการเข้าถึงฐานข้อมูล: {err}")
        flash(f'เกิดข้อผิดพลาด: {err}', 'error')
        return redirect(url_for('active_projects'))
    
    finally:
        cursor.close()
        conn.close()

    # แสดงฟอร์มประเมินพร้อมข้อมูลชื่อและอีเมลที่มาจาก URL parameters
    return render_template("project_evaluation.html", 
                         project_name=project['project_name'], 
                         project_id=project_id,
                         join_name=join_name,
                         join_email=join_email)



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
            
            # สร้าง PDF ใหม่หลังจากบันทึกข้อความ
            generate_summary_pdf(project_id)
            
            flash("บันทึกสรุปรายงานโครงการเรียบร้อยแล้ว", "success")
            return redirect(url_for("project_summary", project_id=project_id))
        except mysql.connector.Error as err:
            flash(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {err}", "error")
            return redirect(url_for("project_summary", project_id=project_id))

# ฟังก์ชันสร้าง PDF สรุปผลการดำเนินโครงการ
def generate_summary_pdf(project_id):
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลโครงการ
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
            logging.error(f"ไม่พบข้อมูลโครงการ ID: {project_id}")
            return None
        
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
        
        # ดึงข้อมูลการเข้าร่วม (แทนการดึงคะแนนทดสอบ)
        cursor.execute("""
            SELECT COUNT(*) as total_participants
            FROM `join`
            WHERE project_id = %s AND join_status = 1
        """, (project_id,))
        attendance_data = cursor.fetchone()
        
        attendance_dict = {
            "total_participants": int(attendance_data[0] if attendance_data[0] else 0),
            "attendance_rate": round((int(attendance_data[0] if attendance_data[0] else 0) / float(project[8])) * 100, 2) if int(project[8]) > 0 else 0
        }
        
        # คำนวณประสิทธิผลโครงการ (ใช้เฉพาะผลการประเมินความพึงพอใจ)
        project_success = {}
        if evaluation_dict["total_evaluations"] > 0:
            # มีผลประเมินความพึงพอใจ
            score = float(evaluation_dict["average_score"]) * 20  # ปรับสเกลจาก 0-5 เป็น 0-100
            project_success = {
                "score": round(score, 2),
                "level": get_success_level(score)
            }
        else:
            # ไม่มีข้อมูลประเมิน
            project_success = {
                "score": 0.0,
                "level": "ไม่สามารถประเมินได้"
            }
    
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
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
        styles["Normal"].fontSize = 12
        styles["Heading1"].fontName = "THSarabunNew-Bold"
        styles["Heading1"].fontSize = 16
        styles["Heading2"].fontName = "THSarabunNew-Bold"
        styles["Heading2"].fontSize = 14
        styles["Heading3"].fontName = "THSarabunNew"
        styles["Heading3"].fontSize = 12

        def header(canvas, doc):
            canvas.saveState()
            page_width = doc.pagesize[0]
            page_height = doc.pagesize[1]

            logo_path = os.path.join(app.static_folder, "2.png")

            if os.path.exists(logo_path):
                try:
                    img = Image.open(logo_path)
                    img = img.convert("RGB")
                    img_buffer = BytesIO()
                    img.save(img_buffer, format="PNG")
                    img_buffer.seek(0)

                    logo_width = 0.7 * inch
                    logo_height = 0.7 * inch
                    logo_x = (page_width - logo_width) / 2
                    logo_y = page_height - 0.7 * inch

                    canvas.drawImage(
                        ImageReader(img_buffer),
                        logo_x,
                        logo_y,
                        width=logo_width,
                        height=logo_height,
                    )
                except Exception as e:
                    print(f"Error loading logo: {e}")
            else:
                print(f"Logo file not found at {logo_path}")

            canvas.setFont("THSarabunNew-Bold", 16)
            canvas.drawCentredString(
                page_width / 2, page_height - 1.1 * inch, "มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน"
            )
            canvas.setFont("THSarabunNew", 14)
            canvas.drawCentredString(
                page_width / 2, page_height - 1.3 * inch, "วิทยาเขต ขอนแก่น"
            )
            canvas.drawCentredString(
                page_width / 2,
                page_height - 1.5 * inch,
                "สรุปผลการดำเนินโครงการ"
            )
            canvas.drawCentredString(
                page_width / 2,
                page_height - 1.7 * inch,
                "-----------------------------------------------------"
            )

            # วันที่พิมพ์เอกสาร
            today = datetime.now().strftime("%d/%m/%Y")
            canvas.setFont("THSarabunNew", 10)
            canvas.drawRightString(
                page_width - 72, page_height - 0.7 * inch, f"พิมพ์เมื่อ: {today}"
            )

            # หมายเลขหน้า
            canvas.setFont("THSarabunNew", 10)
            page_num = f"หน้า {canvas.getPageNumber()}"
            canvas.drawRightString(
                page_width - 72, 30, page_num
            )

            canvas.restoreState()

        # เนื้อหา PDF
        content = []
        content.append(Spacer(1, 2 * inch))  # เพิ่มระยะห่างด้านบน
        
        # ข้อมูลโครงการ
        content.append(Paragraph("ข้อมูลโครงการ", styles["Heading2"]))
        content.append(Spacer(1, 0.1 * inch))
        
        # สร้างตารางข้อมูลโครงการ
        project_data = [
            ["ชื่อโครงการ:", project[1]],
            ["ผู้รับผิดชอบโครงการ:", project[15]],
            ["สาขาวิชา:", project[16]],
            ["ประเภทงบประมาณ:", project[2]],
            ["ปีงบประมาณ:", str(project[3])],
            ["งบประมาณ:", f"{project[11]:,.2f} บาท"],
            ["สถานที่จัด:", project[5]],
            ["ระยะเวลา:", f"{project[6].strftime('%d/%m/%Y')} - {project[7].strftime('%d/%m/%Y')}"],
            ["จำนวนผู้เข้าร่วมเป้าหมาย:", f"{project[8]} คน"],
            ["วันที่เสร็จสิ้น:", f"{project[14].strftime('%d/%m/%Y')}" if project[14] else "ไม่ระบุ"],
        ]
        
        # ตารางข้อมูลโครงการ
        project_info_table = Table(project_data, colWidths=[120, 300])
        project_info_table.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), 'THSarabunNew', 12),
            ('FONT', (0,0), (0,-1), 'THSarabunNew-Bold', 12),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.white),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        
        content.append(project_info_table)
        content.append(Spacer(1, 0.2 * inch))
        
        # ผลการดำเนินงาน
        content.append(Paragraph("ผลการดำเนินงาน", styles["Heading2"]))
        content.append(Spacer(1, 0.1 * inch))
        
        # ตารางสรุปการเข้าร่วม
        participation_data = [
            ["สรุปการเข้าร่วม"],
            [f"- จำนวนผู้เข้าร่วม: {participant_count} คน ({attendance_dict['attendance_rate']:.1f}% ของเป้าหมาย)"]
        ]
        
        participation_table = Table(participation_data, colWidths=[420])
        participation_table.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), 'THSarabunNew', 12),
            ('FONT', (0,0), (0,0), 'THSarabunNew-Bold', 12),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.white),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        
        content.append(participation_table)
        content.append(Spacer(1, 0.1 * inch))
        
        # ตารางสรุปผลการประเมินความพึงพอใจ
        eval_data = [
            ["สรุปผลการประเมินความพึงพอใจ"],
            [f"- จำนวนผู้ประเมิน: {evaluation_dict['total_evaluations']} คน"],
            [f"- คะแนนเฉลี่ย: {evaluation_dict['average_score']:.2f}/5 คะแนน"],
            [f"- คะแนนต่ำสุด: {evaluation_dict['min_score']:.1f} คะแนน"],
            [f"- คะแนนสูงสุด: {evaluation_dict['max_score']:.1f} คะแนน"]
        ]
        
        eval_table = Table(eval_data, colWidths=[420])
        eval_table.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), 'THSarabunNew', 12),
            ('FONT', (0,0), (0,0), 'THSarabunNew-Bold', 12),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.white),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        
        content.append(eval_table)
        content.append(Spacer(1, 0.1 * inch))
        
        # ตารางประสิทธิผลโครงการ
        effectiveness_data = [
            ["ประสิทธิผลโครงการ"],
            [f"- ประสิทธิผลรวม: {project_success['score']}% ({project_success['level']})"],
        ]
        
        effectiveness_text = "- การดำเนินโครงการครั้งนี้บรรลุวัตถุประสงค์"
        if project_success['score'] >= 80:
            effectiveness_text += "อยู่ในระดับดีมาก ประสบความสำเร็จตามเป้าหมายที่ตั้งไว้"
        elif project_success['score'] >= 70:
            effectiveness_text += "อยู่ในระดับดี ส่วนใหญ่บรรลุตามเป้าหมายที่ตั้งไว้"
        elif project_success['score'] >= 60:
            effectiveness_text += "อยู่ในระดับค่อนข้างดี บรรลุตามเป้าหมายหลักที่สำคัญ"
        elif project_success['score'] >= 50:
            effectiveness_text += "อยู่ในระดับพอใช้ บรรลุตามเป้าหมายได้บางส่วน"
        else:
            effectiveness_text += "อยู่ในระดับที่ควรปรับปรุง ยังไม่บรรลุตามเป้าหมายที่ตั้งไว้"
            
        effectiveness_data.append([effectiveness_text])
        
        effectiveness_table = Table(effectiveness_data, colWidths=[420])
        effectiveness_table.setStyle(TableStyle([
            ('FONT', (0,0), (-1,-1), 'THSarabunNew', 12),
            ('FONT', (0,0), (0,0), 'THSarabunNew-Bold', 12),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.white),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        
        content.append(effectiveness_table)
        content.append(Spacer(1, 0.3 * inch))
        
        # ข้อความสรุปรายงาน (ถ้ามี)
        if project[17]:  # summary_text
            content.append(Paragraph("ข้อความสรุปผลการดำเนินโครงการ", styles["Heading2"]))
            content.append(Spacer(1, 0.1 * inch))
            
            # แปลงข้อความที่มีการขึ้นบรรทัดใหม่เป็นย่อหน้า
            summary_lines = project[17].split("\n")
            for line in summary_lines:
                if line.strip():  # ข้ามบรรทัดว่าง
                    content.append(Paragraph(line, styles["Normal"]))
                    content.append(Spacer(1, 0.05 * inch))
            
            content.append(Spacer(1, 0.2 * inch))
        
        # สร้าง PDF
        doc.build(content, onFirstPage=header, onLaterPages=header)
        buffer.seek(0)
        
        # บันทึก PDF ลงฐานข้อมูล
        with get_db_cursor() as (db, cursor):
            query = "UPDATE project SET summary_pdf = %s WHERE project_id = %s"
            cursor.execute(query, (buffer.getvalue(), project_id))
            db.commit()
            
        return True
    except Exception as e:
        logging.error(f"Error creating summary PDF: {e}", exc_info=True)
        return False

# Route สำหรับดาวน์โหลด PDF สรุปผลการดำเนินโครงการ
@app.route("/download_summary_pdf/<int:project_id>")
@login_required("teacher", "admin")
def download_summary_pdf(project_id):
    try:
        with get_db_cursor() as (db, cursor):
            # ถ้าเป็น admin สามารถเข้าถึงได้ทุกโครงการ แต่ถ้าเป็น teacher ต้องเป็นโครงการของตัวเอง
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
                # ลองสร้าง PDF ใหม่
                if generate_summary_pdf(project_id):
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
            
            return send_file(
                BytesIO(pdf_content),
                as_attachment=True,
                download_name=f"สรุปโครงการ_{project_name}.pdf",
                mimetype="application/pdf",
            )
            
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
@app.route("/close_project", methods=["POST"])
@login_required("teacher")
def close_project():
    if "teacher_id" not in session:
        flash("คุณไม่มีสิทธิ์ในการดำเนินการนี้", "error")
        return redirect(url_for("home"))

    project_id = request.form.get("project_id")
    
    with get_db_cursor() as (db, cursor):
        try:
            # ตรวจสอบสิทธิ์การปิดโครงการ
            cursor.execute("""
                SELECT p.teacher_id, p.project_status, p.project_statusStart, p.project_name 
                FROM project p
                WHERE p.project_id = %s
            """, (project_id,))
            project = cursor.fetchone()

            if not project:
                flash("ไม่พบโครงการ", "error")
                return redirect(url_for("teacher_projects"))

            # ตรวจสอบว่าเป็นอาจารย์เจ้าของโครงการ
            if project[0] != session['teacher_id']:
                flash("คุณไม่มีสิทธิ์ปิดโครงการนี้", "error")
                return redirect(url_for("teacher_projects"))

            # ตรวจสอบสถานะโครงการ
            if project[1] != 2 or project[2] != 1:
                flash("ไม่สามารถปิดโครงการได้ ณ ขณะนี้", "error")
                return redirect(url_for("project_detail", project_id=project_id))

            # อัปเดตสถานะโครงการเป็นปิด
            query = """
            UPDATE project 
            SET 
                project_statusStart = 2,  # สถานะ 2 คือปิดโครงการ
                project_close_date = NOW()  # เพิ่มวันที่ปิดโครงการ
            WHERE project_id = %s
            """
            cursor.execute(query, (project_id,))
            db.commit()
            
            # สร้าง URL สำหรับประเมินโครงการ
            # หมายเหตุ: เพิ่ม request.host_url เพื่อให้ URL เป็น absolute URL
            base_url = request.host_url.rstrip('/')
            
            # ส่งอีเมลแจ้งเตือนผู้เข้าร่วมว่าสามารถประเมินโครงการได้แล้ว
            cursor.execute("""
                SELECT j.join_email, j.join_name 
                FROM `join` j 
                WHERE j.project_id = %s AND j.join_status = 1
            """, (project_id,))
            participants = cursor.fetchall()
            
            project_name = project[3]
            
            # ส่งอีเมลแจ้งเตือนผู้เข้าร่วมโครงการทุกคน
            for participant in participants:
                participant_email = participant[0]
                participant_name = participant[1]
                
                # สร้าง URL ที่มีข้อมูลชื่อและอีเมลเป็น parameters
                evaluation_url = f"{base_url}{url_for('project_evaluation', project_id=project_id)}?name={urllib.parse.quote(participant_name)}&email={urllib.parse.quote(participant_email)}"
                
                subject = f"เชิญประเมินโครงการ: {project_name}"
                message = f"""เรียน คุณ{participant_name}

โครงการ "{project_name}" ได้เสร็จสิ้นแล้ว เราขอเชิญท่านร่วมประเมินความพึงพอใจในโครงการนี้

ท่านสามารถเข้าไปประเมินได้โดยคลิกที่ลิงก์ด้านล่าง:
{evaluation_url}

ลิงก์นี้เชื่อมต่อกับข้อมูลของท่านโดยตรง ท่านไม่จำเป็นต้องกรอกชื่อและอีเมลอีกครั้ง

ขอบคุณที่ร่วมเป็นส่วนหนึ่งของโครงการ
ทีมงานบริหารโครงการ
"""
                send_email_notification(subject, message, participant_email)

            flash("ปิดโครงการเรียบร้อยแล้วและได้ส่งอีเมลเชิญผู้เข้าร่วมประเมินโครงการแล้ว", "success")
            return redirect(url_for("teacher_projects"))

        except mysql.connector.Error as err:
            flash(f"เกิดข้อผิดพลาด: {err}", "error")
            return redirect(url_for("project_detail", project_id=project_id))
@app.route("/evaluate_project/<int:project_id>")
def evaluate_project(project_id):
    # ตรวจสอบการล็อกอิน
    if 'user_type' not in session or session['user_type'] != 'teacher':
        flash('คุณต้องล็อกอินก่อน', 'error')
        return redirect(url_for('login'))
    
    # ตรวจสอบว่าเคยอนุมัติเข้าร่วมโครงการนี้แล้วหรือยัง
    with get_db_cursor() as (db, cursor):
        # ดึงข้อมูลโครงการ
        cursor.execute("""
            SELECT p.project_name 
            FROM project p 
            WHERE p.project_id = %s
        """, (project_id,))
        project = cursor.fetchone()
        
        if not project:
            flash('ไม่พบโครงการ', 'error')
            return redirect(url_for('active_projects'))
        
        # ตรวจสอบว่าเคยประเมินไปแล้วหรือยัง
        cursor.execute("""
            SELECT j.join_id, j.join_name, j.join_email 
            FROM `join` j
            WHERE j.project_id = %s 
            AND j.join_status = 1 
            AND j.join_email = %s
        """, (project_id, session.get('teacher_email')))
        participant = cursor.fetchone()
        
        if not participant:
            flash('คุณไม่มีสิทธิ์ประเมินโครงการนี้', 'error')
            return redirect(url_for('active_projects'))
        
        # ตรวจสอบว่าเคยประเมินไปแล้วหรือยัง
        cursor.execute("""
            SELECT COUNT(*) 
            FROM project_evaluation 
            WHERE project_id = %s AND join_id = %s
        """, (project_id, participant[0]))
        existing_evaluation = cursor.fetchone()[0]
        
        if existing_evaluation > 0:
            flash('คุณได้ประเมินโครงการนี้ไปแล้ว', 'warning')
            return redirect(url_for('active_projects'))
        
        project_name = project[0]
        join_id = participant[0]
        
    if request.method == 'POST':
        # รับข้อมูลการประเมิน
        evaluation_score = request.form.get('evaluation_score')
        evaluation_comments = request.form.get('evaluation_comments', '')
        
        # ตรวจสอบความถูกต้องของข้อมูล
        try:
            with get_db_cursor() as (db, cursor):
                query = """
                INSERT INTO project_evaluation 
                (project_id, join_id, evaluation_score, evaluation_comments) 
                VALUES (%s, %s, %s, %s)
                """
                cursor.execute(query, (
                    project_id, join_id, 
                    evaluation_score, 
                    evaluation_comments
                ))
                db.commit()
                
            flash('บันทึกการประเมินสำเร็จ', 'success')
            return redirect(url_for('active_projects'))
        
        except mysql.connector.Error as err:
            flash(f'เกิดข้อผิดพลาดในการบันทึกการประเมิน: {err}', 'error')
    
    return render_template('project_evaluation.html', 
                           project_id=project_id, 
                           project_name=project_name)
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
        branch_name = request.form["branch_name"]

        with get_db_cursor() as (db, cursor):
            query = "INSERT INTO branch (branch_name) VALUES (%s)"
            cursor.execute(query, (branch_name,))
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
    if request.method == "POST":
        branch_id = request.form["branch_id"]
        teacher_name = request.form["teacher_name"]
        teacher_username = request.form["teacher_username"]
        teacher_password = request.form["teacher_password"]
        teacher_phone = request.form["teacher_phone"]
        teacher_email = request.form["teacher_email"]

        if "admin_id" in session:
            return redirect(url_for("admin_home"))

    if "admin_id" in session:
        branches = get_branches_from_database()
        teachers = get_teachers_from_database()
        return render_template(
            "edit_basic_info.html", teachers=teachers, branches=branches
        )
    else:
        return redirect(url_for("login"))


def get_teacher_by_id(teacher_id):
    with get_db_cursor() as (db, cursor):
        query = """SELECT t.teacher_id, t.teacher_name, t.teacher_username, t.teacher_password, 
                          t.teacher_phone, t.teacher_email, b.branch_name
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
        if teacher:
            return render_template("edit_teacher.html", teacher=teacher)
        else:
            return "Teacher not found"
    elif request.method == "POST":
        teacher_name = request.form["teacher_name"]
        teacher_username = request.form["teacher_username"]
        
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
   

        update_teacher(
            teacher_id,
            teacher_name,
            teacher_username,
            teacher_password,
            teacher_phone,
            teacher_email,
          
        )

        return redirect(url_for("edit_basic_info"))

def delete_teacher(teacher_id):
    with get_db_cursor() as (db, cursor):
        query = "DELETE FROM teacher WHERE teacher_id = %s"
        cursor.execute(query, (teacher_id,))
        db.commit()


@app.route("/delete_teacher/<int:teacher_id>", methods=["POST"])
def delete_teacher_route(teacher_id):
    delete_teacher(teacher_id)
    return redirect(url_for("teacher_home"))
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
        query = "SELECT branch_id, branch_name FROM branch"
        cursor.execute(query)
        branches = cursor.fetchall()
    return branches

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
@app.route("/update_join_status/<int:join_id>", methods=["POST"])
@login_required("teacher")
def update_join_status(join_id):
    if "teacher_id" not in session:
        flash("คุณไม่มีสิทธิ์ในการดำเนินการนี้", "error")
        return redirect(url_for("home"))

    new_status = request.form.get("join_status")
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # ดึงข้อมูลผู้เข้าร่วมและโครงการ
        cursor.execute(
            """SELECT j.join_id, j.join_name, j.join_email, p.project_id, p.project_name, j.join_status, p.project_dotime
               FROM `join` j 
               JOIN project p ON j.project_id = p.project_id 
               WHERE j.join_id = %s""", 
            (join_id,)
        )
        participant_info = cursor.fetchone()
        
        if not participant_info:
            flash("ไม่พบข้อมูลผู้สมัคร", "error")
            return redirect(request.referrer)
        
        # ถ้าสถานะคือ "1" (อนุมัติ) และยังไม่เคยอนุมัติมาก่อน
        if new_status == '1' and participant_info['join_status'] != 1:
            # สร้างโทเค็นสำหรับยืนยัน
            token = generate_confirmation_token(join_id, participant_info['join_email'])
            
            # สร้าง URL สำหรับยืนยัน
            base_url = request.host_url.rstrip('/')
            confirmation_url = f"{base_url}{url_for('confirm_participation', join_id=join_id, token=token)}"
            
            # ส่งอีเมลยืนยันให้ผู้สมัคร
            subject = f"ยืนยันการเข้าร่วมโครงการ: {participant_info['project_name']}"
            message = f"""
เรียน {participant_info['join_name']} 

ยินดีด้วย! คำขอเข้าร่วมโครงการ "{participant_info['project_name']}" ของคุณได้รับการพิจารณาอนุมัติในเบื้องต้นแล้ว

กรุณายืนยันการเข้าร่วมโครงการโดยคลิกที่ลิงก์ด้านล่าง:
{confirmation_url}

*สำคัญ*: หากไม่ได้คลิกลิงก์ยืนยันการเข้าร่วม คุณจะไม่ได้รับอนุมัติให้เข้าร่วมโครงการนี้
และการยืนยันนี้จะหมดอายุใน 1 วันก่อนวันเริ่มโครงการ หากไม่ได้รับการยืนยันภายในเวลาดังกล่าว 
ระบบจะยกเลิกการลงทะเบียนของคุณโดยอัตโนมัติ

หากคุณไม่ได้ลงทะเบียนเข้าร่วมโครงการนี้ กรุณาละเว้นอีเมลฉบับนี้

ขอแสดงความนับถือ
ทีมงานบริหารโครงการ
มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น
"""
            # ส่งอีเมล
            email_result = send_email_notification(subject, message, participant_info['join_email'])
            
            # อัปเดตสถานะเป็น "รอการยืนยัน" (สถานะ 3)
            cursor.execute(
                "UPDATE `join` SET join_status = 3 WHERE join_id = %s",
                (join_id,)
            )
            conn.commit()
            
            if email_result:
                flash(f"ส่งอีเมลยืนยันไปยัง {participant_info['join_name']} แล้ว รอผู้สมัครคลิกลิงก์ยืนยันในอีเมล", "success")
            else:
                flash(f"ไม่สามารถส่งอีเมลยืนยันได้ กรุณาลองอีกครั้ง", "warning")
                
        # ถ้าสถานะคือ "2" (ไม่อนุมัติ)
        elif new_status == '2':
            # อัปเดตสถานะเป็นไม่อนุมัติ
            cursor.execute(
                "UPDATE `join` SET join_status = 2 WHERE join_id = %s",
                (join_id,)
            )
            conn.commit()
            
            # ส่งอีเมลแจ้งเตือน
            subject = f"ผลการพิจารณาการเข้าร่วมโครงการ: {participant_info['project_name']}"
            message = f"""
เรียน {participant_info['join_name']} 

ขออภัย คำขอเข้าร่วมโครงการ "{participant_info['project_name']}" ของคุณไม่ได้รับการอนุมัติ

หากมีข้อสงสัยประการใด กรุณาติดต่อผู้ประสานงานโครงการ

ขอแสดงความนับถือ
ทีมงานบริหารโครงการ
มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน วิทยาเขตขอนแก่น
"""
            send_email_notification(subject, message, participant_info['join_email'])
            flash("อัพเดทสถานะการเข้าร่วมเป็น 'ไม่อนุมัติ' เรียบร้อยแล้ว", "success")
        
        # สถานะอื่นๆ (เช่น "0" - รอการอนุมัติ)
        else:
            cursor.execute(
                "UPDATE `join` SET join_status = %s WHERE join_id = %s",
                (new_status, join_id)
            )
            conn.commit()
            flash("อัพเดทสถานะการเข้าร่วมเรียบร้อยแล้ว", "success")
            
    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการอัพเดทสถานะ: {err}", "error")
    finally:
        cursor.close()
        conn.close()

    return redirect(request.referrer)
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


# ตรวจสอบข้อมูลใหม่ทุกๆ 5 นาที
if __name__ == "__main__":
    init_scheduler(app)
    app.run(debug=True, port=5000)
