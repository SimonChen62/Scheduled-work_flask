from flask import Flask , request , jsonify,session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_migrate import Migrate
from flask_cors import CORS
import os
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import subprocess
from werkzeug.utils import secure_filename

# --- 部署修改 ---
# 1. 从环境变量获取前端URL，提供一个本地开发的默认值
#    在Render上，你需要设置环境变量 FRONTEND_URL 为你部署后React应用的URL
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:3000')

# 2. 从环境变量获取数据库URL
#    Render会自动提供 DATABASE_URL 环境变量
DATABASE_URL = os.environ.get('DATABASE_URL')

# 3. 从环境变量获取SECRET_KEY，提供一个用于本地开发的默认值
#    在Render上，你需要设置一个高强度的 SECRET_KEY
SECRET_KEY = os.environ.get('SECRET_KEY', 'a-very-secret-key-for-dev')

app = Flask(__name__)
CORS(app, origins=FRONTEND_URL, supports_credentials=True)

# --- 部署修改 (适配Postgres) ---
# 4. 配置数据库和密钥
if DATABASE_URL:
    # 生产环境 (Render): 使用 DATABASE_URL
    # Render 提供的 postgres url 可能是 postgres://...，需要替换为 postgresql://
    if DATABASE_URL.startswith("postgres://"):
        app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    else:
        # 保留对MySQL的支持，以防将来切换
        app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)
else:
    # 本地开发环境: 仍然使用您的MySQL配置
    HOSTNAME="localhost"
    PORT="3306"
    USERNAME="root"
    PASSWORD="Xajdlyld6622"
    DATABASE="flasklearn"
    app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{USERNAME}:{PASSWORD}@{HOSTNAME}:{PORT}/{DATABASE}?charset=utf8mb4'

app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

# 注意：Render的免费服务文件系统是临时的，上传的文件会在服务重启或重新部署后丢失。
# 如果需要持久化存储，建议使用Render的付费Disks功能或第三方对象存储（如AWS S3）。
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ... 您的 User 和 Task 模型定义保持不变 ...
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(300), nullable=False)

class Task(db.Model):
    __tablename__ = 'task'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    task_name = db.Column(db.String(100), nullable=False)
    script_path = db.Column(db.String(255), nullable=False)
    cron_expr = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='stopped')
    created_at = db.Column(db.DateTime, default=datetime.now)
    user = db.relationship('User', backref=db.backref('task', lazy=True))

# --- 部署修改 ---
# 5. 确保 scheduler 使用与 app 相同的数据库配置
scheduler = BackgroundScheduler()
scheduler.add_jobstore(SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI']), 'default')

# 在应用上下文中启动调度器，以确保数据库连接可用
with app.app_context():
    # 检查数据库连接
    try:
        db.session.execute(text('SELECT 1'))
        if not scheduler.running:
            scheduler.start()
    except Exception as e:
        print(f"数据库连接失败或调度器启动失败: {e}")


# ... 您所有的 @app.route(...) 路由函数保持不变 ...
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"error": "the username and pasword cannot be empty"}), 400
    hashed_password = generate_password_hash(password)
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        return jsonify({"error": "the username already exists "}), 400
    new_user = User(username=username, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "registered successfully"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'the username and pasword cannot be empty'}), 400
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password, password):
        user_info = {'id': user.id, 'username': user.username}
        session['user_id']=user.id
        return jsonify({'message': 'logined successfully', 'user': user_info}), 200
    else:
        return jsonify({'error': 'username or password is wrong'}), 401

@app.route('/upload_task', methods=['POST'])
def task():
    if 'user_id' not in session:
        return jsonify({'error': 'please login first'}), 401
    if 'script' not in request.files:
        return jsonify({'error': 'the script cannot be empty'}), 400
    file = request.files['script']
    if file.filename =='':
        return jsonify({'error': 'the script cannot be empty'}), 400
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    return jsonify({"message": "上传成功", "script_path": filepath}), 200

@app.route('/create_task', methods=['POST'])
def create_task():
    if 'user_id' not in session:
        return jsonify({'error': 'please login first'}), 401
    data = request.get_json()
    user_id = session['user_id']
    cron_expression = data.get('cron_expr')
    try:
        parts = cron_expression.split()
        if len(parts) == 5:
            CronTrigger.from_crontab(cron_expression)
        elif len(parts) == 6:
            CronTrigger(second=parts[0], minute=parts[1], hour=parts[2], day=parts[3], month=parts[4], day_of_week=parts[5])
        else:
            raise ValueError("cron表达式必须有5个或6个字段")
    except Exception as e:
        return jsonify({"error": f"cron表达式无效: {str(e)}"}), 400
    new_task=Task(
        user_id=user_id,
        task_name=data['task_name'],
        script_path=data['script_path'],
        cron_expr=cron_expression
    )
    db.session.add(new_task)
    db.session.commit()
    return jsonify({"message": "任务创建成功", "task_id": new_task.id}), 201

def run_script(script_path, task_name):
    try:
        result = subprocess.run(
            ['python', script_path],
            capture_output=True, text=True, check=True
        )
        print(f"任务 '{task_name}' 执行成功. 输出: {result.stdout}")
    except FileNotFoundError:
        print(f"错误: 脚本 '{script_path}' 未找到.")
    except subprocess.CalledProcessError as e:
        print(f"任务 '{task_name}' 执行失败. 错误: {e.stderr}")
    except Exception as e:
        print(f"执行任务 '{task_name}' 时发生未知错误: {str(e)}")

@app.route('/start/<int:task_id>', methods=['POST'])
def start_task(task_id):
    if 'user_id' not in session:
        return jsonify({"error": "please login first"}), 401
    task = Task.query.filter_by(id=task_id,user_id=session['user_id']).first()
    if not task:
        return jsonify({"error": "task not found"}), 404
    trigger = None
    try:
        parts = task.cron_expr.split()
        if len(parts) == 5:
            trigger = CronTrigger.from_crontab(task.cron_expr)
        elif len(parts) == 6:
            trigger = CronTrigger(second=parts[0], minute=parts[1], hour=parts[2], day=parts[3], month=parts[4], day_of_week=parts[5])
        else:
            raise ValueError("数据库中的cron表达式格式不正确")
    except Exception as e:
        return jsonify({"error": f"无法解析cron表达式: {str(e)}"}), 400
    scheduler.add_job(
        run_script, trigger,
        args=[task.script_path, task.task_name],
        id=str(task_id), replace_existing=True
    )
    task.status = 'running'
    db.session.commit()
    return jsonify({"message": "task has started"}), 200

@app.route('/stop/<int:task_id>', methods=['POST'])
def stop_task(task_id):
    if 'user_id' not in session:
        return jsonify({"error": "please login first"}), 401
    task = Task.query.filter_by(id=task_id, user_id=session['user_id']).first()
    if not task:
        return jsonify({"error": "task does not exist"}), 404
    if scheduler.get_job(str(task_id)):
        scheduler.remove_job(str(task_id))
    task.status='stopped'
    db.session.commit()
    return jsonify({"message": "task has stopped"}), 200

@app.route('/get-task',methods=['GET'])
def get_task():
    if 'user_id' not in session:
        return jsonify({"error": "please login first"}), 401
    tasks=Task.query.filter_by(user_id=session['user_id']).all()
    task_list = [{
        "id": task.id, "task_name": task.task_name, "script_path": task.script_path,
        "cron_expr": task.cron_expr, "status": task.status,
        "created_at": task.created_at.strftime("%Y-%m-%d %H:%M:%S")
    } for task in tasks]
    return jsonify({"tasks": task_list}), 200
