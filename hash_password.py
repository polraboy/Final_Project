# hash_passwords.py
# สคริปต์แยกต่างหากสำหรับแฮชรหัสผ่านที่มีอยู่แล้ว

import mysql.connector
from werkzeug.security import generate_password_hash
from contextlib import contextmanager

@contextmanager
def get_db_cursor():
    db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="project",
        connection_timeout=60,
    )
    try:
        cursor = db.cursor(buffered=True)
        yield db, cursor
    finally:
        cursor.close()
        db.close()

def hash_existing_passwords():
    print("เริ่มต้นกระบวนการแฮชรหัสผ่าน...")
    try:
        with get_db_cursor() as (db, cursor):
            # แฮชรหัสผ่านของครู
            cursor.execute("SELECT teacher_id, teacher_password FROM teacher")
            teachers = cursor.fetchall()
            print(f"พบครูทั้งหมด {len(teachers)} คน")
            
            for i, teacher in enumerate(teachers):
                teacher_id = teacher[0]
                plain_password = teacher[1]
                hashed_password = generate_password_hash(plain_password)
                cursor.execute(
                    "UPDATE teacher SET teacher_password = %s WHERE teacher_id = %s",
                    (hashed_password, teacher_id)
                )
                print(f"แฮชรหัสผ่านสำหรับครู ID {teacher_id} แล้ว ({i+1}/{len(teachers)})")
            
            # แฮชรหัสผ่านของผู้ดูแลระบบ
            cursor.execute("SELECT admin_id, admin_password FROM admin")
            admins = cursor.fetchall()
            print(f"พบผู้ดูแลระบบทั้งหมด {len(admins)} คน")
            
            for i, admin in enumerate(admins):
                admin_id = admin[0]
                plain_password = admin[1]
                hashed_password = generate_password_hash(plain_password)
                cursor.execute(
                    "UPDATE admin SET admin_password = %s WHERE admin_id = %s",
                    (hashed_password, admin_id)
                )
                print(f"แฮชรหัสผ่านสำหรับผู้ดูแลระบบ ID {admin_id} แล้ว ({i+1}/{len(admins)})")
            
            db.commit()
            print("แฮชรหัสผ่านเสร็จสมบูรณ์")
            
    except Exception as e:
        print(f"เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    confirmation = input("การดำเนินการนี้จะแฮชรหัสผ่านทั้งหมดในฐานข้อมูล คุณต้องการดำเนินการต่อใช่หรือไม่? (y/n): ")
    if confirmation.lower() == 'y':
        hash_existing_passwords()
    else:
        print("ยกเลิกการดำเนินการ")