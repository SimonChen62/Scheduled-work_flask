from flask import Flask , request , jsonify,session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_migrate import Migrate
from flask_cors import CORS
import os
import hashlib
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler  # 定时任务调度
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # 任务持久化
from apscheduler.triggers.cron import CronTrigger # 导入 CronTrigger 用于解析和验证
from datetime import datetime
import subprocess
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app, origins="http://127.0.0.1:3000", supports_credentials=True)


HOSTNAME="localhost"
PORT="3306"  
USERNAME="root"  
PASSWORD="Xajdlyld6622"
DATABASE="flasklearn"  
# 在 app.config 中添加以下配置（放在 SECRET_KEY 后面）
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # 允许跨域请求携带 Cookie
app.config['SESSION_COOKIE_HTTPONLY'] = True   # 增强安全性（不影响传递）
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://{}:{}@{}:{}/{}?charset=utf8mb4'.format(USERNAME,PASSWORD,HOSTNAME,PORT,DATABASE)
app.config['UPLOAD_FOLDER'] = 'uploads'  # 脚本上传目录，在当前项下自动创建
app.config['SECRET_KEY'] = 'your-secret-key'  # 用于session加密，session['user.id']记录这个id的登录状态
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)  #确保上传目录存在，即帮助创建
db = SQLAlchemy(app)

migrate = Migrate(app, db)  

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)  #表当中的字段，主键/像索引，自动递增
    username = db.Column(db.String(80), unique=True, nullable=False) #不能为空，而且唯一
    password = db.Column(db.String(300), nullable=False)

class Task(db.Model):
    __tablename__ = 'task'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # 关联用户
    task_name = db.Column(db.String(100), nullable=False)  # 任务名称
    script_path = db.Column(db.String(255), nullable=False)  # 脚本文件路径
    cron_expr = db.Column(db.String(50), nullable=False)  # cron表达式
    status = db.Column(db.String(20), default='stopped')  # 状态：running/stopped
    created_at = db.Column(db.DateTime, default=datetime.now)   #不给出，会默认当前时间
    # 关联用户（方便查询）
    user = db.relationship('User', backref=db.backref('task', lazy=True)) #这样可以直接user.task互相访问，backref
    #在需要关联的class中，建立另一个关联=该class的name

scheduler = BackgroundScheduler()
scheduler.add_jobstore(SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI']), 'default')
scheduler.start()

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() # 获取请求体中的数据
    username = data.get('username')
    password = data.get('password')

    # 校验：用户名和密码是否为空
    if not username or not password:
        return jsonify({"error": "the username and pasword cannot be empty"}), 400

    # 密码加密
    hashed_password = generate_password_hash(password) # 加密密码，固定

    # 检查用户名是否已存在
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        return jsonify({"error": "the username already exists "}), 400

    # 创建新用户
    new_user = User(username=username, password=hashed_password)
    db.session.add(new_user)  # 添加到会话
    db.session.commit()       # 提交到数据库

    return jsonify({"message": "registered successfully"}), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
        
    # 检查输入是否为空
    if not username or not password:
        return jsonify({'error': 'the username and pasword cannot be empty'}), 400
        
    user = User.query.filter_by(username=username).first() #查询用户，获得user对象
    if user and check_password_hash(user.password, password):
        user_info = {
            'id': user.id,
            'username': user.username
        }
        session['user_id']=user.id #记录登录状态，为后续给出权限。session这个是自带属性
        print("登录成功后 Session：", dict(session)) 
        return jsonify({'message': 'logined successfully', 'user': user_info}), 200
    else:
        return jsonify({'error': 'username or password is wrong'}), 401


@app.route('/upload_task', methods=['POST']) #上传任务
def task():
    if 'user_id' not in session: #只有在本浏览器登录后才会有这个键名，不同电脑登录互不影响。只要有这个键名就可以
        return jsonify({'error': 'please login first'}), 401
    if 'script' not in request.files: #脚本不能为空，看前端是否返回这个建。查看脚本
        return jsonify({'error': 'the script cannot be empty'}), 400
    file = request.files['script'] #获取上传的文件，放到file对象中
    if file.filename =='':
        return jsonify({'error': 'the script cannot be empty'}), 400
    
    filename = secure_filename(file.filename)  #安全的文件名，防止路径穿越，预处理。对文件名预处理
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename) #关联脚本路径，方便保存
    file.save(filepath) #保存脚本文件

    return jsonify({"message": "上传成功", "script_path": filepath}), 200  #注意，返回了path

@app.route('/create_task', methods=['POST']) #记录创建任务，把脚本路径，cron表达式这些存储到数据库
def create_task():
    if 'user_id' not in session: #同理，有键名就可以
        return jsonify({'error': 'please login first'}), 401
    data = request.get_json()
    user_id = session['user_id'] #从session中获取用户id

    #验证给出的cron表达合法性
    try:
        # 使用 APScheduler 的 CronTrigger 进行验证
        CronTrigger.from_crontab(data['cron_expr'])
    except Exception as e: #如果cron表达式不合法会报错，然后exception就是捕获这个异常的代码并给e,最后打印即可
        return jsonify({"error": f"cron表达式无效: {str(e)}"}), 400
    
    new_task=Task(
        user_id=user_id,
        task_name=data['task_name'],
        script_path=data['script_path'], #查看如何前端传过来，前端？
        cron_expr=data['cron_expr']
    )
    db.session.add(new_task)
    db.session.commit()
    return jsonify({"message": "任务创建成功", "task_id": new_task.id}), 201

def run_script(script_path, task_name):
    """在后台执行脚本的函数"""
    try:
        result = subprocess.run(
            ['python', script_path],
            capture_output=True,
            text=True,
            check=True # 如果脚本执行出错，会抛出 CalledProcessError
        )
        print(f"任务 '{task_name}' 执行成功. 输出: {result.stdout}")
    except FileNotFoundError:
        print(f"错误: 脚本 '{script_path}' 未找到.")
    except subprocess.CalledProcessError as e:
        print(f"任务 '{task_name}' 执行失败. 错误: {e.stderr}")
    except Exception as e:
        print(f"执行任务 '{task_name}' 时发生未知错误: {str(e)}")

@app.route('/start/<int:task_id>', methods=['POST']) #启动任务,并把任务的id传过来，尖括号可以直接获取，作为task_id传递
def start_task(task_id):
    if 'user_id' not in session:
        return jsonify({"error": "please login first"}), 401
    
    task = Task.query.filter_by(id=task_id,user_id=session['user_id']).first() #没找到返回none，first就是帮助提取，前面的访问并根据要求查群，最后提取
    if not task:#为空
        return jsonify({"error": "task not found"}), 404
    
    try:
        # 从 cron 表达式创建触发器
        trigger = CronTrigger.from_crontab(task.cron_expr)
    except Exception as e:
        return jsonify({"error": f"无法解析cron表达式: {str(e)}"}), 400

    scheduler.add_job(
        run_script,
        trigger, # 直接使用创建好的 trigger 对象
        args=[task.script_path, task.task_name], # 通过 args 将脚本路径和任务名传递给 run_script 函数
        id=str(task_id),  # 用任务ID作为唯一标识,起名字，要求必须字符串
        replace_existing=True  # 重复添加时替换
    )
    task.status = 'running'
    db.session.commit() #更新状态
    return jsonify({"message": "task has started"}), 200

@app.route('/stop/<int:task_id>', methods=['POST'])
def stop_task(task_id):
    if 'user_id' not in session:
        return jsonify({"error": "please login first"}), 401
    
    task = Task.query.filter_by(id=task_id, user_id=session['user_id']).first()
    if not task:
        return jsonify({"error": "task does not exist"}), 404
    
    # 增加一个判断，防止因任务不存在而移除失败报错
    if scheduler.get_job(str(task_id)):
        scheduler.remove_job(str(task_id))#移除任务

    task.status='stopped' # 修正拼写错误
    db.session.commit()
    return jsonify({"message": "task has stopped"}), 200

@app.route('/get-task',methods=['GET'])
def get_task(): #返回给前端任务列表
    print("获取任务时的 Session：", dict(session)) 
    if 'user_id' not in session:
        return jsonify({"error": "please login first"}), 401
    
    tasks=Task.query.filter_by(user_id=session['user_id']).all()
    task_list = [{
        "id": task.id,
        "task_name": task.task_name,
        "script_path": task.script_path,
        "cron_expr": task.cron_expr,
        "status": task.status,
        "created_at": task.created_at.strftime("%Y-%m-%d %H:%M:%S")
    } for task in tasks] #前面的输出内容和格式，后面循环遍历
    return jsonify({"tasks": task_list}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    app.run(host='127.0.0.1', port=5000, debug=True)