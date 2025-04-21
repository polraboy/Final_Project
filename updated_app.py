from reportlab.lib.enums import TA_CENTER
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, send_file
import mysql.connector
import base64
import os
from contextlib import contextmanager
from fpdf import FPDF, XPos, YPos, Align
from io import BytesIO
from functools import wraps
from PIL import Image
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
from reportlab.lib.utils import ImageReader
import logging

app = Flask(__name__)
app.secret_key = "your_secret_key"
app.static_folder = 'static'
# ตั้งค่าการบันทึกล็อก
logging.basicConfig(level=logging.INFO)

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ลงทะเบียนฟอนต์ไทย
pdfmetrics.registerFont(TTFont('THSarabunNew', 'THSarabunNew.ttf'))

class ThaiPDF(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.add_thai_font()

    def add_thai_font(self):
        font_path = os.path.join(os.path.dirname(__file__), 'THSarabunNew.ttf')
        if os.path.exists(font_path):
            self.add_font("THSarabunNew", "", font_path, uni=True)
            self.add_font("THSarabunNew", "B", font_path, uni=True)
        else:
            raise FileNotFoundError(f"ไม่พบไฟล์ฟอนต์ที่ {font_path}")

    def header(self):
        self.set_font('THSarabunNew', 'B', 16)
        self.cell(0, 10, 'รายละเอียดโครงการ', 0, 1, 'C')
        
    def footer(self):
        self.set_y(-15)
        self.set_font('THSarabunNew', '', 8)
        self.cell(0, 10, f'หน้า {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, num, label):
        self.set_font('THSarabunNew', 'B', 14)
        self.cell(0, 6, f'{num}. {label}', 0, 1)
        self.ln(4)

    def chapter_body(self, body):
        self.set_font('THSarabunNew', '', 12)
        self.multi_cell(0, 5, body)
        self.ln()

    def add_thai_text(self, txt):
        encoded_text = txt.encode('latin-1', 'replace').decode('latin-1')
        self.multi_cell(0, 5, encoded_text)
class ProjectPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font('THSarabunNew', '', 'THSarabunNew.ttf', uni=True)
        self.add_font('THSarabunNew', 'B', 'THSarabunNew Bold.ttf', uni=True)

    def header(self):
        
        self.set_font('THSarabunNew', 'B', 16)
        self.cell(0, 10, 'มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน', 0, 1, 'C')
        self.cell(0, 10, 'วิทยาเขต....................................', 0, 1, 'C')
        self.cell(0, 10, 'หน่วยงาน....................................', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('THSarabunNew', '', 8)
        self.cell(0, 10, f'หน้า {self.page_no()}/{{nb}}', 0, 0, 'C')

    def chapter_title(self, num, label):
        self.set_font('THSarabunNew', 'B', 16)
        self.cell(0, 6, f'{num}. {label}', 0, 1)
        self.ln(4)

    def chapter_body(self, body):
        self.set_font('THSarabunNew', '', 16)
        self.multi_cell(0, 10, body)
        self.ln()
@app.route("/home")
def index():
    return "Welcome to the Flask Google Form Integration App"

def login_required(user_type):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_type" not in session or session["user_type"] != user_type:
                flash("คุณไม่มีสิทธิ์เข้าถึงหน้านี้", "error")
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

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
        host="localhost",
        user="root",
        password="",
        database="project"
         )

@app.route("/")
def home():
    with get_db_cursor() as (db, cursor):
        query = "SELECT constants_headname, constants_detail, constants_image FROM constants"
        cursor.execute(query)
        constants = cursor.fetchall()

    constants = [
        (c[0], c[1], base64.b64encode(c[2]).decode("utf-8")) for c in constants
    ]

    return render_template("home.html", constants=constants)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        with get_db_cursor() as (db, cursor):
            query_teacher = "SELECT * FROM teacher WHERE teacher_username = %s AND teacher_password = %s"
            cursor.execute(query_teacher, (username, password))
            teacher = cursor.fetchone()

            if teacher:
                session.clear()  # Clear any existing session data
                session["teacher_id"] = teacher[0]
                session["teacher_name"] = teacher[1]
                session["user_type"] = "teacher"
                return redirect(url_for("teacher_home"))
            else:
                query_admin = "SELECT * FROM admin WHERE admin_username = %s AND admin_password = %s"
                cursor.execute(query_admin, (username, password))
                admin = cursor.fetchone()

                if admin:
                    session.clear()  # Clear any existing session data
                    session["admin_id"] = admin[0]
                    session["admin_name"] = admin[1]
                    session["user_type"] = "admin"
                    return redirect(url_for("admin_home"))
                else:
                    flash("Login failed. Please check your username and password.", "error")

    return render_template("login.html")


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
    return redirect(url_for("login"))


@app.route("/admin_home")
@login_required("admin")
def admin_home():
    if "user_type" not in session or session["user_type"] != "admin":
        return redirect(url_for("login"))
    if request.method == "POST":
        if "constant_headname" in request.form:
            constant_headname = request.form["constant_headname"]
            constant_detail = request.form["constant_detail"]
            constant_image = request.files["constant_image"]

            # ปรับขนาดรูปภาพและแปลงเป็น RGB
            img = Image.open(constant_image)
            img = img.convert("RGB")  # แปลง RGBA เป็น RGB
            img.thumbnail((800, 600))  # ปรับขนาดให้พอดีกับ 800x600 โดยรักษาสัดส่วน

            # แปลงรูปภาพเป็น binary
            img_io = BytesIO()
            img.save(img_io, "JPEG", quality=85)
            image_binary = img_io.getvalue()

            # บันทึกลงฐานข้อมูล
            try:
                with get_db_cursor() as (db, cursor):
                    query = "INSERT INTO constants (constants_headname, constants_detail, constants_image) VALUES (%s, %s, %s)"
                    cursor.execute(
                        query, (constant_headname, constant_detail, image_binary)
                    )
                    db.commit()

                flash("Constant added successfully!", "success")
            except mysql.connector.Error as err:
                flash(f"Error: {err}", "danger")

            return redirect(url_for("admin_home"))

        elif "delete_constant_headname" in request.form:
            constant_headname = request.form["delete_constant_headname"]
            try:
                with get_db_cursor() as (db, cursor):
                    query = "DELETE FROM constants WHERE constants_headname = %s"
                    cursor.execute(query, (constant_headname,))
                    db.commit()

                flash("Constant deleted successfully!", "success")
            except mysql.connector.Error as err:
                flash(f"Error: {err}", "danger")

            return redirect(url_for("admin_home"))

    # ดึงข้อมูล constants
    try:
        with get_db_cursor() as (db, cursor):
            query = "SELECT constants_headname, constants_detail, constants_image FROM constants"
            cursor.execute(query)
            constants = cursor.fetchall()

        # แปลงรูปภาพเป็น base64
        constants = [
            (c[0], c[1], base64.b64encode(c[2]).decode("utf-8")) for c in constants
        ]
    except mysql.connector.Error as err:
        flash(f"Error: {err}", "danger")
        constants = []

    return render_template("admin_home.html", constants=constants)


@app.route("/approve_project", methods=["GET", "POST"])
@login_required("admin")
def approve_project():
    if "admin_id" in session:
        if request.method == "POST":
            project_id = request.form.get("project_id")
            with get_db_cursor() as (db, cursor):
                query = "UPDATE project SET project_status = 2 WHERE project_id = %s"
                cursor.execute(query, (project_id,))
                db.commit()
            return redirect(url_for("approve_project"))

        projects = get_projects()
        return render_template(
            "approve_project.html", projects=projects, get_status=get_status
        )
    else:
        return redirect(url_for("login"))


@app.route("/teacher_home")
@login_required("teacher")
def teacher_home():
    if "user_type" not in session or session["user_type"] != "teacher":
        return redirect(url_for("login"))

    with get_db_cursor() as (db, cursor):
        query = "SELECT constants_headname, constants_detail, constants_image FROM constants"
        cursor.execute(query)
        constants = cursor.fetchall()

    constants = [
        (c[0], c[1], base64.b64encode(c[2]).decode("utf-8")) for c in constants
    ]

    return render_template("teacher_home.html", constants=constants)


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


@app.route('/project/<int:project_id>/join', methods=['GET', 'POST'])
def join_project(project_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT project_name, project_target FROM project WHERE project_id = %s", (project_id,))
    project = cursor.fetchone()
    
    if not project:
        flash('โครงการไม่พบ', 'error')
        return redirect(url_for('active_projects'))
    
    cursor.execute("SELECT COUNT(*) as current_count FROM `join` WHERE project_id = %s", (project_id,))
    result = cursor.fetchone()
    current_count = result['current_count']
    
    if current_count >= project['project_target']:
        flash('ขออภัย โครงการนี้มีผู้เข้าร่วมเต็มแล้ว', 'error')
        return redirect(url_for('project_detail', project_id=project_id))
    
    if request.method == 'POST':
        join_name = request.form['join_name']
        join_telephone = request.form['join_telephone']
        join_email = request.form['join_email']
        
        try:
            cursor.execute("""
                INSERT INTO `join` (join_name, join_telephone, join_email, project_id, join_status)
                VALUES (%s, %s, %s, %s, 0)
            """, (join_name, join_telephone, join_email, project_id))
            conn.commit()
            flash('คุณได้ลงทะเบียนเข้าร่วมโครงการเรียบร้อยแล้ว โปรดรอการอนุมัติ', 'success')
        except mysql.connector.Error as err:
            flash(f'เกิดข้อผิดพลาดในการลงทะเบียน: {err}', 'error')
        
        return redirect(url_for('project_detail', project_id=project_id))
    
    cursor.close()
    conn.close()
    return render_template('join_project.html', project=project, project_id=project_id, current_count=current_count)

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
        (project_id,)
    )
    participants = cursor.fetchall()

    cursor.close()
    conn.close()

    is_logged_in = 'teacher_id' in session

    return render_template(
        "project_participants.html", 
        project_id=project_id, 
        participants=participants,
        is_logged_in=is_logged_in
    )

@app.route('/uploads/<filename>')
@login_required("teacher")
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/download_project_pdf/<int:project_id>")
@login_required("teacher")
def download_project_pdf(project_id):
    teacher_id = session["teacher_id"]

    with get_db_cursor() as (db, cursor):
        query = """
            SELECT project_pdf, project_name 
            FROM project 
            WHERE project_id = %s AND teacher_id = %s
        """
        cursor.execute(query, (project_id, teacher_id))
        result = cursor.fetchone()

    if result and result[0]:
        pdf_content, project_name = result
        return send_file(
            BytesIO(pdf_content),
            as_attachment=True,
            download_name=f'{project_name}.pdf',
            mimetype='application/pdf'
        )
    else:
        flash('ไม่พบไฟล์ PDF สำหรับโครงการนี้', 'error')
        return redirect(url_for('teacher_projects'))
def compress_pdf(pdf_content):
    reader = PdfReader(io.BytesIO(pdf_content))
    writer = PdfWriter()

    for page in reader.pages:
        page.compress_content_streams()  # This is CPU intensive!
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()



def create_project_pdf(project_data):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)

        # ลงทะเบียนฟอนต์ไทย
        font_path = os.path.join(os.path.dirname(__file__), 'THSarabunNew.ttf')
        bold_font_path = os.path.join(os.path.dirname(__file__), 'THSarabunNew-Bold.ttf')

        pdfmetrics.registerFont(TTFont('THSarabunNew', font_path))
        if os.path.exists(bold_font_path):
            pdfmetrics.registerFont(TTFont('THSarabunNew-Bold', bold_font_path))
        else:
            logging.warning("THSarabunNew-Bold font not found, using regular font for bold text")
            pdfmetrics.registerFont(TTFont('THSarabunNew-Bold', font_path))

        # สร้างสไตล์
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='Center', alignment=CENTER, fontName='THSarabunNew', fontSize=16))
        styles['Normal'].fontName = 'THSarabunNew'
        styles['Normal'].fontSize = 12
        styles['Heading1'].fontName = 'THSarabunNew-Bold'
        styles['Heading1'].fontSize = 16
        styles['Heading1'].alignment = TA_CENTER
        styles['Heading2'].fontName = 'THSarabunNew-Bold'
        styles['Heading2'].fontSize = 14
        styles['Heading3'].fontName = 'THSarabunNew-Bold'
        styles['Heading3'].fontSize = 12

        def header(canvas, doc):
            canvas.saveState()
            # วาดเส้นขอบ
            canvas.setStrokeColorRGB(0, 0, 0)
            canvas.setLineWidth(1)
            canvas.rect(0.5*inch, 0.5*inch, doc.width, doc.height)
            
            # ดึงโลโก้จาก URL
            logo_url = "file:///C:/Users/PC/Desktop/my-project2567/static/4d9031c8-3f48-4f56-9208-327c0fc8a873.jpg"  # แทนที่ด้วย URL จริงของโลโก้
            try:
                response = requests.get(logo_url)
                if response.status_code == 200:
                    logo = Image(BytesIO(response.content), width=40, height=40)
                    logo.drawOn(canvas, 0.75*inch, doc.height + 0.25*inch)
                else:
                    logging.warning(f"Failed to fetch logo from {logo_url}")
            except Exception as e:
                logging.error(f"Error fetching logo: {e}")
            
            canvas.restoreState()

        content = []

        # หัวเรื่อง
        content.append(Paragraph('มหาวิทยาลัยเทคโนโลยีราชมงคลอีสาน', styles['Heading1']))
        content.append(Paragraph(f"วิทยาเขต ขอนแก่น", styles['Center']))
        content.append(Paragraph(f"งบประมาณ{project_data['project_budgettype']} ประจำปีงบประมาณ พ.ศ. {project_data['project_year']}", styles['Center']))
        content.append(Spacer(1, 0.5*inch))

        # ข้อมูลโครงการ
        content.append(Paragraph(f"1. ชื่อโครงการ: {project_data['project_name']}", styles['Normal']))
        content.append(Paragraph(f"2. ลักษณะโครงการ: {project_data['project_style']}", styles['Normal']))
        content.append(Paragraph("3. โครงการนี้สอดคล้องกับนโยบายชาติ และผลผลิต", styles['Heading2']))
        content.append(Paragraph(f"นโยบายที่ 4 : การศึกษา และเรียนรู้ การทะนุบำรุงศาสนา ศิลปะ และวัฒนธรรม", styles['Normal']))
        content.append(Paragraph(f"ผลผลิต : {project_data.get('output', '')}", styles['Normal']))
        content.append(Paragraph("4. ความสอดคล้องประเด็นยุทธศาสตร์ และตัวชี้วัด", styles['Heading2']))
        content.append(Paragraph(f"ประเด็นยุทธศาสตร์ที่ : {project_data.get('strategy', '')}", styles['Normal']))
        content.append(Paragraph(f"ตัวชี้วัดที่ : {project_data.get('indicator', '')}", styles['Normal']))
        content.append(Paragraph("5. ความสอดคล้องกับ Cluster / Commonality / Physical grouping", styles['Heading2']))
        content.append(Paragraph(f"Cluster : {project_data.get('cluster', '')}", styles['Normal']))
        content.append(Paragraph(f"Commonality : {project_data.get('commonality', '')}", styles['Normal']))
        content.append(Paragraph(f"Physical grouping : {project_data.get('physical_grouping', '')}", styles['Normal']))
        
        content.append(Paragraph(f"7. สถานที่ดำเนินงาน: {project_data['project_address']}", styles['Normal']))
        content.append(Paragraph(f"8. ระยะเวลาดำเนินการ: {project_data['project_dotime']} ถึง {project_data['project_endtime']}", styles['Normal']))
        content.append(Paragraph("9. หลักการและเหตุผล", styles['Heading2']))
        content.append(Paragraph(project_data.get('rationale', ''), styles['Normal']))
        content.append(Paragraph("10. วัตถุประสงค์", styles['Heading2']))
        content.append(Paragraph(project_data.get('objectives', ''), styles['Normal']))
        content.append(Paragraph("11. เป้าหมาย", styles['Heading2']))
        content.append(Paragraph(project_data.get('goals', ''), styles['Normal']))
        content.append(Paragraph(f"11.1 เป้าหมายเชิงผลผลิต (Output): {project_data.get('output_target', '')}", styles['Normal']))
        content.append(Paragraph(f"11.2 เป้าหมายเชิงผลลัพธ์ (Outcome): {project_data.get('outcome_target', '')}", styles['Normal']))
        content.append(Paragraph("12. กิจกรรมดำเนินงาน", styles['Heading2']))
        content.append(Paragraph(project_data.get('project_activity', ''), styles['Normal']))
        content.append(Paragraph("13. กลุ่มเป้าหมายผู้เข้าร่วมโครงการ", styles['Heading2']))
        content.append(Paragraph(project_data['project_target'], styles['Normal']))
        
        content.append(Paragraph("14. งบประมาณ", styles['Heading2']))
        content.append(Paragraph(f"งบประมาณโครงการ: {project_data['project_budget']} บาท", styles['Normal']))
        content.append(Paragraph("14.1 ค่าตอบแทน", styles['Heading3']))
        for item in project_data['compensation']:
            content.append(Paragraph(f"{item['description']}: {item['amount']} บาท", styles['Normal']))
        content.append(Paragraph(f"รวมค่าตอบแทน: {project_data['total_compensation']} บาท", styles['Normal']))
        content.append(Paragraph("14.2 ค่าใช้สอย", styles['Heading3']))
        for item in project_data['expenses']:
            content.append(Paragraph(f"{item['description']}: {item['amount']} บาท", styles['Normal']))
        content.append(Paragraph(f"รวมค่าใช้สอย: {project_data['total_expenses']} บาท", styles['Normal']))
        content.append(Paragraph(f"รวมค่าใช้จ่ายทั้งสิ้น: {project_data['grand_total']} บาท", styles['Normal']))

        # แผนปฏิบัติงาน
        content.append(Paragraph("15. แผนปฏิบัติงาน (แผนงาน) แผนการใช้จ่ายงบประมาณ (แผนเงิน) และตัวชี้วัดเป้าหมายผลผลิต", styles['Heading2']))
        
        months = ['ต.ค.', 'พ.ย.', 'ธ.ค.', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.']
        table_data = [
            ['กิจกรรมดำเนินงาน'] + [f"ปี พ.ศ. {int(project_data['project_year'])}" if i < 3 else f"ปี พ.ศ. {int(project_data['project_year']) + 1}" for i in range(12)],
            [''] + months
        ]
        
        for activity in project_data.get('activities', []):
            row = [activity['activity']] + ['X' if month in activity['months'] else '' for month in months]
            table_data.append(row)
        
        table = Table(table_data)
        table_style = TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'THSarabunNew-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 10),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), colors.beige),
            ('TEXTCOLOR', (0,1), (-1,-1), colors.black),
            ('ALIGN', (0,1), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,1), (-1,-1), 'THSarabunNew'),
            ('FONTSIZE', (0,1), (-1,-1), 8),
            ('TOPPADDING', (0,1), (-1,-1), 3),
            ('BOTTOMPADDING', (0,1), (-1,-1), 3),
            ('GRID', (0,0), (-1,-1), 1, colors.black)
        ])
        table.setStyle(table_style)

        # กำหนดความกว้างของคอลัมน์
        col_widths = [3*cm] + [1.3*cm]*12
        table._argW = col_widths
        
        content.append(table)

        # เพิ่มตัวชี้วัดเป้าหมายผลผลิตหลังจากตาราง
        content.append(Paragraph('ตัวชี้วัดเป้าหมายผลผลิต', styles['Heading3']))
        content.append(Paragraph(f"เชิงปริมาณ: {project_data.get('quantity_indicator', '')}", styles['Normal']))
        content.append(Paragraph(f"เชิงคุณภาพ: {project_data.get('quality_indicator', '')}", styles['Normal']))
        content.append(Paragraph(f"เชิงเวลา: {project_data.get('time_indicator', '')}", styles['Normal']))
        content.append(Paragraph(f"เชิงค่าใช้จ่าย: {project_data.get('cost_indicator', '')}", styles['Normal']))

        content.append(Paragraph("16. ผลที่คาดว่าจะเกิด (Impact)", styles['Heading2']))
        content.append(Paragraph(project_data.get('expected_results', ''), styles['Normal']))

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

# เพิ่มการล็อกข้อมูลเพื่อตรวจสอบปัญหา
print(f"Current working directory: {os.getcwd()}")
print(f"Full path to logo: {os.path.abspath(os.path.join(os.path.dirname(__file__), 'static', '1.png'))}")

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
        project_data = {
            "project_budgettype": request.form["project_budgettype"],
            "project_year": request.form["project_year"],
            "project_name": request.form["project_name"],
            "project_style": request.form["project_style"],
            "project_address": request.form["project_address"],
            "project_dotime": request.form["project_dotime"],
            "project_endtime": request.form["project_endtime"],
            "project_target": request.form["project_target"],
            "project_budget": request.form["project_budget"],  # เพิ่มงบประมาณ
            
            "teacher_name": teacher_info[0],
            "branch_name": teacher_info[1],
            "project_status": 0,
        # ข้อมูลที่ไม่ได้บันทึกลงฐานข้อมูล แต่ต้องการแสดงใน PDF
            "output": request.form["output"],
            "strategy": request.form["strategy"],
            "indicator": request.form["indicator"],
            "cluster": request.form["cluster"],
            "commonality": request.form["commonality"],
            "physical_grouping": request.form["physical_grouping"],
            "rationale": request.form["rationale"],
            "objectives": request.form["objectives"],
            "goals": request.form["goals"],
            "output_target": request.form["output_target"],
            "outcome_target": request.form["outcome_target"],
            "project_activity": request.form["project_activity"],
            "compensation": [],
            "expenses": [],
            "activities": [],
            "quantity_indicator": request.form["quantity_indicator"],
            "quality_indicator": request.form["quality_indicator"],
            "time_indicator": request.form["time_indicator"],
            "cost_indicator": request.form["cost_indicator"],
            "expected_results": request.form.get('expected_results', ''),
            
            
        }
        
        # รับข้อมูลแผนปฏิบัติงาน
        activities = request.form.getlist('activity[]')
        project_data["activities"] = []
        for i, activity in enumerate(activities):
            if activity:
                selected_months = request.form.getlist(f'month[{i}][]')
                project_data["activities"].append({
                    'activity': activity,
                    'months': selected_months
                })
        
        
        # รับข้อมูลตัวชี้วัดเป้าหมายผลผลิต
        project_data["quantity_indicator"] = request.form.get('quantity_indicator')
        project_data["quality_indicator"] = request.form.get('quality_indicator')
        project_data["time_indicator"] = request.form.get('time_indicator')
        project_data["cost_indicator"] = request.form.get('cost_indicator')
        
        # รับข้อมูลค่าตอบแทน
        compensation_descriptions = request.form.getlist('compensation_description[]')
        compensation_amounts = request.form.getlist('compensation_amount[]')
        for desc, amount in zip(compensation_descriptions, compensation_amounts):
            if desc and amount:
                project_data["compensation"].append({"description": desc, "amount": float(amount)})
        
        # รับข้อมูลค่าใช้สอย
        expense_descriptions = request.form.getlist('expense_description[]')
        expense_amounts = request.form.getlist('expense_amount[]')
        for desc, amount in zip(expense_descriptions, expense_amounts):
            if desc and amount:
                project_data["expenses"].append({"description": desc, "amount": float(amount)})
        
        # คำนวณยอดรวม
        total_compensation = sum(item['amount'] for item in project_data["compensation"])
        total_expenses = sum(item['amount'] for item in project_data["expenses"])
        grand_total = total_compensation + total_expenses
        
        with get_db_cursor() as (db, cursor):
            query = """INSERT INTO project (project_budgettype, project_year, project_name, project_style, 
                       project_address, project_dotime, project_endtime, project_target, 
                       project_status, teacher_id, project_budget) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
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
                    project_data["project_status"],
                    teacher_id,
                    project_data["project_budget"],
                   
                ),
            )
            db.commit()
            project_id = cursor.lastrowid
        
        # เพิ่มข้อมูลยอดรวมใน project_data สำหรับใช้ในการสร้าง PDF
        project_data["total_compensation"] = total_compensation
        project_data["total_expenses"] = total_expenses
        project_data["grand_total"] = grand_total
        
        # สร้าง PDF
      # สร้าง PDF
        pdf_buffer = create_project_pdf(project_data)
        if pdf_buffer:
            pdf_content = pdf_buffer.getvalue()
            
            with get_db_cursor() as (db, cursor):
                query = "UPDATE project SET project_pdf = %s WHERE project_id = %s"
                cursor.execute(query, (pdf_content, project_id))
                db.commit()
                logging.info(f"PDF uploaded for project_id: {project_id}")
                flash('โครงการและ PDF ถูกบันทึกเรียบร้อยแล้ว', 'success')
        else:
            logging.error("PDF buffer is None")
            flash('เกิดข้อผิดพลาดในการสร้าง PDF', 'error')

        return redirect(url_for('teacher_projects'))

    return render_template("add_project.html", teacher_info=teacher_info)

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
        teachers = get_teachers()
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
    teacher_email,
):
    with get_db_cursor() as (db, cursor):
        query = """UPDATE teacher SET teacher_name = %s, teacher_username = %s, 
                   teacher_password = %s, teacher_phone = %s, teacher_email = %s WHERE teacher_id = %s"""
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
        teacher_password = request.form["teacher_password"]
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
        teacher_password = request.form["teacher_password"]
        teacher_phone = request.form["teacher_phone"]
        teacher_email = request.form["teacher_email"]
        branch_id = request.form["branch_id"]

        with get_db_cursor() as (db, cursor):
            query = """INSERT INTO teacher (teacher_name, teacher_username, teacher_password, 
                                            teacher_phone, teacher_email, branch_id) VALUES (%s, %s, %s, %s, %s, %s)"""
            cursor.execute(
                query,
                (
                    teacher_name,
                    teacher_username,
                    teacher_password,
                    teacher_phone,
                    teacher_email,
                    branch_id,
                ),
            )
            db.commit()

        return redirect(url_for("edit_basic_info"))


@app.route("/add_branch", methods=["GET", "POST"])
@login_required("admin")
def add_branch():
    if request.method == "POST":
        branch_name = request.form["branch_name"]

        with get_db_cursor() as (db, cursor):
            query = "INSERT INTO branch (branch_name) VALUES (%s)"
            cursor.execute(query, (branch_name,))
            db.commit()

        return redirect(url_for("edit_basic_info"))

    return render_template("add_branch.html")


@app.route("/teacher_projects")
@login_required("teacher")
def teacher_projects():
    if "teacher_id" not in session:
        return redirect(url_for("login"))

    teacher_id = session["teacher_id"]
    page = request.args.get('page', 1, type=int)
    per_page = 6  # จำนวนโปรเจคต่อหน้า

    with get_db_cursor() as (db, cursor):
        # นับจำนวนโปรเจคทั้งหมด
        cursor.execute("SELECT COUNT(*) FROM project WHERE teacher_id = %s", (teacher_id,))
        total_projects = cursor.fetchone()[0]

        # คำนวณจำนวนหน้าทั้งหมด
        total_pages = ceil(total_projects / per_page)

        # ดึงข้อมูลโปรเจคตามหน้าที่ต้องการ
        offset = (page - 1) * per_page
        query = """
            SELECT project_id, project_name, project_status, project_statusStart, 
                   CASE WHEN project_pdf IS NOT NULL THEN TRUE ELSE FALSE END as has_pdf
            FROM project 
            WHERE teacher_id = %s 
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, (teacher_id, per_page, offset))
        projects = cursor.fetchall()

    return render_template(
        "teacher_projects.html", 
        projects=projects, 
        page=page, 
        total_pages=total_pages, 
        per_page=per_page
    )


@app.route("/request_approval", methods=["POST"])
@login_required("teacher")
def request_approval():
    project_id = request.form.get("project_id")
    with get_db_cursor() as (db, cursor):
        query = "UPDATE project SET project_status = 1 WHERE project_id = %s"
        cursor.execute(query, (project_id,))
        db.commit()
    return redirect(url_for("teacher_projects"))


@app.route("/project/<int:project_id>")
@login_required("teacher")
def project_detail(project_id):
    with get_db_cursor() as (db, cursor):
        query = """SELECT project.project_id, project.project_name, project.project_year, project.project_style, 
                          project.project_address, DATE(project.project_dotime) as project_dotime, 
                          DATE(project.project_endtime) as project_endtime, 
                          project.project_target, teacher.teacher_name, project.project_statusStart
                   FROM project
                   JOIN teacher ON project.teacher_id = teacher.teacher_id
                   WHERE project.project_id = %s"""
        cursor.execute(query, (project_id,))
        project = cursor.fetchone()

        if not project:
            flash('โครงการไม่พบ', 'error')
            return redirect(url_for('active_projects'))

        cursor.execute("SELECT COUNT(*) as current_participants FROM `join` WHERE project_id = %s", (project_id,))
        result = cursor.fetchone()
        current_count = result[0] if result else 0

        project_dict = {
            'project_id': project[0],
            'project_name': project[1],
            'project_year': project[2],
            'project_style': project[3],
            'project_address': project[4],
            'project_dotime': project[5],
            'project_endtime': project[6],
            'project_target': int(project[7]) if project[7] is not None else 0,
            'teacher_name': project[8],
            'project_statusStart': project[9]
        }

    is_logged_in = 'teacher_id' in session
    return render_template(
        "project_detail.html", project=project_dict, current_count=current_count, is_logged_in=is_logged_in
    )

@app.route("/update_project_statusStart", methods=["POST"])
@login_required("admin")
def update_project_statusStart():
    if "teacher_id" not in session:
        return redirect(url_for("login"))

    project_id = request.form.get("project_id")
    project_status = request.form.get("projectStatus")

    if project_status is not None and project_status != '':
        try:
            project_status = int(project_status)
            with get_db_cursor() as (db, cursor):
                query = "UPDATE project SET project_statusStart = %s WHERE project_id = %s"
                cursor.execute(query, (project_status, project_id))
                db.commit()
            flash('อัพเดทสถานะโครงการเรียบร้อยแล้ว', 'success')
        except ValueError:
            flash('สถานะโครงการไม่ถูกต้อง', 'error')
    else:
        flash('กรุณาเลือกสถานะโครงการ', 'error')

    return redirect(url_for("project_detail", project_id=project_id))
@app.route("/active_projects")
@login_required("teacher")
def active_projects():
    with get_db_cursor() as (db, cursor):
        query = """
        SELECT project_id, project_name, project_dotime, project_endtime
        FROM project
        WHERE project_statusStart = 1
        ORDER BY project_dotime DESC
        """
        cursor.execute(query)
        active_projects = cursor.fetchall()

    return render_template("active_projects.html", projects=active_projects)
@app.route('/update_join_status/<int:join_id>', methods=['POST'])
@login_required("teacher")
def update_join_status(join_id):
    if 'teacher_id' not in session:
        flash('คุณไม่มีสิทธิ์ในการดำเนินการนี้', 'error')
        return redirect(url_for('home'))

    new_status = request.form.get('join_status')
    
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE `join` SET join_status = %s WHERE join_id = %s", (new_status, join_id))
        conn.commit()
        flash('อัพเดทสถานะการเข้าร่วมเรียบร้อยแล้ว', 'success')
    except mysql.connector.Error as err:
        flash(f'เกิดข้อผิดพลาดในการอัพเดทสถานะ: {err}', 'error')
    
    cursor.close()
    conn.close()

    return redirect(request.referrer)

@app.route('/project/<int:project_id>/approve_participants')
@login_required("teacher")
def approve_participants(project_id):
    if 'teacher_id' not in session:
        flash('คุณไม่มีสิทธิ์ในการดำเนินการนี้', 'error')
        return redirect(url_for('home'))

    with get_db_cursor() as (db, cursor):
        cursor.execute("SELECT teacher_id FROM project WHERE project_id = %s", (project_id,))
        project = cursor.fetchone()
        if not project or project[0] != session['teacher_id']:
            flash('คุณไม่มีสิทธิ์อนุมัติผู้เข้าร่วมโครงการนี้', 'error')
            return redirect(url_for('project_detail', project_id=project_id))

        cursor.execute("""
            SELECT join_id, join_name, join_email, join_telephone, join_status
            FROM `join`
            WHERE project_id = %s
        """, (project_id,))
        participants = cursor.fetchall()

        # แปลง tuple เป็น dictionary
        participants = [
            {
                'join_id': p[0],
                'join_name': p[1],
                'join_email': p[2],
                'join_telephone': p[3],
                'join_status': p[4]
            } for p in participants
        ]

    return render_template('approve_participants.html', project_id=project_id, participants=participants)
# ตรวจสอบข้อมูลใหม่ทุกๆ 5 นาที
if __name__ == "__main__":
    app.run(debug=True, port=5000)
