import mysql.connector

connection=mysql.connector.connect(host='localhost',user='root',password='',database='teacher')

if connection.is_connected():
    print('good connect')

else:
    print('bad con')

connection.close()

