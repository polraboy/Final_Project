from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from contextlib import contextmanager


app = Flask(__name__)
app.secret_key = "your_secret_key"


# ฟังก์ชันสำหรับการเชื่อมต่อฐานข้อมูลและ cursor
@contextmanager
def get_db_cursor():
    db = mysql.connector.connect(
        host="localhost", user="root", password="", database="project"
    )
    cursor = db.cursor()
    yield db, cursor
    db.close()


# ตัวอย่างสำหรับ Flask app
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        # ใช้ context manager สำหรับ cursor
        with get_db_cursor() as (db, cursor):
            # ตรวจสอบข้อมูลล็อกอินในตาราง teacher
            query_teacher = "SELECT * FROM teacher WHERE teacher_username = %s AND teacher_password = %s"
            cursor.execute(query_teacher, (username, password))
            teacher = cursor.fetchone()

            # ถ้าไม่พบใน teacher, ตรวจสอบในตาราง admin
            if not teacher:
                query_admin = "SELECT * FROM admin WHERE admin_username = %s AND admin_password = %s"
                cursor.execute(query_admin, (username, password))
                admin = cursor.fetchone()

                if admin:
                    # ถ้าล็อกอินสำเร็จในตาราง admin, เก็บข้อมูลล็อกอินใน session
                    session["admin_id"] = admin[0]
                    session["admin_name"] = admin[1]
                    return redirect(
                        url_for("admin_home")
                    )  # Redirect ไปยังหน้า admin_home
                else:
                    return "Login failed. Please check your username and password."

            # ถ้าล็อกอินสำเร็จในตาราง teacher, เก็บข้อมูลล็อกอินใน session
            session["teacher_id"] = teacher[0]
            session["teacher_name"] = teacher[1]
            return redirect(url_for("teacher_home"))  # Redirect ไปยังหน้า teacher_home

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    # เช็คว่ามี session ของ admin_id หรือ teacher_id หรือไม่
    if "admin_id" in session:
        return f"Hello, Admin {session['admin_name']}! This is your dashboard."
    elif "teacher_id" in session:
        return f"Hello, Teacher {session['teacher_name']}! This is your dashboard."
    else:
        return redirect(url_for("login"))


@app.route("/logout")
def logout():
    # ลบ session ทั้งหมด
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin_home")
def admin_home():
    # ตรวจสอบว่ามี session ของ admin_id หรือไม่
    if "admin_id" in session:
        return render_template("admin_home.html")
    else:
        return redirect(url_for("login"))  # ถ้าไม่มี session ให้เด้งไปหน้า login


@app.route("/aprove_project")
def aprove_project():
    # ตรวจสอบว่ามี session ของ admin_id หรือไม่
    if "admin_id" in session:
        # เรียกใช้งานฟังก์ชันเพื่อดึงข้อมูลโครงการ
        projects = get_projects()
        return render_template(
            "aprove_project.html", projects=projects, get_status=get_status
        )
    else:
        return redirect(url_for("login"))  # ถ้าไม่มี session ให้เด้งไปหน้า login


@app.route("/teacher_home")
def teacher_home():
    # ตรวจสอบว่ามี session ของ teacher_id หรือไม่
    if "teacher_id" in session:
        return render_template("teacher_home.html")
    else:
        return redirect(url_for("login"))  # ถ้าไม่มี session ให้เด้งไปหน้า login


def get_projects():
    db = mysql.connector.connect(
        host="localhost", user="root", password="", database="project"
    )
    cursor = db.cursor()

    cursor.execute(
        "SELECT project_id, project_name, project_status FROM project"
    )  # เปลี่ยนจาก Project_id เป็น project_id
    projects = cursor.fetchall()

    db.close()
    return projects


# สร้างฟังก์ชันสำหรับแปลงสถานะโปรเจกต์เป็นข้อความที่เข้าใจง่าย
def get_status(status_code):
    if status_code == 0:
        return "ยังไม่ยื่นอนุมัติ"
    elif status_code == 1:
        return "รออนุมัติ"
    elif status_code == 2:
        return "อนุมัติแล้ว"
    else:
        return "ไม่มีข้อมูล"


from flask import session






@app.route("/add_project", methods=["GET", "POST"])
def add_project():
    if request.method == "POST":
        project_budgettype = request.form["project_budgettype"]
        project_year = request.form["project_year"]
        project_name = request.form["project_name"]
        project_style = request.form["project_style"]
        project_address = request.form["project_address"]
        project_dotime = request.form["project_dotime"]
        project_endtime = request.form["project_endtime"]
        project_target = request.form["project_target"]
        project_budget = request.form["project_budget"]
        project_status = request.form["project_status"]
        project_statusStart = request.form["project_statusStart"]
        teacher_id = request.form["teacher_id"]

        with get_db_cursor() as (db, cursor):
            query = "INSERT INTO project (project_budgettype, project_year, project_name, project_style, project_address, project_dotime, project_endtime, project_target, project_budget, project_status, project_statusStart, teacher_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            cursor.execute(
                query,
                (
                    project_budgettype,
                    project_year,
                    project_name,
                    project_style,
                    project_address,
                    project_dotime,
                    project_endtime,
                    project_target,
                    project_budget,
                    project_status,
                    project_statusStart,
                    teacher_id,
                ),
            )
            db.commit()

        return redirect(url_for("aprove_project"))

    # หากเป็น method GET ให้ดึงข้อมูลอาจารย์แล้วส่งไปยังหน้า add_project.html
    teachers = get_teachers()
    return render_template("add_project.html", teachers=teachers)

def get_teachers(teacher_id=None):
    with get_db_cursor() as (db, cursor):
        if teacher_id:
            query = "SELECT teacher_id, teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email, branch_name FROM teacher JOIN branch ON teacher.branch_id = branch.branch_id WHERE teacher_id = %s"
            cursor.execute(query, (teacher_id,))
        else:
            query = "SELECT teacher_id, teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email, branch_name FROM teacher JOIN branch ON teacher.branch_id = branch.branch_id"
            cursor.execute(query)
        teachers = cursor.fetchall()
    return teachers

@app.route("/edit_basic_info", methods=["GET", "POST"])
def edit_basic_info():
    if request.method == "POST":
        # รับข้อมูลจากฟอร์มแก้ไขข้อมูลพื้นฐาน
        branch_id = request.form["branch_id"]
        teacher_name = request.form["teacher_name"]
        teacher_username = request.form["teacher_username"]
        teacher_password = request.form["teacher_password"]
        teacher_phone = request.form["teacher_phone"]
        teacher_email = request.form["teacher_email"]

        # ดำเนินการเกี่ยวกับการบันทึกข้อมูลลงฐานข้อมูล หรืออื่นๆ ตามต้องการ
        # ตัวอย่างเช่น:
        # save_to_database(branch_id, teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email)

        # เมื่อเสร็จสิ้นการแก้ไข ให้ redirect ไปยังหน้าที่ต้องการ
        if "admin_id" in session:
            return redirect(url_for("admin_home"))

    # ตรวจสอบว่าผู้ใช้เป็น admin หรือไม่
    if "admin_id" in session:
        teachers = get_teachers()  # ดึงข้อมูลอาจารย์จากฐานข้อมูล
        return render_template("edit_basic_info.html", teachers=teachers)
    else:
        # หากไม่ใช่ admin ให้เด้งไปยังหน้า login
        return redirect(url_for("login"))

def get_teacher_by_id(teacher_id):
    with get_db_cursor() as (db, cursor):
        query = """
        SELECT t.teacher_id, t.teacher_name, t.teacher_username, t.teacher_password, t.teacher_phone, t.teacher_email, b.branch_name 
        FROM teacher t 
        JOIN branch b ON t.branch_id = b.branch_id 
        WHERE t.teacher_id = %s
        """
        cursor.execute(query, (teacher_id,))
        teacher = cursor.fetchone()
    return teacher

def update_teacher(teacher_id, branch_id, teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email):
    with get_db_cursor() as (db, cursor):
        query = "UPDATE teacher SET branch_id = %s, teacher_name = %s, teacher_username = %s, teacher_password = %s, teacher_phone = %s, teacher_email = %s WHERE teacher_id = %s"
        cursor.execute(query, (branch_id, teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email, teacher_id))
        db.commit()

@app.route('/edit_teacher/<int:teacher_id>', methods=['GET', 'POST'])
def edit_teacher(teacher_id):
    if request.method == 'GET':
        teacher = get_teacher_by_id(teacher_id)
        if teacher:
            return render_template('edit_teacher.html', teacher=teacher)
        else:
            return "Teacher not found"
    elif request.method == 'POST':
       
        teacher_name = request.form["teacher_name"]
        teacher_username = request.form["teacher_username"]
        teacher_password = request.form["teacher_password"]
        teacher_phone = request.form["teacher_phone"]
        teacher_email = request.form["teacher_email"]

        # เรียกใช้ฟังก์ชันสำหรับปรับปรุงข้อมูลอาจารย์ในฐานข้อมูล
        update_teacher(teacher_id, teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email)

        # หลังจากปรับปรุงข้อมูลเสร็จสิ้น ให้เปลี่ยนเส้นทางไปยังหน้า edit_basic_info หรือหน้าอื่นๆ ตามที่คุณต้องการ
        return redirect(url_for("edit_basic_info"))


def update_teacher(teacher_id, teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email):
    with get_db_cursor() as (db, cursor):
        query = "UPDATE teacher SET teacher_name = %s, teacher_username = %s, teacher_password = %s, teacher_phone = %s, teacher_email = %s WHERE teacher_id = %s"
        cursor.execute(query, (teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email, teacher_id))
        db.commit()

# สร้างเส้นทางสำหรับหน้า add_teacher
# ในส่วนของหน้า "add_teacher"
@app.route("/add_teacher", methods=["GET", "POST"])
def add_teacher():
    if request.method == 'GET':
        # ดึงข้อมูลสาขาจากฐานข้อมูล
        branches = get_branches_from_database()  # แทนที่ด้วยฟังก์ชันที่คุณใช้ในการดึงข้อมูลสาขา
        return render_template('add_teacher.html', branches=branches)
    elif request.method == 'POST':
        # รับข้อมูลจากฟอร์ม
        teacher_name = request.form["teacher_name"]
        teacher_username = request.form["teacher_username"]
        teacher_password = request.form["teacher_password"]
        teacher_phone = request.form["teacher_phone"]
        teacher_email = request.form["teacher_email"]
        branch_id = request.form["branch_id"]

        # เชื่อมต่อฐานข้อมูลและเพิ่มข้อมูลอาจารย์
        with get_db_cursor() as (db, cursor):
            query = "INSERT INTO teacher (teacher_name, teacher_username, teacher_password, teacher_phone, teacher_email, branch_id) VALUES (%s, %s, %s, %s, %s, %s)"
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

    
def get_branches_from_database():
    with get_db_cursor() as (db, cursor):
        query = "SELECT * FROM branch"
        cursor.execute(query)
        branches = cursor.fetchall()
    return branches

 
if __name__ == "__main__":
    app.run(debug=True)
