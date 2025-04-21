import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def test_email():
    try:
        sender_email = "chawanakorn.ca@gmail.com"  # เปลี่ยนเป็นอีเมลจริง
        password = "nosv mtub ctqn wnbv"  # เปลี่ยนเป็นรหัสผ่านจริง
        recipient_email = "testsoul00@gmail.com"  # เปลี่ยนเป็นอีเมลผู้รับ
        
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = "ทดสอบการส่งอีเมล"
        
        body = "นี่เป็นอีเมลทดสอบ"
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, password)
        text = msg.as_string()
        server.sendmail(sender_email, recipient_email, text)
        server.quit()
        
        print("ส่งอีเมลสำเร็จ!")
    except Exception as e:
        print(f"เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    test_email()